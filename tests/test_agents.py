"""Tests for Planner, Executor, and separate Verifier agents."""

from __future__ import annotations

from pathlib import Path

import pytest

from ts_harness.agents.models import ModelMessage, StubModelClient
from ts_harness.agents.roles import (
    ExecutorAgent,
    PlannerAgent,
    PlanStep,
    SubAgentLimitError,
    SubAgentLimits,
    VerifierAgent,
)
from ts_harness.audit.logger import AuditLogger
from ts_harness.config import ModelRoleConfig
from ts_harness.core.models import RiskTier
from ts_harness.finops.budget import BudgetManager
from ts_harness.gateway.gateway import ExecutionContext, ToolGateway, ToolSpec
from ts_harness.killswitch.manager import KillSwitchManager
from ts_harness.policy.engine import PolicyEngine


def test_planner_executor_and_separate_verifier_flow(
    audit_logger: AuditLogger,
    budget_manager: BudgetManager,
    kill_switch: KillSwitchManager,
) -> None:
    policy = PolicyEngine.from_yaml(Path("policies/strict.yaml"))
    gateway = ToolGateway(
        audit_logger=audit_logger,
        budget_manager=budget_manager,
        kill_switch=kill_switch,
        policy_checker=policy,
    )
    gateway.register(
        ToolSpec(
            name="read_report",
            description="Read quarterly numbers",
            risk_tier=RiskTier.T0,
            handler=lambda args, ctx: {
                "text": "Q4 revenue was 100 + 25 = 125",
                "urls": ["https://intranet.example/q4"],
            },
        )
    )

    def scripted_responder(
        messages: list[ModelMessage],
        role_cfg: ModelRoleConfig,
        system_prompt: str | None,
    ) -> str:
        if system_prompt and "Executor" in system_prompt:
            return "Total Q4 revenue is 100 + 25 = 125 (source: https://intranet.example/q4)."
        if system_prompt and "Verifier" in system_prompt:
            return "PASS: Output matches sources and arithmetic."
        return "Plan: read_report"

    client = StubModelClient(responder=scripted_responder)
    planner = PlannerAgent(
        model_client=client,
        role_config=ModelRoleConfig(provider="anthropic", model_name="claude-sonnet-4-20250514"),
        allowed_tools={"read_report"},
        budget_manager=budget_manager,
    )
    executor = ExecutorAgent(
        model_client=client,
        role_config=ModelRoleConfig(provider="anthropic", model_name="claude-sonnet-4-20250514"),
        gateway=gateway,
        allowed_tools={"read_report"},
        budget_manager=budget_manager,
    )
    verifier = VerifierAgent(
        model_client=client,
        role_config=ModelRoleConfig(provider="anthropic", model_name="claude-haiku-4-5-20251001"),
        budget_manager=budget_manager,
    )

    plan = planner.plan(
        "Summarise Q4 revenue",
        proposed_steps=[PlanStep(tool_name="read_report")],
        task_id="t1",
        workflow_name="weekly_review",
    )
    exec_report = executor.execute(
        "Summarise Q4 revenue",
        plan,
        ExecutionContext(task_id="t1", workflow_name="weekly_review", trust_level="user"),
    )
    ver_report = verifier.verify(
        "Summarise Q4 revenue",
        exec_report,
        task_id="t1",
        workflow_name="weekly_review",
    )

    assert ver_report.passed is True
    assert "100 + 25 = 125" in ver_report.checked_arithmetic
    # Planner + Executor + Verifier = 3 distinct model calls
    assert len(client.calls) == 3

    # Verify arithmetic error detection
    exec_report.output_text = "Total is 100 + 25 = 999 (source: https://intranet.example/q4)."
    bad_ver = verifier.verify("Summarise Q4 revenue", exec_report)
    assert bad_ver.passed is False
    assert any("Arithmetic mismatch" in issue for issue in bad_ver.issues)


def test_subagent_depth_and_fanout_limits() -> None:
    limits = SubAgentLimits(max_depth=2, max_fanout=3)
    limits.check_spawn(current_depth=1, requested_fanout=2)

    with pytest.raises(SubAgentLimitError, match="depth"):
        limits.check_spawn(current_depth=2, requested_fanout=1)

    with pytest.raises(SubAgentLimitError, match="fan-out"):
        limits.check_spawn(current_depth=0, requested_fanout=4)
