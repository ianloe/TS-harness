"""Tests for task state store, idempotency, checkpoints, DLQ, and retry."""

from __future__ import annotations

import pytest

from ts_harness.core.models import DataClass, RiskTier, TaskCreate, TaskStatus
from ts_harness.core.retry import RetryExhaustedError, retry_with_backoff
from ts_harness.core.store import StateStore


def test_create_task_and_idempotency(store: StateStore) -> None:
    payload = TaskCreate(
        title="Triage morning inbox",
        workflow_name="inbox_triage",
        risk_tier=RiskTier.T1,
        data_class=DataClass.PERSONAL,
        idempotency_key="inbox-2026-11-22",
    )
    task1, created1 = store.create_task(payload)
    task2, created2 = store.create_task(payload)

    assert created1 is True
    assert created2 is False
    assert task1.id == task2.id
    assert task1.status == TaskStatus.PENDING


def test_update_task_status_and_cost(store: StateStore) -> None:
    task, _ = store.create_task(TaskCreate(title="Prep", workflow_name="meeting_prep"))
    running = store.update_task_status(task.id, TaskStatus.RUNNING)
    assert running.status == TaskStatus.RUNNING

    with_cost = store.add_task_cost(task.id, 0.25)
    assert with_cost.cost_amount == 0.25

    done = store.update_task_status(task.id, TaskStatus.COMPLETED, result={"summary": "ok"})
    assert done.status == TaskStatus.COMPLETED
    assert done.result == {"summary": "ok"}
    assert done.completed_at is not None


def test_checkpoints_and_dlq(store: StateStore) -> None:
    task, _ = store.create_task(TaskCreate(title="Research", workflow_name="research_digest"))
    store.save_checkpoint(task.id, "plan", 0, {"step": "planned"})
    store.save_checkpoint(task.id, "act", 1, {"step": "acted"})

    latest = store.get_latest_checkpoint(task.id)
    assert latest is not None
    assert latest.node_id == "act"
    assert latest.step_index == 1

    all_cps = store.list_checkpoints(task.id)
    assert len(all_cps) == 2

    dlq_item = store.send_to_dlq(
        task.id,
        "Loop limit exceeded",
        payload={"node": "act"},
        attempts=3,
    )
    assert dlq_item.task_id == task.id
    assert dlq_item.attempts == 3

    updated = store.get_task(task.id)
    assert updated is not None
    assert updated.status == TaskStatus.DEAD_LETTERED
    assert len(store.list_dlq()) == 1


def test_retry_with_backoff_succeeds_and_exhausts() -> None:
    calls = 0

    def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ValueError("transient")
        return "ok"

    assert retry_with_backoff(flaky, max_attempts=3, sleep_fn=lambda _: None) == "ok"
    assert calls == 3

    def always_fail() -> str:
        raise RuntimeError("boom")

    with pytest.raises(RetryExhaustedError) as exc_info:
        retry_with_backoff(always_fail, max_attempts=2, sleep_fn=lambda _: None)
    assert exc_info.value.attempts == 2
