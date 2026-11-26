"""Persistent approval queue for T2 and high-cost actions."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol, cast

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ts_harness.audit.logger import AuditLogger
from ts_harness.config import Currency
from ts_harness.db.models import ApprovalRecord
from ts_harness.logging import get_logger


class ApprovalExpiredError(RuntimeError):
    """Raised when attempting to approve an expired request."""


class ApprovalStatus(StrEnum):
    """Lifecycle states of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ApprovalRequest(BaseModel):
    """Domain representation of an approval item."""

    id: str
    task_id: str | None
    tool_name: str
    status: ApprovalStatus
    summary: str
    reason: str
    estimated_cost: float
    cost_currency: Currency
    reversibility: str
    preview_diff: str
    payload: dict[str, Any]
    decided_by: str | None = None
    decision_reason: str | None = None
    expires_at: datetime
    created_at: datetime
    decided_at: datetime | None = None


class NotificationHook(Protocol):
    """Hook invoked when a new approval request requires human attention."""

    def notify(self, request: ApprovalRequest) -> None:
        """Send a push notification for a pending approval."""
        ...


class LogNotificationHook:
    """Default notification hook that logs structured alerts."""

    def __init__(self) -> None:
        self._log = get_logger("approvals.notify")

    def notify(self, request: ApprovalRequest) -> None:
        self._log.info(
            "approval.notification",
            approval_id=request.id,
            tool_name=request.tool_name,
            summary=request.summary,
            estimated_cost=request.estimated_cost,
            currency=request.cost_currency,
        )


class NtfyNotificationHook:
    """Stub ntfy push notification hook (records notifications for testing/extension)."""

    def __init__(self, topic_url: str) -> None:
        self.topic_url = topic_url
        self.sent: list[dict[str, Any]] = []

    def notify(self, request: ApprovalRequest) -> None:
        self.sent.append(
            {
                "topic_url": self.topic_url,
                "approval_id": request.id,
                "title": f"Approval required: {request.tool_name}",
                "message": request.summary,
            }
        )


class ApprovalQueue:
    """Manages pending, approved, edited, rejected, and expired approval requests."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        audit_logger: AuditLogger,
        notifier: NotificationHook | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._audit = audit_logger
        self._notifier: NotificationHook = notifier or LogNotificationHook()

    def create_request(
        self,
        *,
        tool_name: str,
        summary: str,
        reason: str,
        task_id: str | None = None,
        estimated_cost: float = 0.0,
        cost_currency: Currency = "SGD",
        reversibility: str = "irreversible",
        preview_diff: str = "",
        payload: dict[str, Any] | None = None,
        ttl_minutes: int = 60,
        now: datetime | None = None,
    ) -> ApprovalRequest:
        """Create a new pending approval request and trigger notification hook."""
        created_at = now or datetime.now(UTC)
        expires_at = created_at + timedelta(minutes=ttl_minutes)

        with self._session_factory() as session:
            record = ApprovalRecord(
                id=str(uuid.uuid4()),
                task_id=task_id,
                tool_name=tool_name,
                status=ApprovalStatus.PENDING.value,
                summary=summary,
                reason=reason,
                estimated_cost=round(estimated_cost, 6),
                cost_currency=cost_currency,
                reversibility=reversibility,
                preview_diff=preview_diff,
                payload_json=json.dumps(payload or {}, sort_keys=True),
                expires_at=expires_at,
                created_at=created_at,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            req = self._to_request(record)

        self._audit.append(
            event_type="approval.requested",
            actor="system",
            task_id=task_id,
            payload={"approval_id": req.id, "tool_name": tool_name, "summary": summary},
        )
        self._notifier.notify(req)
        return req

    def get_request(self, approval_id: str) -> ApprovalRequest | None:
        """Fetch an approval request by ID."""
        with self._session_factory() as session:
            record = session.get(ApprovalRecord, approval_id)
            return self._to_request(record) if record is not None else None

    def list_pending(self, *, task_id: str | None = None) -> list[ApprovalRequest]:
        """List pending approval requests."""
        with self._session_factory() as session:
            stmt = (
                select(ApprovalRecord)
                .where(ApprovalRecord.status == ApprovalStatus.PENDING.value)
                .order_by(ApprovalRecord.created_at.asc())
            )
            if task_id is not None:
                stmt = stmt.where(ApprovalRecord.task_id == task_id)
            return [self._to_request(r) for r in session.scalars(stmt).all()]

    def approve(
        self,
        approval_id: str,
        *,
        actor: str = "user",
        reason: str = "Approved",
        now: datetime | None = None,
    ) -> ApprovalRequest:
        """Approve a pending request."""
        return self._decide(
            approval_id,
            status=ApprovalStatus.APPROVED,
            actor=actor,
            reason=reason,
            now=now,
        )

    def edit_and_approve(
        self,
        approval_id: str,
        updated_payload: dict[str, Any],
        *,
        actor: str = "user",
        reason: str = "Edited and approved",
        now: datetime | None = None,
    ) -> ApprovalRequest:
        """Edit the action payload and approve the request."""
        return self._decide(
            approval_id,
            status=ApprovalStatus.EDITED,
            actor=actor,
            reason=reason,
            updated_payload=updated_payload,
            now=now,
        )

    def reject(
        self,
        approval_id: str,
        *,
        reason: str,
        actor: str = "user",
        now: datetime | None = None,
    ) -> ApprovalRequest:
        """Reject a pending request."""
        return self._decide(
            approval_id,
            status=ApprovalStatus.REJECTED,
            actor=actor,
            reason=reason,
            now=now,
        )

    def expire_stale(self, *, now: datetime | None = None) -> int:
        """Mark expired pending approvals as expired."""
        current = now or datetime.now(UTC)
        count = 0
        with self._session_factory() as session:
            records = session.scalars(
                select(ApprovalRecord).where(ApprovalRecord.status == ApprovalStatus.PENDING.value)
            ).all()
            for rec in records:
                exp = rec.expires_at
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=UTC)
                if exp <= current:
                    rec.status = ApprovalStatus.EXPIRED.value
                    rec.decided_at = current
                    rec.decision_reason = "Expired before decision"
                    count += 1
            session.commit()
        return count

    def unattended_summary(self, task_id: str) -> dict[str, Any]:
        """Summarise held T2 approvals for an unattended run."""
        pending = self.list_pending(task_id=task_id)
        return {
            "task_id": task_id,
            "held_count": len(pending),
            "held_actions": [
                {
                    "approval_id": p.id,
                    "tool_name": p.tool_name,
                    "summary": p.summary,
                    "estimated_cost": p.estimated_cost,
                    "currency": p.cost_currency,
                }
                for p in pending
            ],
        }

    def _decide(
        self,
        approval_id: str,
        *,
        status: ApprovalStatus,
        actor: str,
        reason: str,
        updated_payload: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> ApprovalRequest:
        current = now or datetime.now(UTC)
        with self._session_factory() as session:
            record = session.get(ApprovalRecord, approval_id)
            if record is None:
                raise KeyError(f"Approval '{approval_id}' not found.")
            if record.status != ApprovalStatus.PENDING.value:
                raise ValueError(
                    f"Approval '{approval_id}' is already '{record.status}'."
                )
            exp = record.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=UTC)
            if exp <= current and status != ApprovalStatus.REJECTED:
                record.status = ApprovalStatus.EXPIRED.value
                record.decided_at = current
                record.decision_reason = "Expired before decision"
                session.commit()
                raise ApprovalExpiredError(f"Approval '{approval_id}' has expired.")

            record.status = status.value
            record.decided_by = actor
            record.decision_reason = reason
            record.decided_at = current
            if updated_payload is not None:
                record.payload_json = json.dumps(updated_payload, sort_keys=True)
            session.commit()
            session.refresh(record)
            req = self._to_request(record)

        self._audit.append(
            event_type=f"approval.{status.value}",
            actor=actor,
            task_id=req.task_id,
            payload={"approval_id": req.id, "tool_name": req.tool_name, "reason": reason},
        )
        return req

    @staticmethod
    def _to_request(record: ApprovalRecord) -> ApprovalRequest:
        return ApprovalRequest(
            id=record.id,
            task_id=record.task_id,
            tool_name=record.tool_name,
            status=ApprovalStatus(record.status),
            summary=record.summary,
            reason=record.reason,
            estimated_cost=record.estimated_cost,
            cost_currency=cast(Currency, record.cost_currency),
            reversibility=record.reversibility,
            preview_diff=record.preview_diff,
            payload=json.loads(record.payload_json),
            decided_by=record.decided_by,
            decision_reason=record.decision_reason,
            expires_at=record.expires_at,
            created_at=record.created_at,
            decided_at=record.decided_at,
        )
