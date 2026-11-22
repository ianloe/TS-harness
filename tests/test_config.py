"""Tests for configuration loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from ts_harness.config import BudgetConfig, load_settings
from ts_harness.logging import REDACTED, redact_value


def test_budget_config_accepts_sgd_and_usd() -> None:
    sgd = BudgetConfig(currency="SGD")
    usd = BudgetConfig(currency="USD")
    assert sgd.currency == "SGD"
    assert usd.currency == "USD"


def test_budget_config_rejects_other_currencies() -> None:
    with pytest.raises(ValidationError):
        BudgetConfig(currency="EUR")  # type: ignore[arg-type]


def test_load_settings_from_yaml(tmp_path: Path) -> None:
    cfg = tmp_path / "settings.yaml"
    cfg.write_text(
        "environment: test\nbudget:\n  currency: USD\n  daily_limit: 42.0\n",
        encoding="utf-8",
    )
    settings = load_settings(cfg)
    assert settings.environment == "test"
    assert settings.budget.currency == "USD"
    assert settings.budget.daily_limit == 42.0


def test_redact_value_masks_keys_and_tokens() -> None:
    payload = {
        "api_key": "super-secret-key",
        "nested": {"message": "Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"},
        "raw": "token sk-1234567890abcdef in text",
    }
    redacted = redact_value(payload)
    assert redacted["api_key"] == REDACTED
    assert REDACTED in redacted["nested"]["message"]
    assert REDACTED in redacted["raw"]
