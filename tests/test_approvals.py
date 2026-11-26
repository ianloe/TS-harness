"""Tests for the human-in-the-loop approval queue."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ts_harness.approvals.queue import (
    ApprovalExpiredError,
    ApprovalQueue,
    ApprovalStatus,
    NtfyNotificationHook,
)
from ts_harness.audit.logger import AuditLogger


def test_approval_queue_lifecycle_approve_edit_reject_expire(
    session_factory,
    audit_logger: AuditLogger,
) -> None:
    notifier = NtfyNotificationHook("https://ntfy.sh/ts-harness-test")
    queue = ApprovalQueue(session_factory, audit_logger, notifier=notifier)

    req1 = queue.create_request(
        task_id="task-1",
        tool_name="send_email",
        summary="Send weekly status email",
        reason="T2 outward-facing action",
        estimated_cost=0.05,
        cost_currency="SGD",
        reversibility="irreversible",
        preview_diff="+ To: team@example.com",
        payload={"to": "team@example.com", "body": "Draft"},
    )
    assert len(notifier.sent) == 1
    assert len(queue.list_pending(task_id="task-1")) == 1

    summary = queue.unattended_summary("task-1")
    assert summary["held_count"] == 1

    edited = queue.edit_and_approve(
        req1.id,
        {"to": "team@example.com", "body": "Edited Draft"},
        actor="ian",
    )
    assert edited.status == ApprovalStatus.EDITED
    assert edited.payload["body"] == "Edited Draft"

    req2 = queue.create_request(
        task_id="task-1",
        tool_name="delete_file",
        summary="Delete old archive",
        reason="T2 destructive action",
    )
    rejected = queue.reject(req2.id, reason="Keep archive", actor="ian")
    assert rejected.status == ApprovalStatus.REJECTED

    base = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
    req3 = queue.create_request(
        task_id="task-2",
        tool_name="publish_post",
        summary="Publish digest",
        reason="T2 publish",
        ttl_minutes=10,
        now=base,
    )
    with pytest.raises(ApprovalExpiredError):
        queue.approve(req3.id, now=base + timedelta(minutes=15))

    req4 = queue.create_request(
        task_id="task-2",
        tool_name="publish_post",
        summary="Publish digest 2",
        reason="T2 publish",
        ttl_minutes=5,
        now=base,
    )
    expired_count = queue.expire_stale(now=base + timedelta(minutes=6))
    assert expired_count == 1
    fetched = queue.get_request(req4.id)
    assert fetched is not None and fetched.status == ApprovalStatus.EXPIRED
