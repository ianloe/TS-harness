"""FinOps cost attribution, prompt caching, anomaly detection, and provider rate limits."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ts_harness.config import Currency
from ts_harness.core.models import TaskStatus
from ts_harness.db.models import BudgetLedgerRecord, TaskRecord


class CostAttributionReport(BaseModel):
    """Cost breakdown by workflow, model, tool, and useful outcome."""

    currency: Currency
    total_spend: float
    completed_tasks: int
    cost_per_useful_outcome: float
    by_workflow: dict[str, float] = Field(default_factory=dict)
    by_model: dict[str, float] = Field(default_factory=dict)
    by_tool: dict[str, float] = Field(default_factory=dict)


def build_cost_attribution_report(
    session_factory: sessionmaker[Session],
    currency: Currency,
) -> CostAttributionReport:
    """Aggregate spend by workflow, model, tool, and completed task outcomes."""
    by_workflow: dict[str, float] = defaultdict(float)
    by_model: dict[str, float] = defaultdict(float)
    by_tool: dict[str, float] = defaultdict(float)
    total_spend = 0.0

    with session_factory() as session:
        rows = session.scalars(
            select(BudgetLedgerRecord).where(BudgetLedgerRecord.currency == currency)
        ).all()
        for row in rows:
            total_spend += row.amount
            if row.workflow_name:
                by_workflow[row.workflow_name] += row.amount
            if row.model_name:
                by_model[row.model_name] += row.amount
            if row.tool_name:
                by_tool[row.tool_name] += row.amount

        completed = session.scalars(
            select(TaskRecord).where(TaskRecord.status == TaskStatus.COMPLETED.value)
        ).all()
        completed_count = len(completed)

    cost_per_outcome = (total_spend / completed_count) if completed_count > 0 else 0.0
    return CostAttributionReport(
        currency=currency,
        total_spend=round(total_spend, 6),
        completed_tasks=completed_count,
        cost_per_useful_outcome=round(cost_per_outcome, 6),
        by_workflow={k: round(v, 6) for k, v in sorted(by_workflow.items())},
        by_model={k: round(v, 6) for k, v in sorted(by_model.items())},
        by_tool={k: round(v, 6) for k, v in sorted(by_tool.items())},
    )


class PromptCache:
    """TTL-based prompt and tool result cache to reduce duplicate model spend."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._store: dict[str, tuple[datetime, Any]] = {}
        self.hits = 0
        self.misses = 0

    @staticmethod
    def make_key(namespace: str, payload: str) -> str:
        digest = hashlib.sha256(f"{namespace}:{payload}".encode()).hexdigest()
        return digest

    def get(self, key: str, *, now: datetime | None = None) -> Any | None:
        current = now or datetime.now(UTC)
        entry = self._store.get(key)
        if entry is None:
            self.misses += 1
            return None
        expires_at, value = entry
        if current >= expires_at:
            del self._store[key]
            self.misses += 1
            return None
        self.hits += 1
        return value

    def set(self, key: str, value: Any, *, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        self._store[key] = (current + self._ttl, value)


class SpendAnomalyDetector:
    """Detects spend spikes relative to recent baseline."""

    def __init__(self, spike_multiplier: float = 3.0, min_baseline_samples: int = 3) -> None:
        self._multiplier = spike_multiplier
        self._min_samples = min_baseline_samples
        self._history: list[float] = []

    def observe(self, amount: float) -> tuple[bool, str | None]:
        """Record a spend amount and return (is_anomaly, reason)."""
        if len(self._history) >= self._min_samples:
            avg = sum(self._history) / len(self._history)
            if avg > 0 and amount > avg * self._multiplier:
                self._history.append(amount)
                return (
                    True,
                    f"Spend spike detected: {amount:.4f} exceeds "
                    f"{self._multiplier}x baseline ({avg:.4f}).",
                )
        self._history.append(amount)
        return False, None


class ProviderRateLimiter:
    """Per-provider RPM and concurrency cap enforcer."""

    def __init__(self, max_rpm: int = 60, max_concurrent: int = 5) -> None:
        self._max_rpm = max_rpm
        self._max_concurrent = max_concurrent
        self._requests: dict[str, list[datetime]] = defaultdict(list)
        self._active: dict[str, int] = defaultdict(int)

    def acquire(self, provider: str, *, now: datetime | None = None) -> tuple[bool, str | None]:
        current = now or datetime.now(UTC)
        if self._active[provider] >= self._max_concurrent:
            return False, f"Concurrency cap ({self._max_concurrent}) reached for '{provider}'."
        cutoff = current - timedelta(minutes=1)
        recent = [t for t in self._requests[provider] if t >= cutoff]
        if len(recent) >= self._max_rpm:
            self._requests[provider] = recent
            return False, f"Rate limit ({self._max_rpm} RPM) exceeded for '{provider}'."
        recent.append(current)
        self._requests[provider] = recent
        self._active[provider] += 1
        return True, None

    def release(self, provider: str) -> None:
        if self._active[provider] > 0:
            self._active[provider] -= 1
