"""End-to-end tests for all four draft-only workflows against mock connectors."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ts_harness.agents.models import StubModelClient
from ts_harness.agents.roles import PlannerAgent, VerifierAgent
from ts_harness.approvals.queue import ApprovalQueue
from ts_harness.audit.logger import AuditLogger
from ts_harness.config import ModelRoleConfig
from ts_harness.connectors.mocks import (
    MockCalendarConnector,
    MockDriveConnector,
    MockMailConnector,
    MockWebResearchConnector,
)
from ts_harness.core.models import TaskCreate, TaskStatus
from ts_harness.core.store import StateStore
from ts_harness.finops.budget import BudgetManager
from ts_harness.gateway.gateway import ToolGateway
from ts_harness.graph.engine import GraphRunner
from ts_harness.killswitch.manager import KillSwitchManager
from ts_harness.policy.engine import PolicyEngine
from ts_harness.workflows.implementations import (
    build_inbox_triage_handlers,
    build_meeting_prep_handlers,
    build_research_digest_handlers,
    build_weekly_review_handlers,
)
from ts_harness.workflows.registry import load_workflow_definition


def _setup_deps(
    session_factory: Any,
    store: StateStore,
    audit_logger: AuditLogger,
    budget_manager: BudgetManager,
    kill_switch: KillSwitchManager,
) -> tuple[ToolGateway, GraphRunner, PlannerAgent, VerifierAgent, ApprovalQueue]:
    policy = PolicyEngine.from_yaml(Path("policies/strict.yaml"))
    gateway = ToolGateway(
        audit_logger=audit_logger,
        budget_manager=budget_manager,
        kill_switch=kill_switch,
        policy_checker=policy,
    )
    queue = ApprovalQueue(session_factory, audit_logger)
    runner = GraphRunner(
        store=store,
        audit_logger=audit_logger,
        budget_manager=budget_manager,
        kill_switch=kill_switch,
        approval_queue=queue,
    )
    client = StubModelClient()
    planner = PlannerAgent(
        model_client=client,
        role_config=ModelRoleConfig(provider="anthropic", model_name="claude-sonnet-4-20250514"),
        budget_manager=budget_manager,
    )
    verifier = VerifierAgent(
        model_client=client,
        role_config=ModelRoleConfig(provider="anthropic", model_name="claude-haiku-4-5-20251001"),
        budget_manager=budget_manager,
    )
    return gateway, runner, planner, verifier, queue


def test_inbox_triage_workflow_draft_only_and_quarantines_injection(
    session_factory: Any,
    store: StateStore,
    audit_logger: AuditLogger,
    budget_manager: BudgetManager,
    kill_switch: KillSwitchManager,
) -> None:
    gateway, runner, planner, verifier, _ = _setup_deps(
        session_factory, store, audit_logger, budget_manager, kill_switch
    )
    wf = load_workflow_definition(Path("workflows/inbox_triage.yaml"))
    mail = MockMailConnector()
    handlers = build_inbox_triage_handlers(
        mail=mail, gateway=gateway, planner=planner, verifier=verifier
    )
    task, _ = store.create_task(
        TaskCreate(title="Morning inbox", workflow_name=wf.name, risk_tier=wf.risk_tier)
    )
    res = runner.run(wf.graph, task, handlers)
    assert res.status == TaskStatus.COMPLETED.value
    # Only the legitimate email gets a draft; the injected email is quarantined & labelled only
    assert len(mail.drafts) == 1
    assert mail.drafts[0].in_reply_to == "msg-1"
    assert any(lbl["proposed_label"] == "quarantine-suspicious" for lbl in mail.proposed_labels)
    assert res.state["verification"]["passed"] is True


def test_meeting_prep_workflow(
    session_factory: Any,
    store: StateStore,
    audit_logger: AuditLogger,
    budget_manager: BudgetManager,
    kill_switch: KillSwitchManager,
) -> None:
    gateway, runner, planner, verifier, _ = _setup_deps(
        session_factory, store, audit_logger, budget_manager, kill_switch
    )
    wf = load_workflow_definition(Path("workflows/meeting_prep.yaml"))
    handlers = build_meeting_prep_handlers(
        calendar=MockCalendarConnector(),
        drive=MockDriveConnector(),
        gateway=gateway,
        planner=planner,
        verifier=verifier,
    )
    task, _ = store.create_task(TaskCreate(title="Prep Q4 review", workflow_name=wf.name))
    res = runner.run(wf.graph, task, handlers)
    assert res.status == TaskStatus.COMPLETED.value
    assert len(res.state["briefs"]) == 1
    assert res.state["verification"]["passed"] is True


def test_research_digest_workflow(
    session_factory: Any,
    store: StateStore,
    audit_logger: AuditLogger,
    budget_manager: BudgetManager,
    kill_switch: KillSwitchManager,
) -> None:
    gateway, runner, planner, verifier, _ = _setup_deps(
        session_factory, store, audit_logger, budget_manager, kill_switch
    )
    wf = load_workflow_definition(Path("workflows/research_digest.yaml"))
    handlers = build_research_digest_handlers(
        web=MockWebResearchConnector(),
        gateway=gateway,
        planner=planner,
        verifier=verifier,
    )
    task, _ = store.create_task(TaskCreate(title="LLM Security", workflow_name=wf.name))
    res = runner.run(wf.graph, task, handlers)
    assert res.status == TaskStatus.COMPLETED.value
    assert len(res.state["citations"]) == 2
    assert res.state["verification"]["passed"] is True


def test_weekly_review_workflow(
    session_factory: Any,
    store: StateStore,
    audit_logger: AuditLogger,
    budget_manager: BudgetManager,
    kill_switch: KillSwitchManager,
) -> None:
    gateway, runner, planner, verifier, queue = _setup_deps(
        session_factory, store, audit_logger, budget_manager, kill_switch
    )
    wf = load_workflow_definition(Path("workflows/weekly_review.yaml"))
    queue.create_request(
        tool_name="send_email",
        summary="Pending email",
        reason="T2",
    )
    handlers = build_weekly_review_handlers(
        store=store,
        budget_manager=budget_manager,
        approval_queue=queue,
        planner=planner,
        verifier=verifier,
    )
    task, _ = store.create_task(TaskCreate(title="Weekly review", workflow_name=wf.name))
    res = runner.run(wf.graph, task, handlers)
    assert res.status == TaskStatus.COMPLETED.value
    assert res.state["pending_approvals"] == 1
    assert "Weekly Review:" in res.state["report_text"]
    assert res.state["verification"]["passed"] is True
