"""Tests for YAML policy engine, rule dimensions, explain mode, and gateway integration."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ts_harness.audit.logger import AuditLogger
from ts_harness.core.models import DataClass, RiskTier
from ts_harness.finops.budget import BudgetManager
from ts_harness.gateway.gateway import ExecutionContext, ToolDeniedError, ToolGateway, ToolSpec
from ts_harness.killswitch.manager import KillSwitchManager
from ts_harness.policy.engine import PolicyEngine
from ts_harness.policy.schema import PolicyRule, PolicySet, RuleEffect, RuleMatch, TimeWindow


def test_strict_yaml_policy_and_explain_mode() -> None:
    engine = PolicyEngine.from_yaml(Path("policies/strict.yaml"))

    t0_exp = engine.explain(
        "read_email",
        RiskTier.T0,
        {},
        ExecutionContext(trust_level="user"),
    )
    assert t0_exp.decision.allowed is True
    assert t0_exp.decision.rule_id == "allow-readonly-trusted"

    t1_draft = engine.explain(
        "draft_reply",
        RiskTier.T1,
        {},
        ExecutionContext(trust_level="user"),
    )
    assert t1_draft.decision.allowed is True

    t1_other = engine.explain(
        "modify_calendar",
        RiskTier.T1,
        {},
        ExecutionContext(trust_level="user"),
    )
    assert t1_other.decision.allowed is False
    assert t1_other.decision.rule_id == "default-deny"

    t2_send = engine.explain(
        "send_email",
        RiskTier.T2,
        {},
        ExecutionContext(trust_level="user"),
    )
    assert t2_send.decision.allowed is False
    assert "Human approval required" in t2_send.summary

    t2_approved = engine.explain(
        "send_email",
        RiskTier.T2,
        {},
        ExecutionContext(trust_level="user", metadata={"approved": True}),
    )
    assert t2_approved.decision.allowed is True


def test_t3_cannot_be_overridden_even_by_permissive_yaml() -> None:
    permissive = PolicyEngine(
        PolicySet(
            version="1.0",
            name="allow-everything",
            rules=[
                PolicyRule(
                    id="allow-all",
                    effect=RuleEffect.ALLOW,
                    match=RuleMatch(tools=["*"]),
                )
            ],
        )
    )
    t3_decision = permissive.evaluate("wire_transfer", RiskTier.T3, {}, ExecutionContext())
    assert t3_decision.allowed is False
    assert t3_decision.rule_id == "invariant-t3-forbidden"

    cat_decision = permissive.evaluate(
        "submit_form",
        RiskTier.T1,
        {"category": "payment"},
        ExecutionContext(),
    )
    assert cat_decision.allowed is False


def test_policy_dimensions_scope_recipient_data_time_amount() -> None:
    engine = PolicyEngine(
        PolicySet(
            version="1.0",
            name="dimension-test",
            rules=[
                PolicyRule(
                    id="scoped-draft",
                    effect=RuleEffect.ALLOW,
                    match=RuleMatch(
                        tools=["draft_*"],
                        action_tiers=[RiskTier.T1],
                        resource_scopes=["/work/inbox/*"],
                        recipients_or_domains=["*@company.com"],
                        data_classes=[DataClass.INTERNAL],
                        max_amount=50.0,
                        time_window=TimeWindow(
                            start_hour_utc=9,
                            end_hour_utc=17,
                            days_of_week=[0, 1, 2, 3, 4],
                        ),
                    ),
                )
            ],
        )
    )
    monday_10am = datetime(2026, 11, 23, 10, 0, tzinfo=UTC)  # Monday
    ctx = ExecutionContext(data_class=DataClass.INTERNAL, trust_level="user")

    ok = engine.explain(
        "draft_email",
        RiskTier.T1,
        {"resource": "/work/inbox/123", "recipient": "alice@company.com", "amount": 25.0},
        ctx,
        now=monday_10am,
    )
    assert ok.decision.allowed is True

    bad_domain = engine.explain(
        "draft_email",
        RiskTier.T1,
        {"resource": "/work/inbox/123", "recipient": "evil@outside.org", "amount": 25.0},
        ctx,
        now=monday_10am,
    )
    assert bad_domain.decision.allowed is False
    assert "recipient/domain" in bad_domain.traces[0].reasons[0]

    bad_time = engine.explain(
        "draft_email",
        RiskTier.T1,
        {"resource": "/work/inbox/123", "recipient": "alice@company.com", "amount": 25.0},
        ctx,
        now=datetime(2026, 11, 23, 22, 0, tzinfo=UTC),
    )
    assert bad_time.decision.allowed is False


def test_gateway_with_policy_engine(
    audit_logger: AuditLogger,
    budget_manager: BudgetManager,
    kill_switch: KillSwitchManager,
) -> None:
    engine = PolicyEngine.from_yaml(Path("policies/relaxed.yaml"))
    gw = ToolGateway(
        audit_logger=audit_logger,
        budget_manager=budget_manager,
        kill_switch=kill_switch,
        policy_checker=engine,
    )
    gw.register(
        ToolSpec(
            name="send_email",
            description="Send email",
            risk_tier=RiskTier.T2,
            handler=lambda args, ctx: "sent",
        )
    )
    with pytest.raises(ToolDeniedError):
        gw.execute("send_email", {}, ExecutionContext(task_id="t1", trust_level="user"))

    res = gw.execute(
        "send_email",
        {},
        ExecutionContext(task_id="t1", trust_level="user", metadata={"approved": True}),
    )
    assert res.output == "sent"
