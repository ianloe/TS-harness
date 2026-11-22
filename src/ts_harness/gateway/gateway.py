"""Governed tool gateway: deny-by-default, kill-switch, budget, and audit enforcement."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, Field

from ts_harness.audit.logger import AuditLogger
from ts_harness.config import Currency
from ts_harness.core.models import DataClass, RiskTier
from ts_harness.finops.budget import BudgetExceededError, BudgetManager
from ts_harness.killswitch.manager import KillSwitchActiveError, KillSwitchManager


class ToolDeniedError(PermissionError):
    """Raised when a tool call is denied by policy."""


class ToolNotFoundError(KeyError):
    """Raised when a requested tool is not registered."""


class PolicyDecision(BaseModel):
    """Outcome of a policy evaluation."""

    allowed: bool
    reason: str
    rule_id: str | None = None


class ExecutionContext(BaseModel):
    """Context passed to every tool evaluation and execution."""

    task_id: str | None = None
    workflow_name: str | None = None
    actor: str = "system"
    data_class: DataClass = DataClass.INTERNAL
    trust_level: str = "user"
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyChecker(Protocol):
    """Protocol for policy evaluation before tool execution."""

    def evaluate(
        self,
        tool_name: str,
        risk_tier: RiskTier,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> PolicyDecision:
        """Return whether the tool invocation is allowed."""
        ...


class DenyAllPolicyChecker:
    """Default deny-by-default policy checker."""

    def evaluate(
        self,
        tool_name: str,
        risk_tier: RiskTier,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> PolicyDecision:
        return PolicyDecision(
            allowed=False,
            reason=(
                f"Deny by default: no policy rule allows tool "
                f"'{tool_name}' ({risk_tier.value})."
            ),
            rule_id="default-deny",
        )


class ToolResult(BaseModel):
    """Result returned by a governed tool execution."""

    tool_name: str
    output: Any
    cost_amount: float = 0.0
    cost_currency: Currency = "SGD"


class ToolSpec(BaseModel):
    """Registration metadata and handler for a tool."""

    model_config = {"arbitrary_types_allowed": True}

    name: str
    description: str
    risk_tier: RiskTier = RiskTier.T0
    connector_name: str | None = None
    estimated_cost: float = 0.0
    handler: Callable[[dict[str, Any], ExecutionContext], Any]


class ToolGateway:
    """Single governed entry point for all native and MCP tool invocations."""

    def __init__(
        self,
        *,
        audit_logger: AuditLogger,
        budget_manager: BudgetManager,
        kill_switch: KillSwitchManager,
        policy_checker: PolicyChecker | None = None,
        currency: Currency = "SGD",
    ) -> None:
        self._audit = audit_logger
        self._budget = budget_manager
        self._kill_switch = kill_switch
        self._policy: PolicyChecker = policy_checker or DenyAllPolicyChecker()
        self._currency: Currency = currency
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """Register a tool with the gateway."""
        self._tools[spec.name] = spec

    def list_tools(self) -> list[str]:
        """Return registered tool names."""
        return sorted(self._tools.keys())

    def execute(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Validate kill switch, policy, and budget, then execute and audit."""
        spec = self._tools.get(tool_name)
        if spec is None:
            self._audit.append(
                event_type="tool.not_found",
                actor=context.actor,
                task_id=context.task_id,
                payload={"tool_name": tool_name},
            )
            raise ToolNotFoundError(f"Tool '{tool_name}' is not registered.")

        blocked, block_reason = self._kill_switch.is_blocked(
            workflow_name=context.workflow_name,
            connector_name=spec.connector_name,
        )
        if blocked:
            self._audit.append(
                event_type="tool.killswitch_blocked",
                actor=context.actor,
                task_id=context.task_id,
                payload={"tool_name": tool_name, "reason": block_reason},
            )
            raise KillSwitchActiveError(block_reason or "Kill switch active.")

        decision = self._policy.evaluate(tool_name, spec.risk_tier, args, context)
        if not decision.allowed:
            self._audit.append(
                event_type="tool.denied",
                actor=context.actor,
                task_id=context.task_id,
                payload={
                    "tool_name": tool_name,
                    "risk_tier": spec.risk_tier.value,
                    "rule_id": decision.rule_id,
                    "reason": decision.reason,
                },
            )
            raise ToolDeniedError(decision.reason)

        budget_status = self._budget.check_budget(
            task_id=context.task_id,
            workflow_name=context.workflow_name,
            estimated_cost=spec.estimated_cost,
        )
        if not budget_status.allowed:
            self._audit.append(
                event_type="tool.budget_blocked",
                actor=context.actor,
                task_id=context.task_id,
                payload={"tool_name": tool_name, "reason": budget_status.reason},
            )
            raise BudgetExceededError(budget_status.reason or "Budget limit reached.")

        output = spec.handler(args, context)

        if spec.estimated_cost > 0.0:
            self._budget.record_spend(
                amount=spec.estimated_cost,
                currency=self._currency,
                task_id=context.task_id,
                workflow_name=context.workflow_name,
                tool_name=tool_name,
            )

        self._audit.append(
            event_type="tool.executed",
            actor=context.actor,
            task_id=context.task_id,
            payload={
                "tool_name": tool_name,
                "risk_tier": spec.risk_tier.value,
                "rule_id": decision.rule_id,
            },
            cost_amount=spec.estimated_cost,
            cost_currency=self._currency,
        )

        return ToolResult(
            tool_name=tool_name,
            output=output,
            cost_amount=spec.estimated_cost,
            cost_currency=self._currency,
        )
