"""Tests for risk tiers and non-overridable T3 rules."""

from __future__ import annotations

from ts_harness.core.models import RiskTier
from ts_harness.risk.tiers import ActionDisposition, classify_action, is_forbidden


def test_tier_classifications() -> None:
    assert classify_action(RiskTier.T0).disposition == ActionDisposition.AUTO
    assert classify_action(RiskTier.T1).disposition == ActionDisposition.AUTO_LOGGED
    assert classify_action(RiskTier.T2).disposition == ActionDisposition.APPROVAL_REQUIRED
    assert classify_action(RiskTier.T3).disposition == ActionDisposition.FORBIDDEN


def test_forbidden_categories_force_t3() -> None:
    for category in ("payment", "credential_entry", "security_setting_change", "trading"):
        assert is_forbidden(RiskTier.T0, category) is True
        policy = classify_action(RiskTier.T1, category)
        assert policy.tier == RiskTier.T3
        assert policy.disposition == ActionDisposition.FORBIDDEN
