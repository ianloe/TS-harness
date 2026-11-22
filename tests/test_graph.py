"""Tests for graph engine: bounded loops, no-progress, crash resume, and idempotency."""

from __future__ import annotations

from typing import Any

import pytest

from ts_harness.approvals.queue import ApprovalQueue
from ts_harness.audit.logger import AuditLogger
from ts_harness.core.models import Task, TaskCreate, TaskStatus
from ts_harness.core.store import StateStore
from ts_harness.finops.budget import BudgetManager
from ts_harness.graph.engine import (
    GraphRunner,
    LoopLimitExceededError,
    NodeOutcome,
    NoProgressError,
)
from ts_harness.graph.schema import GraphEdge, GraphNode, LoopPolicy, NodeType, WorkflowGraph
from ts_harness.killswitch.manager import KillSwitchActiveError, KillSwitchManager


def _make_runner(
    store: StateStore,
    audit_logger: AuditLogger,
    budget_manager: BudgetManager,
    kill_switch: KillSwitchManager,
    session_factory: Any,
    clock_fn: Any = None,
) -> GraphRunner:
    queue = ApprovalQueue(session_factory, audit_logger)
    kwargs: dict[str, Any] = {
        "store": store,
        "audit_logger": audit_logger,
        "budget_manager": budget_manager,
        "kill_switch": kill_switch,
        "approval_queue": queue,
    }
    if clock_fn is not None:
        kwargs["clock_fn"] = clock_fn
    return GraphRunner(**kwargs)


def test_graph_execution_branch_and_approval_gate(
    store: StateStore,
    audit_logger: AuditLogger,
    budget_manager: BudgetManager,
    kill_switch: KillSwitchManager,
    session_factory: Any,
) -> None:
    runner = _make_runner(store, audit_logger, budget_manager, kill_switch, session_factory)
    graph = WorkflowGraph(
        name="triage",
        entry_node="plan",
        nodes={
            "plan": GraphNode(id="plan", node_type=NodeType.PLAN),
            "act": GraphNode(id="act", node_type=NodeType.ACT),
            "approve": GraphNode(id="approve", node_type=NodeType.APPROVE),
            "end": GraphNode(id="end", node_type=NodeType.END),
        },
        edges=[
            GraphEdge(source="plan", target="act"),
            GraphEdge(source="act", target="approve"),
            GraphEdge(source="approve", target="end"),
        ],
    )
    task, _ = store.create_task(TaskCreate(title="Triage", workflow_name="triage"))
    handlers = {
        "plan": lambda st, t: NodeOutcome(state_updates={"planned": True}),
        "act": lambda st, t: NodeOutcome(state_updates={"draft": "Hello"}, cost_incurred=0.05),
    }

    paused = runner.run(graph, task, handlers)
    assert paused.status == TaskStatus.WAITING_APPROVAL.value
    assert paused.approval_id is not None

    resumed = runner.run(graph, task, handlers, resume=True)
    assert resumed.status == TaskStatus.COMPLETED.value
    assert resumed.final_node == "end"
    assert resumed.state["draft"] == "Hello"


def test_graph_crash_resume_and_idempotency(
    store: StateStore,
    audit_logger: AuditLogger,
    budget_manager: BudgetManager,
    kill_switch: KillSwitchManager,
    session_factory: Any,
) -> None:
    runner = _make_runner(store, audit_logger, budget_manager, kill_switch, session_factory)
    graph = WorkflowGraph(
        name="crash_test",
        entry_node="step1",
        nodes={
            "step1": GraphNode(id="step1", node_type=NodeType.PLAN),
            "step2": GraphNode(id="step2", node_type=NodeType.ACT),
            "end": GraphNode(id="end", node_type=NodeType.END),
        },
        edges=[
            GraphEdge(source="step1", target="step2"),
            GraphEdge(source="step2", target="end"),
        ],
    )
    task1, created1 = store.create_task(
        TaskCreate(title="Crash", workflow_name="crash_test", idempotency_key="idem-1")
    )
    task2, created2 = store.create_task(
        TaskCreate(title="Crash", workflow_name="crash_test", idempotency_key="idem-1")
    )
    assert created1 is True and created2 is False and task1.id == task2.id

    step1_calls = 0

    def step1_handler(st: dict[str, Any], t: Task) -> NodeOutcome:
        nonlocal step1_calls
        step1_calls += 1
        return NodeOutcome(state_updates={"step1_done": True})

    def crashing_step2(st: dict[str, Any], t: Task) -> NodeOutcome:
        raise RuntimeError("Simulated process crash")

    with pytest.raises(RuntimeError, match="Simulated process crash"):
        runner.run(graph, task1, {"step1": step1_handler, "step2": crashing_step2})
    assert step1_calls == 1

    def fixed_step2(st: dict[str, Any], t: Task) -> NodeOutcome:
        return NodeOutcome(state_updates={"step2_done": True})

    resumed = runner.run(
        graph,
        task1,
        {"step1": step1_handler, "step2": fixed_step2},
        resume=True,
    )
    assert resumed.status == TaskStatus.COMPLETED.value
    # step1 must NOT have re-executed on resume
    assert step1_calls == 1
    assert resumed.state["step1_done"] is True
    assert resumed.state["step2_done"] is True


def test_loop_limits_iterations_timeout_budget_and_no_progress(
    store: StateStore,
    audit_logger: AuditLogger,
    budget_manager: BudgetManager,
    kill_switch: KillSwitchManager,
    session_factory: Any,
) -> None:
    # 1. Max iterations
    runner = _make_runner(store, audit_logger, budget_manager, kill_switch, session_factory)
    loop_graph = WorkflowGraph(
        name="loop_wf",
        entry_node="loop",
        nodes={
            "loop": GraphNode(
                id="loop",
                node_type=NodeType.LOOP,
                loop_policy=LoopPolicy(max_iterations=2, max_cost=5.0, no_progress_threshold=5),
            ),
            "end": GraphNode(id="end", node_type=NodeType.END),
        },
        edges=[GraphEdge(source="loop", target="end")],
    )
    t_iter, _ = store.create_task(TaskCreate(title="Iter", workflow_name="loop_wf"))
    count = 0

    def endless(st: dict[str, Any], t: Task) -> NodeOutcome:
        nonlocal count
        count += 1
        return NodeOutcome(continue_loop=True, action_signature=f"step-{count}")

    with pytest.raises(LoopLimitExceededError, match="max_iterations"):
        runner.run(loop_graph, t_iter, {"loop": endless})
    assert store.get_task(t_iter.id).status == TaskStatus.DEAD_LETTERED  # type: ignore[union-attr]

    # 2. No-progress detector (same action 3 times)
    t_noprog, _ = store.create_task(TaskCreate(title="NoProg", workflow_name="loop_wf"))
    noprog_graph = WorkflowGraph(
        name="loop_wf",
        entry_node="loop",
        nodes={
            "loop": GraphNode(
                id="loop",
                node_type=NodeType.LOOP,
                loop_policy=LoopPolicy(max_iterations=10, no_progress_threshold=3),
            ),
            "end": GraphNode(id="end", node_type=NodeType.END),
        },
        edges=[GraphEdge(source="loop", target="end")],
    )
    with pytest.raises(NoProgressError, match="repeated 3 times"):
        runner.run(
            noprog_graph,
            t_noprog,
            {"loop": lambda st, t: NodeOutcome(continue_loop=True, action_signature="same_call")},
        )

    # 3. Timeout limit
    ticks = iter([0.0, 0.5, 5.0])
    timed_runner = _make_runner(
        store,
        audit_logger,
        budget_manager,
        kill_switch,
        session_factory,
        clock_fn=lambda: next(ticks),
    )
    timeout_graph = WorkflowGraph(
        name="loop_wf",
        entry_node="loop",
        nodes={
            "loop": GraphNode(
                id="loop",
                node_type=NodeType.LOOP,
                loop_policy=LoopPolicy(max_iterations=10, timeout_seconds=1.0),
            ),
            "end": GraphNode(id="end", node_type=NodeType.END),
        },
        edges=[GraphEdge(source="loop", target="end")],
    )
    t_to, _ = store.create_task(TaskCreate(title="Timeout", workflow_name="loop_wf"))
    with pytest.raises(LoopLimitExceededError, match="timeout"):
        timed_runner.run(
            timeout_graph,
            t_to,
            {"loop": lambda st, t: NodeOutcome(continue_loop=True, action_signature="tick")},
        )

    # 4. Kill switch halts before node execution
    t_ks, _ = store.create_task(TaskCreate(title="KS", workflow_name="loop_wf"))
    kill_switch.pause_workflow("loop_wf", reason="halt")
    with pytest.raises(KillSwitchActiveError):
        runner.run(loop_graph, t_ks, {"loop": endless})
