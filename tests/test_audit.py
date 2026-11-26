"""Tests for append-only hash-chained audit logging."""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from ts_harness.audit.logger import AuditLogger
from ts_harness.db.models import AuditLogRecord


def test_audit_chain_verification_and_replay(audit_logger: AuditLogger) -> None:
    audit_logger.append(
        event_type="task.created",
        actor="user",
        task_id="task-1",
        payload={"title": "Hello", "api_key": "sk-secret-value-12345"},
        cost_amount=0.1,
        cost_currency="SGD",
    )
    audit_logger.append(
        event_type="tool.executed",
        actor="executor",
        task_id="task-1",
        payload={"tool": "read_mail"},
    )

    verification = audit_logger.verify_chain()
    assert verification.valid is True
    assert verification.checked_count == 2

    events = audit_logger.replay_task("task-1")
    assert len(events) == 2
    assert events[0].payload["api_key"] == "[REDACTED]"
    assert events[1].prev_hash == events[0].entry_hash


def test_audit_chain_detects_tampering(
    session_factory: sessionmaker[Session],
    audit_logger: AuditLogger,
) -> None:
    ev1 = audit_logger.append(event_type="one", actor="sys", payload={"a": 1})
    audit_logger.append(event_type="two", actor="sys", payload={"b": 2})

    with session_factory() as session:
        session.execute(
            update(AuditLogRecord)
            .where(AuditLogRecord.id == ev1.id)
            .values(payload_json='{"a":999}')
        )
        session.commit()

    verification = audit_logger.verify_chain()
    assert verification.valid is False
    assert verification.broken_at_id == ev1.id
