"""Tests for global, workflow, and connector kill switches."""

from __future__ import annotations

from ts_harness.audit.logger import AuditLogger
from ts_harness.killswitch.manager import KillSwitchManager


def test_global_workflow_and_connector_kill_switches(
    kill_switch: KillSwitchManager,
    audit_logger: AuditLogger,
) -> None:
    blocked, _ = kill_switch.is_blocked(workflow_name="inbox_triage", connector_name="gmail")
    assert blocked is False

    kill_switch.pause_workflow("inbox_triage", reason="Testing pause", actor="admin")
    blocked, reason = kill_switch.is_blocked(workflow_name="inbox_triage")
    assert blocked is True
    assert reason is not None and "workflow:inbox_triage" in reason

    other_blocked, _ = kill_switch.is_blocked(workflow_name="meeting_prep")
    assert other_blocked is False

    kill_switch.resume_workflow("inbox_triage", actor="admin")
    blocked_after, _ = kill_switch.is_blocked(workflow_name="inbox_triage")
    assert blocked_after is False

    kill_switch.revoke_connector("gmail", reason="Token rotated")
    conn_blocked, _ = kill_switch.is_blocked(connector_name="gmail")
    assert conn_blocked is True

    kill_switch.pause_all(reason="Incident")
    all_blocked, _ = kill_switch.is_blocked(workflow_name="meeting_prep")
    assert all_blocked is True

    events = audit_logger.list_events()
    assert len(events) >= 4
