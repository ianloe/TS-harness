"""Agent and workflow governance registry with review dates and change log."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from ts_harness.core.models import RiskTier


class RegistryEntry(BaseModel):
    """Registered agent or workflow metadata."""

    id: str
    kind: Literal["agent", "workflow"]
    owner: str
    purpose: str
    permissions: list[str] = Field(default_factory=list)
    risk_tier: RiskTier = RiskTier.T0
    draft_only: bool = True
    review_date: date
    last_updated: date


class ChangeLogEntry(BaseModel):
    """Recorded governance change log item."""

    timestamp: datetime
    actor: str
    target_id: str
    summary: str


class GovernanceRegistry(BaseModel):
    """Versioned registry of all agents, workflows, and governance changes."""

    version: str = "1.0.0"
    entries: list[RegistryEntry] = Field(default_factory=list)
    changelog: list[ChangeLogEntry] = Field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: Path) -> GovernanceRegistry:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(**raw)

    def to_yaml(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        dumped = yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False)
        path.write_text(dumped, encoding="utf-8")

    def due_for_review(self, *, as_of: date | None = None) -> list[RegistryEntry]:
        """Return entries whose review_date is on or before ``as_of``."""
        target = as_of or datetime.now(UTC).date()
        return [e for e in self.entries if e.review_date <= target]

    def record_change(self, *, actor: str, target_id: str, summary: str) -> ChangeLogEntry:
        """Append a change log entry."""
        entry = ChangeLogEntry(
            timestamp=datetime.now(UTC),
            actor=actor,
            target_id=target_id,
            summary=summary,
        )
        self.changelog.append(entry)
        return entry
