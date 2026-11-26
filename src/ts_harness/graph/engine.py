"""Graph execution engine with bounded loops, checkpoints, and crash resume."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from ts_harness.approvals.queue import ApprovalQueue
from ts_harness.audit.logger import AuditLogger
from ts_harness.config import Currency
from ts_harness.core.models import Task, TaskStatus
from ts_harness.core.store import StateStore
from ts_harness.finops.budget import BudgetExceededError, BudgetManager
from ts_harness.graph.schema import LoopPolicy, NodeType, WorkflowGraph
from ts_harness.killswitch.manager import KillSwitchActiveError, KillSwitchManager


class LoopLimitExceededError(RuntimeError):
    """Raised when a loop exceeds iteration, timeout, or cost bounds."""


class NoProgressError(RuntimeError):
    """Raised when the same tool call or error repeats without progress."""


class NodeOutcome(BaseModel):
    """Result returned by a node handler."""

    state_updates: dict[str, Any] = Field(default_factory=dict)
    branch: str | None = None
    action_signature: str | None = None
    error_signature: str | None = None
    cost_incurred: float = 0.0
    continue_loop: bool = False


NodeHandler = Callable[[dict[str, Any], Task], NodeOutcome]


class GraphRunResult(BaseModel):
    """Final or paused outcome of a graph execution."""

    task_id: str
    status: str
    final_node: str
    steps_executed: int
    state: dict[str, Any]
    approval_id: str | None = None


class NoProgressDetector:
    """Detects repeated identical tool calls or errors inside a loop."""

    def __init__(self, threshold: int = 3) -> None:
        self._threshold = threshold
        self._action_counts: dict[str, int] = {}
        self._error_counts: dict[str, int] = {}

    def record(self, *, action_sig: str | None = None, error_sig: str | None = None) -> None:
        """Record an iteration's action or error signature and raise on stall."""
        if error_sig:
            self._error_counts[error_sig] = self._error_counts.get(error_sig, 0) + 1
            if self._error_counts[error_sig] >= self._threshold:
                raise NoProgressError(
                    f"No progress: error '{error_sig}' repeated {self._threshold} times."
                )
        if action_sig:
            self._action_counts[action_sig] = self._action_counts.get(action_sig, 0) + 1
            if self._action_counts[action_sig] >= self._threshold:
                raise NoProgressError(
                    f"No progress: action '{action_sig}' repeated {self._threshold} times."
                )


class GraphRunner:
    """Executes WorkflowGraphs with kill-switch, budget, loop, and checkpoint guards."""

    def __init__(
        self,
        *,
        store: StateStore,
        audit_logger: AuditLogger,
        budget_manager: BudgetManager,
        kill_switch: KillSwitchManager,
        approval_queue: ApprovalQueue,
        currency: Currency = "SGD",
        clock_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._audit = audit_logger
        self._budget = budget_manager
        self._kill_switch = kill_switch
        self._approvals = approval_queue
        self._currency: Currency = currency
        self._clock = clock_fn

    def run(
        self,
        graph: WorkflowGraph,
        task: Task,
        handlers: dict[str, NodeHandler],
        *,
        initial_state: dict[str, Any] | None = None,
        resume: bool = False,
    ) -> GraphRunResult:
        """Execute a workflow graph, optionally resuming from the latest checkpoint."""
        state: dict[str, Any] = dict(initial_state or {})
        current_node_id: str | None = graph.entry_node
        step_index = 0

        if resume:
            cp = self._store.get_latest_checkpoint(task.id)
            if cp is not None:
                state = dict(cp.state)
                saved_next = state.pop("_next_node", None)
                current_node_id = str(saved_next) if saved_next else cp.node_id
                step_index = cp.step_index + 1
                self._audit.append(
                    event_type="graph.resumed",
                    actor="graph_runner",
                    task_id=task.id,
                    payload={"resume_node": current_node_id, "step_index": step_index},
                )

        self._store.update_task_status(task.id, TaskStatus.RUNNING)
        steps_executed = 0

        try:
            while current_node_id is not None:
                blocked, block_reason = self._kill_switch.is_blocked(workflow_name=graph.name)
                if blocked:
                    self._store.update_task_status(
                        task.id, TaskStatus.PAUSED, error_message=block_reason
                    )
                    raise KillSwitchActiveError(block_reason or "Kill switch active.")

                budget_status = self._budget.check_budget(
                    task_id=task.id,
                    workflow_name=graph.name,
                )
                if not budget_status.allowed:
                    raise BudgetExceededError(budget_status.reason or "Budget limit exceeded.")

                node = graph.nodes[current_node_id]

                if node.node_type == NodeType.END:
                    self._store.save_checkpoint(task.id, node.id, step_index, state)
                    self._store.update_task_status(task.id, TaskStatus.COMPLETED, result=state)
                    self._audit.append(
                        event_type="graph.completed",
                        actor="graph_runner",
                        task_id=task.id,
                        payload={"workflow": graph.name, "steps": steps_executed},
                    )
                    return GraphRunResult(
                        task_id=task.id,
                        status=TaskStatus.COMPLETED.value,
                        final_node=node.id,
                        steps_executed=steps_executed,
                        state=state,
                    )

                if node.node_type == NodeType.APPROVE:
                    approval = self._approvals.create_request(
                        task_id=task.id,
                        tool_name=node.handler_name or node.id,
                        summary=node.approval_summary or f"Approval required at node '{node.id}'",
                        reason=f"Workflow '{graph.name}' reached approval gate '{node.id}'.",
                        cost_currency=self._currency,
                        payload={"state": state},
                    )
                    next_after_approve = graph.next_target(node.id)
                    cp_state = {**state, "_next_node": next_after_approve}
                    self._store.save_checkpoint(task.id, node.id, step_index, cp_state)
                    self._store.update_task_status(task.id, TaskStatus.WAITING_APPROVAL)
                    return GraphRunResult(
                        task_id=task.id,
                        status=TaskStatus.WAITING_APPROVAL.value,
                        final_node=node.id,
                        steps_executed=steps_executed,
                        state=state,
                        approval_id=approval.id,
                    )

                handler_key = node.handler_name or node.id
                if handler_key not in handlers:
                    raise KeyError(f"Missing handler '{handler_key}' for node '{node.id}'.")
                handler = handlers[handler_key]

                if node.node_type == NodeType.LOOP:
                    outcome = self._run_bounded_loop(
                        node.id,
                        node.loop_policy or LoopPolicy(),
                        handler,
                        state,
                        task,
                        graph.name,
                    )
                else:
                    outcome = handler(state, task)
                    state.update(outcome.state_updates)
                    if outcome.cost_incurred > 0:
                        self._store.add_task_cost(task.id, outcome.cost_incurred)

                steps_executed += 1
                next_node_id = graph.next_target(node.id, branch_key=outcome.branch)
                cp_state = {**state, "_next_node": next_node_id}
                self._store.save_checkpoint(task.id, node.id, step_index, cp_state)
                self._audit.append(
                    event_type="graph.node_executed",
                    actor="graph_runner",
                    task_id=task.id,
                    payload={
                        "workflow": graph.name,
                        "node_id": node.id,
                        "node_type": node.node_type.value,
                        "next_node": next_node_id,
                    },
                    cost_amount=outcome.cost_incurred,
                    cost_currency=self._currency,
                )
                step_index += 1
                current_node_id = next_node_id

            self._store.update_task_status(task.id, TaskStatus.COMPLETED, result=state)
            return GraphRunResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED.value,
                final_node="",
                steps_executed=steps_executed,
                state=state,
            )

        except (LoopLimitExceededError, NoProgressError, BudgetExceededError) as exc:
            self._store.send_to_dlq(
                task.id,
                reason=str(exc),
                payload={"node_id": current_node_id, "state": state},
                attempts=step_index + 1,
            )
            self._audit.append(
                event_type="graph.escalated",
                actor="graph_runner",
                task_id=task.id,
                payload={"node_id": current_node_id, "reason": str(exc)},
            )
            raise

    def _run_bounded_loop(
        self,
        node_id: str,
        policy: LoopPolicy,
        handler: NodeHandler,
        state: dict[str, Any],
        task: Task,
        workflow_name: str,
    ) -> NodeOutcome:
        detector = NoProgressDetector(threshold=policy.no_progress_threshold)
        start = self._clock()
        loop_cost = 0.0
        last_outcome = NodeOutcome()

        for iteration in range(1, policy.max_iterations + 1):
            blocked, block_reason = self._kill_switch.is_blocked(workflow_name=workflow_name)
            if blocked:
                raise KillSwitchActiveError(block_reason or "Kill switch active.")

            elapsed = self._clock() - start
            if elapsed > policy.timeout_seconds:
                raise LoopLimitExceededError(
                    f"Loop '{node_id}' exceeded timeout of {policy.timeout_seconds}s."
                )

            outcome = handler(state, task)
            state.update(outcome.state_updates)
            loop_cost += outcome.cost_incurred
            if outcome.cost_incurred > 0:
                self._store.add_task_cost(task.id, outcome.cost_incurred)

            if loop_cost > policy.max_cost:
                raise LoopLimitExceededError(
                    f"Loop '{node_id}' exceeded max_cost {policy.max_cost} {self._currency}."
                )

            detector.record(
                action_sig=outcome.action_signature,
                error_sig=outcome.error_signature,
            )
            last_outcome = outcome

            if not outcome.continue_loop:
                return last_outcome

            if iteration == policy.max_iterations:
                raise LoopLimitExceededError(
                    f"Loop '{node_id}' reached max_iterations ({policy.max_iterations})."
                )

        return last_outcome
