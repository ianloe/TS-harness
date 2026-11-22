"""Tests for FinOps budget enforcement."""

from __future__ import annotations

import pytest

from ts_harness.finops.budget import BudgetManager


def test_budget_soft_warning_and_hard_stop(budget_manager: BudgetManager) -> None:
    budget_manager.record_spend(
        amount=1.6,
        currency="SGD",
        task_id="t1",
        workflow_name="inbox_triage",
        model_name="claude-sonnet",
    )
    soft = budget_manager.check_budget(task_id="t1", workflow_name="inbox_triage")
    assert soft.allowed is True
    assert soft.soft_warning is True
    assert soft.hard_stop is False

    hard = budget_manager.check_budget(
        task_id="t1",
        workflow_name="inbox_triage",
        estimated_cost=0.5,
    )
    assert hard.allowed is False
    assert hard.hard_stop is True
    assert hard.reason is not None


def test_budget_preflight_approval_threshold(budget_manager: BudgetManager) -> None:
    status = budget_manager.check_budget(estimated_cost=1.5)
    assert status.preflight_approval_required is True


def test_budget_rejects_unsupported_or_mismatched_currency(
    budget_manager: BudgetManager,
) -> None:
    with pytest.raises(ValueError):
        budget_manager.record_spend(amount=1.0, currency="EUR")  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        budget_manager.record_spend(amount=1.0, currency="USD")
