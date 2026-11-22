"""Pydantic v2 schema for versioned YAML policy rules."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from ts_harness.core.models import DataClass, RiskTier
from ts_harness.guardrails.injection import TrustLevel


class RuleEffect(StrEnum):
    """Action taken when a policy rule matches."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class TimeWindow(BaseModel):
    """UTC hour and weekday window for time-bound rules."""

    start_hour_utc: int = Field(ge=0, le=23)
    end_hour_utc: int = Field(ge=0, le=23)
    days_of_week: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])


class RuleMatch(BaseModel):
    """Dimensions matched against a tool call and its execution context."""

    tools: list[str] = Field(default_factory=lambda: ["*"])
    action_tiers: list[RiskTier] | None = None
    resource_scopes: list[str] | None = None
    recipients_or_domains: list[str] | None = None
    data_classes: list[DataClass] | None = None
    time_window: TimeWindow | None = None
    max_amount: float | None = Field(default=None, ge=0.0)
    trust_levels: list[TrustLevel] | None = None


class PolicyRule(BaseModel):
    """A single versioned policy rule."""

    id: str = Field(min_length=1)
    description: str = Field(default="")
    effect: RuleEffect
    match: RuleMatch = Field(default_factory=RuleMatch)


class PolicySet(BaseModel):
    """Top-level validated YAML policy document."""

    version: str = Field(min_length=1)
    name: str = Field(min_length=1)
    default_effect: RuleEffect = Field(default=RuleEffect.DENY)
    rules: list[PolicyRule] = Field(default_factory=list)
