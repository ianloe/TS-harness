"""Persistent state store for tasks, checkpoints, and dead-letter queue."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ts_harness.config import Currency
from ts_harness.core.models import (
    Checkpoint,
    DataClass,
    DeadLetterItem,
    RiskTier,
    Task,
    TaskCreate,
    TaskStatus,
)
from ts_harness.db.models import DeadLetterRecord, StateCheckpointRecord, TaskRecord


class StateStore:
    """Repository for task lifecycle, checkpoints, and dead-letter items."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_task(self, payload: TaskCreate) -> tuple[Task, bool]:
        """Create a task or return an existing task if idempotency_key matches.

        Returns a tuple of ``(task, created)`` where ``created`` is False when
        an existing task was returned via idempotency key.
        """
        with self._session_factory() as session:
            if payload.idempotency_key is not None:
                existing = session.scalar(
                    select(TaskRecord).where(
                        TaskRecord.idempotency_key == payload.idempotency_key
                    )
                )
                if existing is not None:
                    return self._to_task(existing), False

            now = datetime.now(UTC)
            record = TaskRecord(
                id=str(uuid.uuid4()),
                title=payload.title,
                description=payload.description,
                workflow_name=payload.workflow_name,
                status=TaskStatus.PENDING.value,
                risk_tier=payload.risk_tier.value,
                data_class=payload.data_class.value,
                idempotency_key=payload.idempotency_key,
                metadata_json=json.dumps(payload.metadata, sort_keys=True),
                cost_amount=0.0,
                cost_currency=payload.cost_currency,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._to_task(record), True

    def get_task(self, task_id: str) -> Task | None:
        """Fetch a task by ID."""
        with self._session_factory() as session:
            record = session.get(TaskRecord, task_id)
            return self._to_task(record) if record is not None else None

    def list_tasks(
        self,
        *,
        status: TaskStatus | None = None,
        workflow_name: str | None = None,
        limit: int = 50,
    ) -> list[Task]:
        """List tasks ordered by creation time descending."""
        with self._session_factory() as session:
            stmt = select(TaskRecord).order_by(TaskRecord.created_at.desc()).limit(limit)
            if status is not None:
                stmt = stmt.where(TaskRecord.status == status.value)
            if workflow_name is not None:
                stmt = stmt.where(TaskRecord.workflow_name == workflow_name)
            records = session.scalars(stmt).all()
            return [self._to_task(r) for r in records]

    def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        result: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> Task:
        """Update task status and optional result or error."""
        with self._session_factory() as session:
            record = session.get(TaskRecord, task_id)
            if record is None:
                raise KeyError(f"Task '{task_id}' not found")
            now = datetime.now(UTC)
            record.status = status.value
            record.updated_at = now
            if result is not None:
                record.result_json = json.dumps(result, sort_keys=True)
            if error_message is not None:
                record.error_message = error_message
            if status in {
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
                TaskStatus.DEAD_LETTERED,
            }:
                record.completed_at = now
            session.commit()
            session.refresh(record)
            return self._to_task(record)

    def add_task_cost(self, task_id: str, amount: float) -> Task:
        """Increment accumulated cost for a task."""
        with self._session_factory() as session:
            record = session.get(TaskRecord, task_id)
            if record is None:
                raise KeyError(f"Task '{task_id}' not found")
            record.cost_amount = round(record.cost_amount + amount, 6)
            record.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(record)
            return self._to_task(record)

    def save_checkpoint(
        self,
        task_id: str,
        node_id: str,
        step_index: int,
        state: dict[str, Any],
    ) -> Checkpoint:
        """Persist a node execution checkpoint."""
        with self._session_factory() as session:
            record = StateCheckpointRecord(
                id=str(uuid.uuid4()),
                task_id=task_id,
                node_id=node_id,
                step_index=step_index,
                state_json=json.dumps(state, sort_keys=True),
                created_at=datetime.now(UTC),
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._to_checkpoint(record)

    def get_latest_checkpoint(self, task_id: str) -> Checkpoint | None:
        """Return the most recent checkpoint for a task."""
        with self._session_factory() as session:
            stmt = (
                select(StateCheckpointRecord)
                .where(StateCheckpointRecord.task_id == task_id)
                .order_by(
                    StateCheckpointRecord.step_index.desc(),
                    StateCheckpointRecord.created_at.desc(),
                )
                .limit(1)
            )
            record = session.scalar(stmt)
            return self._to_checkpoint(record) if record is not None else None

    def list_checkpoints(self, task_id: str) -> list[Checkpoint]:
        """List all checkpoints for a task in step order."""
        with self._session_factory() as session:
            stmt = (
                select(StateCheckpointRecord)
                .where(StateCheckpointRecord.task_id == task_id)
                .order_by(StateCheckpointRecord.step_index.asc())
            )
            return [self._to_checkpoint(r) for r in session.scalars(stmt).all()]

    def send_to_dlq(
        self,
        task_id: str,
        reason: str,
        payload: dict[str, Any] | None = None,
        attempts: int = 1,
    ) -> DeadLetterItem:
        """Move a failed task into the dead-letter queue and mark its status."""
        with self._session_factory() as session:
            task = session.get(TaskRecord, task_id)
            if task is None:
                raise KeyError(f"Task '{task_id}' not found")
            now = datetime.now(UTC)
            task.status = TaskStatus.DEAD_LETTERED.value
            task.error_message = reason
            task.updated_at = now
            task.completed_at = now

            dlq = DeadLetterRecord(
                id=str(uuid.uuid4()),
                task_id=task_id,
                reason=reason,
                payload_json=json.dumps(payload or {}, sort_keys=True),
                attempts=attempts,
                created_at=now,
            )
            session.add(dlq)
            session.commit()
            session.refresh(dlq)
            return DeadLetterItem(
                id=dlq.id,
                task_id=dlq.task_id,
                reason=dlq.reason,
                payload=json.loads(dlq.payload_json),
                attempts=dlq.attempts,
                created_at=dlq.created_at,
            )

    def list_dlq(self, limit: int = 50) -> list[DeadLetterItem]:
        """List dead-letter queue items."""
        with self._session_factory() as session:
            stmt = (
                select(DeadLetterRecord)
                .order_by(DeadLetterRecord.created_at.desc())
                .limit(limit)
            )
            records = session.scalars(stmt).all()
            return [
                DeadLetterItem(
                    id=r.id,
                    task_id=r.task_id,
                    reason=r.reason,
                    payload=json.loads(r.payload_json),
                    attempts=r.attempts,
                    created_at=r.created_at,
                )
                for r in records
            ]

    @staticmethod
    def _to_task(record: TaskRecord) -> Task:
        return Task(
            id=record.id,
            title=record.title,
            description=record.description,
            workflow_name=record.workflow_name,
            status=TaskStatus(record.status),
            risk_tier=RiskTier(record.risk_tier),
            data_class=DataClass(record.data_class),
            idempotency_key=record.idempotency_key,
            metadata=json.loads(record.metadata_json),
            result=json.loads(record.result_json) if record.result_json is not None else None,
            error_message=record.error_message,
            cost_amount=record.cost_amount,
            cost_currency=cast(Currency, record.cost_currency),
            created_at=record.created_at,
            updated_at=record.updated_at,
            completed_at=record.completed_at,
        )

    @staticmethod
    def _to_checkpoint(record: StateCheckpointRecord) -> Checkpoint:
        return Checkpoint(
            id=record.id,
            task_id=record.task_id,
            node_id=record.node_id,
            step_index=record.step_index,
            state=json.loads(record.state_json),
            created_at=record.created_at,
        )
