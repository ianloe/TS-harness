"""Budget enforcement and spend attribution in SGD or USD."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ts_harness.config import SUPPORTED_CURRENCIES, BudgetConfig, Currency
from ts_harness.db.models import BudgetLedgerRecord


class BudgetExceededError(RuntimeError):
    """Raised when a budget hard stop is reached."""


class BudgetStatus(BaseModel):
    """Result of a pre-flight or runtime budget check."""

    allowed: bool
    hard_stop: bool = False
    soft_warning: bool = False
    preflight_approval_required: bool = False
    currency: Currency
    daily_spend: float = 0.0
    monthly_spend: float = 0.0
    workflow_spend: float = 0.0
    task_spend: float = 0.0
    warnings: list[str] = []
    reason: str | None = None


class SpendSummary(BaseModel):
    """Aggregated spend summary against configured limits."""

    currency: Currency
    daily_spend: float
    daily_limit: float
    monthly_spend: float
    monthly_limit: float


class BudgetManager:
    """Enforces task, workflow, daily, and monthly budgets in SGD or USD."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        config: BudgetConfig,
    ) -> None:
        self._session_factory = session_factory
        self._config = config

    def record_spend(
        self,
        *,
        amount: float,
        currency: Currency | None = None,
        task_id: str | None = None,
        workflow_name: str | None = None,
        model_name: str | None = None,
        tool_name: str | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> None:
        """Record a spend entry in the budget ledger."""
        effective_currency = currency or self._config.currency
        if effective_currency not in SUPPORTED_CURRENCIES:
            raise ValueError(
                f"Unsupported currency '{effective_currency}'. Allowed: SGD, USD."
            )
        if effective_currency != self._config.currency:
            raise ValueError(
                f"Currency mismatch: expected '{self._config.currency}', "
                f"got '{effective_currency}'."
            )
        if amount < 0:
            raise ValueError("Spend amount cannot be negative.")

        with self._session_factory() as session:
            record = BudgetLedgerRecord(
                id=str(uuid.uuid4()),
                task_id=task_id,
                workflow_name=workflow_name,
                model_name=model_name,
                tool_name=tool_name,
                amount=round(amount, 6),
                currency=effective_currency,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                created_at=datetime.now(UTC),
            )
            session.add(record)
            session.commit()

    def check_budget(
        self,
        *,
        task_id: str | None = None,
        workflow_name: str | None = None,
        estimated_cost: float = 0.0,
    ) -> BudgetStatus:
        """Evaluate whether an operation fits within configured soft and hard limits."""
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = day_start.replace(day=1)

        with self._session_factory() as session:
            daily_spend = self._sum_spend(session, since=day_start)
            monthly_spend = self._sum_spend(session, since=month_start)
            workflow_spend = (
                self._sum_spend(session, workflow_name=workflow_name)
                if workflow_name is not None
                else 0.0
            )
            task_spend = (
                self._sum_spend(session, task_id=task_id) if task_id is not None else 0.0
            )

        warnings: list[str] = []
        hard_reasons: list[str] = []

        checks: list[tuple[str, float, float]] = [
            ("daily", daily_spend + estimated_cost, self._config.daily_limit),
            ("monthly", monthly_spend + estimated_cost, self._config.monthly_limit),
        ]
        if workflow_name is not None:
            checks.append(
                ("workflow", workflow_spend + estimated_cost, self._config.workflow_limit)
            )
        if task_id is not None:
            checks.append(("task", task_spend + estimated_cost, self._config.task_limit))

        for scope, projected, limit in checks:
            if projected >= limit * self._config.hard_limit_pct:
                hard_reasons.append(
                    f"{scope} budget hard limit reached "
                    f"({projected:.4f} / {limit:.4f} {self._config.currency})"
                )
            elif projected >= limit * self._config.soft_limit_pct:
                warnings.append(
                    f"{scope} budget soft limit warning "
                    f"({projected:.4f} / {limit:.4f} {self._config.currency})"
                )

        preflight_approval = estimated_cost > self._config.preflight_approval_threshold
        hard_stop = len(hard_reasons) > 0

        return BudgetStatus(
            allowed=not hard_stop,
            hard_stop=hard_stop,
            soft_warning=len(warnings) > 0,
            preflight_approval_required=preflight_approval,
            currency=self._config.currency,
            daily_spend=round(daily_spend, 6),
            monthly_spend=round(monthly_spend, 6),
            workflow_spend=round(workflow_spend, 6),
            task_spend=round(task_spend, 6),
            warnings=warnings,
            reason="; ".join(hard_reasons) if hard_reasons else None,
        )

    def get_spend_summary(self) -> SpendSummary:
        """Return current daily and monthly spend totals."""
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = day_start.replace(day=1)

        with self._session_factory() as session:
            daily_spend = self._sum_spend(session, since=day_start)
            monthly_spend = self._sum_spend(session, since=month_start)

        return SpendSummary(
            currency=self._config.currency,
            daily_spend=round(daily_spend, 6),
            daily_limit=self._config.daily_limit,
            monthly_spend=round(monthly_spend, 6),
            monthly_limit=self._config.monthly_limit,
        )

    def _sum_spend(
        self,
        session: Session,
        *,
        since: datetime | None = None,
        task_id: str | None = None,
        workflow_name: str | None = None,
    ) -> float:
        stmt = select(func.coalesce(func.sum(BudgetLedgerRecord.amount), 0.0)).where(
            BudgetLedgerRecord.currency == self._config.currency
        )
        if since is not None:
            stmt = stmt.where(BudgetLedgerRecord.created_at >= since)
        if task_id is not None:
            stmt = stmt.where(BudgetLedgerRecord.task_id == task_id)
        if workflow_name is not None:
            stmt = stmt.where(BudgetLedgerRecord.workflow_name == workflow_name)
        result = session.scalar(stmt)
        return float(result or 0.0)
