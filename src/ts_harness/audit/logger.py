"""Append-only, hash-chained audit log with verification and replay."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ts_harness.config import SUPPORTED_CURRENCIES, Currency
from ts_harness.db.models import AuditLogRecord
from ts_harness.logging import redact_value

GENESIS_HASH = "GENESIS"


class AuditEvent(BaseModel):
    """Domain representation of an audit log entry."""

    id: int
    timestamp: str
    task_id: str | None
    actor: str
    event_type: str
    payload: dict[str, Any]
    cost_amount: float
    cost_currency: Currency
    prev_hash: str
    entry_hash: str


class ChainVerificationResult(BaseModel):
    """Result of verifying the audit log hash chain."""

    valid: bool
    checked_count: int
    broken_at_id: int | None = None
    reason: str | None = None


def _compute_entry_hash(
    *,
    timestamp: str,
    task_id: str | None,
    actor: str,
    event_type: str,
    payload_json: str,
    cost_amount: float,
    cost_currency: str,
    prev_hash: str,
) -> str:
    canonical = json.dumps(
        {
            "timestamp": timestamp,
            "task_id": task_id,
            "actor": actor,
            "event_type": event_type,
            "payload_json": payload_json,
            "cost_amount": round(cost_amount, 6),
            "cost_currency": cost_currency,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuditLogger:
    """Append-only hash-chained audit log manager."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def append(
        self,
        *,
        event_type: str,
        actor: str,
        payload: dict[str, Any] | None = None,
        task_id: str | None = None,
        cost_amount: float = 0.0,
        cost_currency: Currency = "SGD",
    ) -> AuditEvent:
        """Append a new hash-chained entry to the audit log."""
        if cost_currency not in SUPPORTED_CURRENCIES:
            raise ValueError(f"Unsupported currency '{cost_currency}'. Allowed: SGD, USD.")

        redacted_payload = redact_value(payload or {})
        payload_json = json.dumps(redacted_payload, sort_keys=True, separators=(",", ":"))
        timestamp = datetime.now(UTC).isoformat()
        rounded_cost = round(cost_amount, 6)

        with self._session_factory() as session:
            last_record = session.scalar(
                select(AuditLogRecord).order_by(AuditLogRecord.id.desc()).limit(1)
            )
            prev_hash = last_record.entry_hash if last_record is not None else GENESIS_HASH
            entry_hash = _compute_entry_hash(
                timestamp=timestamp,
                task_id=task_id,
                actor=actor,
                event_type=event_type,
                payload_json=payload_json,
                cost_amount=rounded_cost,
                cost_currency=cost_currency,
                prev_hash=prev_hash,
            )
            record = AuditLogRecord(
                timestamp=timestamp,
                task_id=task_id,
                actor=actor,
                event_type=event_type,
                payload_json=payload_json,
                cost_amount=rounded_cost,
                cost_currency=cost_currency,
                prev_hash=prev_hash,
                entry_hash=entry_hash,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._to_event(record)

    def verify_chain(self) -> ChainVerificationResult:
        """Verify hash linkage and entry integrity across the entire audit log."""
        with self._session_factory() as session:
            records = session.scalars(
                select(AuditLogRecord).order_by(AuditLogRecord.id.asc())
            ).all()
            expected_prev = GENESIS_HASH
            checked = 0
            for record in records:
                checked += 1
                if record.prev_hash != expected_prev:
                    return ChainVerificationResult(
                        valid=False,
                        checked_count=checked,
                        broken_at_id=record.id,
                        reason=f"prev_hash mismatch at entry {record.id}",
                    )
                recomputed = _compute_entry_hash(
                    timestamp=record.timestamp,
                    task_id=record.task_id,
                    actor=record.actor,
                    event_type=record.event_type,
                    payload_json=record.payload_json,
                    cost_amount=record.cost_amount,
                    cost_currency=record.cost_currency,
                    prev_hash=record.prev_hash,
                )
                if record.entry_hash != recomputed:
                    return ChainVerificationResult(
                        valid=False,
                        checked_count=checked,
                        broken_at_id=record.id,
                        reason=f"entry_hash mismatch at entry {record.id}",
                    )
                expected_prev = record.entry_hash
            return ChainVerificationResult(valid=True, checked_count=checked)

    def list_events(
        self,
        *,
        task_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """List recent audit events."""
        with self._session_factory() as session:
            stmt = select(AuditLogRecord).order_by(AuditLogRecord.id.desc()).limit(limit)
            if task_id is not None:
                stmt = stmt.where(AuditLogRecord.task_id == task_id)
            if event_type is not None:
                stmt = stmt.where(AuditLogRecord.event_type == event_type)
            return [self._to_event(r) for r in session.scalars(stmt).all()]

    def replay_task(self, task_id: str) -> list[AuditEvent]:
        """Return all audit events for a task in chronological order for replay."""
        with self._session_factory() as session:
            stmt = (
                select(AuditLogRecord)
                .where(AuditLogRecord.task_id == task_id)
                .order_by(AuditLogRecord.id.asc())
            )
            return [self._to_event(r) for r in session.scalars(stmt).all()]

    @staticmethod
    def _to_event(record: AuditLogRecord) -> AuditEvent:
        return AuditEvent(
            id=record.id,
            timestamp=record.timestamp,
            task_id=record.task_id,
            actor=record.actor,
            event_type=record.event_type,
            payload=json.loads(record.payload_json),
            cost_amount=record.cost_amount,
            cost_currency=cast(Currency, record.cost_currency),
            prev_hash=record.prev_hash,
            entry_hash=record.entry_hash,
        )
