"""Layered memory with provenance, context budgeting, retention, and true deletion."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel


class DurableFact(BaseModel):
    """A persisted fact with provenance, source, and retention expiry."""

    id: str
    key: str
    value: str
    provenance: str
    source: str
    created_at: datetime
    expires_at: datetime | None = None


class ContextBudgeter:
    """Selects context items within a strict character/token budget."""

    def __init__(self, max_chars: int = 8000) -> None:
        self._max_chars = max_chars

    def fit(self, items: list[str]) -> list[str]:
        selected: list[str] = []
        used = 0
        for item in items:
            if used + len(item) > self._max_chars:
                break
            selected.append(item)
            used += len(item)
        return selected


class MemoryStore:
    """Manages working state, task history, and durable facts with true deletion."""

    def __init__(self) -> None:
        self._working: dict[str, dict[str, Any]] = {}
        self._history: list[dict[str, Any]] = []
        self._facts: dict[str, DurableFact] = {}

    def set_working(self, task_id: str, key: str, value: Any) -> None:
        self._working.setdefault(task_id, {})[key] = value

    def get_working(self, task_id: str) -> dict[str, Any]:
        return dict(self._working.get(task_id, {}))

    def clear_working(self, task_id: str) -> None:
        self._working.pop(task_id, None)

    def record_history(self, task_id: str, workflow_name: str, summary: str) -> None:
        self._history.append(
            {
                "task_id": task_id,
                "workflow_name": workflow_name,
                "summary": summary,
                "recorded_at": datetime.now(UTC).isoformat(),
            }
        )

    def list_history(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self._history[-limit:]

    def add_fact(
        self,
        *,
        key: str,
        value: str,
        provenance: str,
        source: str,
        ttl_days: int | None = None,
        now: datetime | None = None,
    ) -> DurableFact:
        created = now or datetime.now(UTC)
        expires = created + timedelta(days=ttl_days) if ttl_days is not None else None
        fact = DurableFact(
            id=str(uuid.uuid4()),
            key=key,
            value=value,
            provenance=provenance,
            source=source,
            created_at=created,
            expires_at=expires,
        )
        self._facts[fact.id] = fact
        return fact

    def list_facts(self, *, now: datetime | None = None) -> list[DurableFact]:
        current = now or datetime.now(UTC)
        return [
            f
            for f in self._facts.values()
            if f.expires_at is None or f.expires_at > current
        ]

    def delete_fact(self, fact_id: str) -> bool:
        """True deletion: immediately removes the fact from memory."""
        return self._facts.pop(fact_id, None) is not None

    def purge_expired(self, *, now: datetime | None = None) -> int:
        """True deletion of all expired facts."""
        current = now or datetime.now(UTC)
        expired_ids = [
            fid
            for fid, f in self._facts.items()
            if f.expires_at is not None and f.expires_at <= current
        ]
        for fid in expired_ids:
            del self._facts[fid]
        return len(expired_ids)
