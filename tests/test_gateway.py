"""Tests for the deny-by-default tool gateway."""

from __future__ import annotations

from typing import Any

import pytest

from ts_harness.audit.logger import AuditLogger
from ts_harness.core.models import RiskTier
from ts_harness.finops.budget import BudgetExceededError, BudgetManager
from ts_harness.gateway.gateway import (
    ExecutionContext,
    PolicyDecision,
    ToolDeniedError,
    ToolGateway,
    ToolNotFoundError,
    ToolSpec,
)
from ts_harness.killswitch.manager import KillSwitchActiveError, KillSwitchManager


class AllowT0Checker:
    """Test-only policy checker that allows T0 tools."""

    def evaluate(
        self,
        tool_name: str,
        risk_tier: RiskTier,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> PolicyDecision:
        if risk_tier == RiskTier.T0:
            return PolicyDecision(allowed=True, reason="T0 allowed in test", rule_id="test-t0")
        return PolicyDecision(allowed=False, reason="Non-T0 denied", rule_id="test-deny")


def test_gateway_denies_by_default(
    audit_logger: AuditLogger,
    budget_manager: BudgetManager,
    kill_switch: KillSwitchManager,
) -> None:
    gateway = ToolGateway(
        audit_logger=audit_logger,
        budget_manager=budget_manager,
        kill_switch=kill_switch,
    )
    gateway.register(
        ToolSpec(
            name="read_notes",
            description="Read local notes",
            risk_tier=RiskTier.T0,
            handler=lambda args, ctx: "notes",
        )
    )

    with pytest.raises(ToolDeniedError):
        gateway.execute("read_notes", {}, ExecutionContext(task_id="t1"))

    with pytest.raises(ToolNotFoundError):
        gateway.execute("missing_tool", {}, ExecutionContext(task_id="t1"))


def test_gateway_executes_when_allowed_and_respects_killswitch_and_budget(
    audit_logger: AuditLogger,
    budget_manager: BudgetManager,
    kill_switch: KillSwitchManager,
) -> None:
    gateway = ToolGateway(
        audit_logger=audit_logger,
        budget_manager=budget_manager,
        kill_switch=kill_switch,
        policy_checker=AllowT0Checker(),
    )
    gateway.register(
        ToolSpec(
            name="search_web",
            description="Search web",
            risk_tier=RiskTier.T0,
            connector_name="web",
            estimated_cost=1.5,
            handler=lambda args, ctx: {"hits": [args.get("q")]},
        )
    )

    ctx = ExecutionContext(task_id="t1", workflow_name="research_digest", actor="executor")
    res = gateway.execute("search_web", {"q": "python"}, ctx)
    assert res.output == {"hits": ["python"]}

    # Second call exceeds task_limit of 2.0 SGD (1.5 + 1.5 = 3.0)
    with pytest.raises(BudgetExceededError):
        gateway.execute("search_web", {"q": "again"}, ctx)

    # Kill switch blocks before policy/budget
    kill_switch.revoke_connector("web", reason="maintenance")
    with pytest.raises(KillSwitchActiveError):
        gateway.execute("search_web", {"q": "blocked"}, ctx)
