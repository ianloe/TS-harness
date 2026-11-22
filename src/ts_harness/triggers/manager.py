"""Trigger scheduler/dispatcher with dedupe and rate limits."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, Field


class TriggerKind(StrEnum):
    """Supported trigger types."""

    CRON = "cron"
    EMAIL_RULE = "email_rule"
    CALENDAR_CHANGE = "calendar_change"
    WEBHOOK = "webhook"


class TriggerSpec(BaseModel):
    """Definition of a workflow trigger."""

    id: str
    kind: TriggerKind
    workflow_name: str
    schedule_or_rule: str
    dedupe_window_seconds: int = Field(default=300, ge=0)
    max_per_window: int = Field(default=5, ge=1)
    rate_window_seconds: int = Field(default=3600, ge=1)


class TriggerDecision(BaseModel):
    """Result of evaluating whether a trigger event should fire."""

    accepted: bool
    reason: str


class TriggerManager:
    """Enforces deduplication and rate limits across cron and event triggers."""

    def __init__(self) -> None:
        self._triggers: dict[str, TriggerSpec] = {}
        self._seen_keys: dict[str, datetime] = {}
        self._fire_times: dict[str, list[datetime]] = {}

    def register(self, spec: TriggerSpec) -> None:
        self._triggers[spec.id] = spec

    def should_fire(
        self,
        trigger_id: str,
        *,
        dedupe_key: str,
        now: datetime | None = None,
    ) -> TriggerDecision:
        spec = self._triggers.get(trigger_id)
        if spec is None:
            return TriggerDecision(accepted=False, reason=f"Unknown trigger '{trigger_id}'.")

        current = now or datetime.now(UTC)

        # Dedupe check
        full_key = f"{trigger_id}:{dedupe_key}"
        last_seen = self._seen_keys.get(full_key)
        if last_seen is not None and (current - last_seen) < timedelta(
            seconds=spec.dedupe_window_seconds
        ):
            return TriggerDecision(
                accepted=False,
                reason=f"Duplicate event '{dedupe_key}' within dedupe window.",
            )

        # Rate limit check
        window_start = current - timedelta(seconds=spec.rate_window_seconds)
        recent = [t for t in self._fire_times.get(trigger_id, []) if t >= window_start]
        if len(recent) >= spec.max_per_window:
            return TriggerDecision(
                accepted=False,
                reason=f"Rate limit exceeded for trigger '{trigger_id}' ({spec.max_per_window}).",
            )

        recent.append(current)
        self._fire_times[trigger_id] = recent
        self._seen_keys[full_key] = current
        return TriggerDecision(accepted=True, reason="Trigger accepted.")
