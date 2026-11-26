"""Scoped Planner, Executor, and Verifier agents with sub-agent depth/fan-out limits."""

from __future__ import annotations

import ast
import operator
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from ts_harness.agents.models import ModelClient, ModelMessage
from ts_harness.config import ModelRoleConfig
from ts_harness.finops.budget import BudgetManager
from ts_harness.gateway.gateway import ExecutionContext, ToolGateway
from ts_harness.guardrails.filters import check_output
from ts_harness.security.sandbox import DockerSandboxRunner


class SubAgentLimitError(RuntimeError):
    """Raised when sub-agent depth or fan-out exceeds configured bounds."""


class SubAgentLimits(BaseModel):
    """Bounds on recursive sub-agent spawning and parallel fan-out."""

    max_depth: int = Field(default=2, ge=0, le=5)
    max_fanout: int = Field(default=3, ge=1, le=10)

    def check_spawn(self, *, current_depth: int, requested_fanout: int = 1) -> None:
        if current_depth >= self.max_depth:
            raise SubAgentLimitError(
                f"Sub-agent depth limit reached ({current_depth} >= {self.max_depth})."
            )
        if requested_fanout > self.max_fanout:
            raise SubAgentLimitError(
                f"Sub-agent fan-out limit exceeded ({requested_fanout} > {self.max_fanout})."
            )


class PlanStep(BaseModel):
    """A single step in an execution plan."""

    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    purpose: str = ""


class AgentPlan(BaseModel):
    """Structured output of PlannerAgent."""

    steps: list[PlanStep] = Field(default_factory=list)
    rationale: str = ""
    cost_amount: float = 0.0


class ExecutionReport(BaseModel):
    """Structured output of ExecutorAgent."""

    output_text: str
    tool_outputs: list[dict[str, Any]] = Field(default_factory=list)
    source_urls: set[str] = Field(default_factory=set)
    cost_amount: float = 0.0


class VerificationReport(BaseModel):
    """Structured output of VerifierAgent (separate call from ExecutorAgent)."""

    passed: bool
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checked_arithmetic: list[str] = Field(default_factory=list)
    cost_amount: float = 0.0


class PlannerAgent:
    """Produces a bounded plan using a read-only/planning tool scope."""

    def __init__(
        self,
        *,
        model_client: ModelClient,
        role_config: ModelRoleConfig,
        allowed_tools: set[str] | None = None,
        budget_manager: BudgetManager | None = None,
    ) -> None:
        self._client = model_client
        self._role_config = role_config
        self._allowed_tools = allowed_tools
        self._budget = budget_manager

    def plan(
        self,
        request: str,
        *,
        proposed_steps: list[PlanStep] | None = None,
        task_id: str | None = None,
        workflow_name: str | None = None,
    ) -> AgentPlan:
        response = self._client.complete(
            [ModelMessage(role="user", content=request)],
            role_config=self._role_config,
            system_prompt="You are the TS-Harness Planner. Produce minimal, reversible steps.",
        )
        if self._budget is not None and response.cost_amount > 0:
            self._budget.record_spend(
                amount=response.cost_amount,
                currency=response.currency,
                task_id=task_id,
                workflow_name=workflow_name,
                model_name=response.model_name,
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
            )

        steps = list(proposed_steps or [])
        if self._allowed_tools is not None:
            steps = [s for s in steps if s.tool_name in self._allowed_tools]

        return AgentPlan(
            steps=steps,
            rationale=response.content,
            cost_amount=response.cost_amount,
        )


class ExecutorAgent:
    """Executes plan steps strictly through the governed ToolGateway."""

    def __init__(
        self,
        *,
        model_client: ModelClient,
        role_config: ModelRoleConfig,
        gateway: ToolGateway,
        allowed_tools: set[str] | None = None,
        budget_manager: BudgetManager | None = None,
    ) -> None:
        self._client = model_client
        self._role_config = role_config
        self._gateway = gateway
        self._allowed_tools = allowed_tools
        self._budget = budget_manager

    def execute(
        self,
        request: str,
        plan: AgentPlan,
        context: ExecutionContext,
    ) -> ExecutionReport:
        tool_outputs: list[dict[str, Any]] = []
        source_urls: set[str] = set()
        total_cost = 0.0

        for step in plan.steps:
            if self._allowed_tools is not None and step.tool_name not in self._allowed_tools:
                raise PermissionError(
                    f"ExecutorAgent tool scope denies '{step.tool_name}'."
                )
            res = self._gateway.execute(step.tool_name, step.args, context)
            total_cost += res.cost_amount
            tool_outputs.append({"tool": step.tool_name, "output": res.output})
            if isinstance(res.output, dict):
                urls = res.output.get("urls")
                if isinstance(urls, list):
                    source_urls.update(str(u) for u in urls)

        response = self._client.complete(
            [
                ModelMessage(
                    role="user",
                    content=f"Request: {request}\nTool outputs: {tool_outputs}",
                )
            ],
            role_config=self._role_config,
            system_prompt="You are the TS-Harness Executor. Summarise only grounded tool outputs.",
        )
        total_cost += response.cost_amount
        if self._budget is not None and response.cost_amount > 0:
            self._budget.record_spend(
                amount=response.cost_amount,
                currency=response.currency,
                task_id=context.task_id,
                workflow_name=context.workflow_name,
                model_name=response.model_name,
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
            )

        return ExecutionReport(
            output_text=response.content,
            tool_outputs=tool_outputs,
            source_urls=source_urls,
            cost_amount=round(total_cost, 6),
        )


_ARITHMETIC_CLAIM = re.compile(r"(\d+(?:\.\d+)?\s*[+\-*/]\s*\d+(?:\.\d+)?)\s*=\s*(\d+(?:\.\d+)?)")


def _safe_eval_arithmetic(expr: str) -> float:
    ops: dict[type[ast.operator], Callable[[float, float], float]] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
    }
    node = ast.parse(expr, mode="eval").body
    if isinstance(node, ast.BinOp) and type(node.op) in ops:
        left = float(ast.literal_eval(node.left))
        right = float(ast.literal_eval(node.right))
        return ops[type(node.op)](left, right)
    raise ValueError(f"Unsupported arithmetic expression: {expr}")


class VerifierAgent:
    """Separate verifier call checking sources, arithmetic, and original request."""

    def __init__(
        self,
        *,
        model_client: ModelClient,
        role_config: ModelRoleConfig,
        sandbox: DockerSandboxRunner | None = None,
        budget_manager: BudgetManager | None = None,
    ) -> None:
        self._client = model_client
        self._role_config = role_config
        self._sandbox = sandbox
        self._budget = budget_manager

    def verify(
        self,
        original_request: str,
        report: ExecutionReport,
        *,
        task_id: str | None = None,
        workflow_name: str | None = None,
    ) -> VerificationReport:
        issues: list[str] = []
        warnings: list[str] = []
        checked_arithmetic: list[str] = []

        # 1. Output guardrail check: secret leakage, hallucinated URLs, style
        out_check = check_output(
            report.output_text,
            allowed_urls=report.source_urls if report.source_urls else None,
            check_style=True,
        )
        issues.extend(out_check.violations)
        warnings.extend(out_check.warnings)

        # 2. Arithmetic verification via sandbox (when provided) or AST evaluator
        for expr, claimed in _ARITHMETIC_CLAIM.findall(report.output_text):
            checked_arithmetic.append(f"{expr} = {claimed}")
            expected = self._compute_arithmetic(expr)
            if abs(expected - float(claimed)) > 1e-6:
                issues.append(
                    f"Arithmetic mismatch: '{expr} = {claimed}' (expected {expected})."
                )

        # 3. Separate model call to check alignment with original request
        response = self._client.complete(
            [
                ModelMessage(
                    role="user",
                    content=(
                        f"Original request: {original_request}\n"
                        f"Output: {report.output_text}\n"
                        f"Sources: {sorted(report.source_urls)}"
                    ),
                )
            ],
            role_config=self._role_config,
            system_prompt="You are the TS-Harness Verifier. Check facts against sources.",
        )
        if self._budget is not None and response.cost_amount > 0:
            self._budget.record_spend(
                amount=response.cost_amount,
                currency=response.currency,
                task_id=task_id,
                workflow_name=workflow_name,
                model_name=response.model_name,
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
            )

        if "FAIL:" in response.content:
            issues.append(response.content)

        return VerificationReport(
            passed=len(issues) == 0,
            issues=issues,
            warnings=warnings,
            checked_arithmetic=checked_arithmetic,
            cost_amount=response.cost_amount,
        )

    def _compute_arithmetic(self, expr: str) -> float:
        if self._sandbox is not None:
            res = self._sandbox.run_python(f"print({expr})")
            if res.exit_code == 0 and res.stdout.strip():
                return float(res.stdout.strip())
        return _safe_eval_arithmetic(expr)
