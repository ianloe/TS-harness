"""Tracing, run-graph reconstruction, and dashboard metrics."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ts_harness.audit.logger import AuditLogger
from ts_harness.config import BudgetConfig, Currency
from ts_harness.core.models import TaskStatus
from ts_harness.db.models import ApprovalRecord, AuditLogRecord, TaskRecord
from ts_harness.finops.budget import BudgetManager


class RunTraceNode(BaseModel):
    """A single event/node in a reconstructed run trace."""

    seq: int
    timestamp: str
    event_type: str
    actor: str
    cost_amount: float
    details: dict[str, object] = Field(default_factory=dict)


class RunTraceGraph(BaseModel):
    """Trace view of a single task run."""

    task_id: str
    event_count: int
    total_cost: float
    nodes: list[RunTraceNode] = Field(default_factory=list)


class DashboardMetrics(BaseModel):
    """Aggregated operational metrics for the observability dashboard."""

    active_runs: int
    approvals_waiting: int
    total_tasks: int
    error_rate: float
    policy_blocks: int
    daily_spend: float
    daily_limit: float
    monthly_spend: float
    monthly_limit: float
    currency: Currency


def configure_otel(
    *,
    service_name: str = "ts-harness",
    enabled: bool = False,
    aegis_export_url: str | None = None,
) -> trace.Tracer:
    """Configure an OpenTelemetry tracer (optional Aegis export endpoint)."""
    if enabled:
        resource = Resource.create(
            {
                "service.name": service_name,
                "aegis.export_url": aegis_export_url or "disabled",
            }
        )
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)


def build_run_trace(task_id: str, audit_logger: AuditLogger) -> RunTraceGraph:
    """Reconstruct a chronological trace graph for a task from the audit log."""
    events = audit_logger.replay_task(task_id)
    nodes = [
        RunTraceNode(
            seq=idx,
            timestamp=ev.timestamp,
            event_type=ev.event_type,
            actor=ev.actor,
            cost_amount=ev.cost_amount,
            details=ev.payload,
        )
        for idx, ev in enumerate(events)
    ]
    total_cost = round(sum(ev.cost_amount for ev in events), 6)
    return RunTraceGraph(
        task_id=task_id,
        event_count=len(nodes),
        total_cost=total_cost,
        nodes=nodes,
    )


def collect_dashboard_metrics(
    session_factory: sessionmaker[Session],
    budget_config: BudgetConfig,
) -> DashboardMetrics:
    """Collect active runs, waiting approvals, error rate, policy blocks, and spend."""
    budget_mgr = BudgetManager(session_factory, budget_config)
    spend = budget_mgr.get_spend_summary()

    with session_factory() as session:
        total_tasks = int(session.scalar(select(func.count(TaskRecord.id))) or 0)
        active_runs = int(
            session.scalar(
                select(func.count(TaskRecord.id)).where(
                    TaskRecord.status.in_([TaskStatus.RUNNING.value, TaskStatus.PENDING.value])
                )
            )
            or 0
        )
        failed_tasks = int(
            session.scalar(
                select(func.count(TaskRecord.id)).where(
                    TaskRecord.status.in_(
                        [TaskStatus.FAILED.value, TaskStatus.DEAD_LETTERED.value]
                    )
                )
            )
            or 0
        )
        approvals_waiting = int(
            session.scalar(
                select(func.count(ApprovalRecord.id)).where(ApprovalRecord.status == "pending")
            )
            or 0
        )
        policy_blocks = int(
            session.scalar(
                select(func.count(AuditLogRecord.id)).where(
                    AuditLogRecord.event_type == "tool.denied"
                )
            )
            or 0
        )

    error_rate = round((failed_tasks / total_tasks), 4) if total_tasks > 0 else 0.0
    return DashboardMetrics(
        active_runs=active_runs,
        approvals_waiting=approvals_waiting,
        total_tasks=total_tasks,
        error_rate=error_rate,
        policy_blocks=policy_blocks,
        daily_spend=spend.daily_spend,
        daily_limit=spend.daily_limit,
        monthly_spend=spend.monthly_spend,
        monthly_limit=spend.monthly_limit,
        currency=spend.currency,
    )
