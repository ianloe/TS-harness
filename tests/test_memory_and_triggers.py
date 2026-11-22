"""Tests for layered memory, preferences, context budgeting, and triggers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from ts_harness.memory.layered import ContextBudgeter, MemoryStore
from ts_harness.memory.preferences import UserPreferences
from ts_harness.triggers.manager import TriggerKind, TriggerManager, TriggerSpec


def test_preferences_and_layered_memory(tmp_path: Path) -> None:
    prefs_path = tmp_path / "prefs.yaml"
    prefs = UserPreferences()
    prefs.to_yaml(prefs_path)
    loaded = UserPreferences.from_yaml(prefs_path)
    assert loaded.language == "en-GB"
    assert loaded.no_em_dashes is True
    assert loaded.word_page_size == "A4"
    assert loaded.currency == "SGD"

    mem = MemoryStore()
    mem.set_working("t1", "step", "plan")
    assert mem.get_working("t1") == {"step": "plan"}
    mem.clear_working("t1")
    assert mem.get_working("t1") == {}

    now = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
    f1 = mem.add_fact(
        key="role",
        value="architect",
        provenance="user",
        source="chat",
        ttl_days=7,
        now=now,
    )
    f2 = mem.add_fact(key="temp", value="123", provenance="tool", source="web", ttl_days=1, now=now)
    assert len(mem.list_facts(now=now)) == 2

    # True deletion
    assert mem.delete_fact(f1.id) is True
    assert mem.delete_fact(f1.id) is False

    # Retention expiry purge
    purged = mem.purge_expired(now=now + timedelta(days=2))
    assert purged == 1
    assert mem.list_facts(now=now + timedelta(days=2)) == []
    assert f2.id not in [f.id for f in mem.list_facts(now=now)]

    budgeter = ContextBudgeter(max_chars=10)
    assert budgeter.fit(["hello", "world", "extra"]) == ["hello", "world"]


def test_trigger_dedupe_and_rate_limit() -> None:
    mgr = TriggerManager()
    mgr.register(
        TriggerSpec(
            id="inbox-poll",
            kind=TriggerKind.CRON,
            workflow_name="inbox_triage",
            schedule_or_rule="0 * * * *",
            dedupe_window_seconds=60,
            max_per_window=2,
            rate_window_seconds=3600,
        )
    )
    t0 = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)
    assert mgr.should_fire("inbox-poll", dedupe_key="k1", now=t0).accepted is True
    # Duplicate within 60s
    dup = mgr.should_fire("inbox-poll", dedupe_key="k1", now=t0 + timedelta(seconds=10))
    assert dup.accepted is False
    # New key accepted
    ok2 = mgr.should_fire("inbox-poll", dedupe_key="k2", now=t0 + timedelta(seconds=20))
    assert ok2.accepted is True
    # Third fire exceeds max_per_window=2
    rate_hit = mgr.should_fire("inbox-poll", dedupe_key="k3", now=t0 + timedelta(seconds=30))
    assert rate_hit.accepted is False
