"""Risk tier definitions and non-overridable T3 enforcement."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from ts_harness.core.models import RiskTier


class ActionDisposition(StrEnum):
    """How a risk tier is handled by default."""

    AUTO = "auto"
    AUTO_LOGGED = "auto_logged"
    APPROVAL_REQUIRED = "approval_required"
    FORBIDDEN = "forbidden"


class ActionCategory(StrEnum):
    """High-risk action categories that are permanently forbidden (T3)."""

    PAYMENT = "payment"
    CREDENTIAL_ENTRY = "credential_entry"
    SECURITY_SETTING_CHANGE = "security_setting_change"
    TRADING = "trading"


FORBIDDEN_CATEGORIES: frozenset[str] = frozenset(c.value for c in ActionCategory)


class TierPolicy(BaseModel):
    """Metadata and default disposition for an action risk tier."""

    tier: RiskTier
    disposition: ActionDisposition
    reversible: bool
    description: str


TIER_POLICIES: dict[RiskTier, TierPolicy] = {
    RiskTier.T0: TierPolicy(
        tier=RiskTier.T0,
        disposition=ActionDisposition.AUTO,
        reversible=True,
        description="Read-only operations; executed automatically.",
    ),
    RiskTier.T1: TierPolicy(
        tier=RiskTier.T1,
        disposition=ActionDisposition.AUTO_LOGGED,
        reversible=True,
        description="Reversible writes (drafts, notes, calendar holds); auto-executed and logged.",
    ),
    RiskTier.T2: TierPolicy(
        tier=RiskTier.T2,
        disposition=ActionDisposition.APPROVAL_REQUIRED,
        reversible=False,
        description="Outward-facing or hard-to-undo actions (send, share, publish, delete); "
        "requires human approval.",
    ),
    RiskTier.T3: TierPolicy(
        tier=RiskTier.T3,
        disposition=ActionDisposition.FORBIDDEN,
        reversible=False,
        description="Forbidden actions (payments, credential entry, security setting changes, "
        "trading); cannot be overridden by configuration.",
    ),
}


def is_forbidden(risk_tier: RiskTier, category: str | None = None) -> bool:
    """Return True if the tier is T3 or the category is permanently forbidden."""
    if risk_tier == RiskTier.T3:
        return True
    return category is not None and category.lower() in FORBIDDEN_CATEGORIES


def classify_action(risk_tier: RiskTier, category: str | None = None) -> TierPolicy:
    """Resolve the effective TierPolicy, enforcing non-overridable T3 rules."""
    if is_forbidden(risk_tier, category):
        return TIER_POLICIES[RiskTier.T3]
    return TIER_POLICIES[risk_tier]
