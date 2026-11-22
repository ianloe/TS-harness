"""Tests for the secrets vault."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from ts_harness.security.vault import SecretsVault, mask_secret


def test_mask_secret() -> None:
    assert mask_secret("short") == "****"
    assert mask_secret("sk-ant-1234567890abcd") == "sk-a...abcd"


def test_vault_set_get_delete_and_permissions(tmp_path: Path) -> None:
    vault_file = tmp_path / ".secrets.json"
    vault = SecretsVault(vault_file)

    vault.set_secret("ANTHROPIC_API_KEY", "sk-ant-secret-9999")
    assert vault.get_secret("ANTHROPIC_API_KEY") == "sk-ant-secret-9999"

    mode = stat.S_IMODE(vault_file.stat().st_mode)
    assert mode == 0o600

    statuses = {s.key: s for s in vault.list_statuses()}
    assert "OPENROUTER_API_KEY" in statuses
    assert "AGNES_AI_API_KEY" in statuses
    assert "DEEPSEEK_API_KEY" in statuses
    assert statuses["ANTHROPIC_API_KEY"].configured is True
    assert statuses["ANTHROPIC_API_KEY"].source == "vault"
    assert statuses["ANTHROPIC_API_KEY"].masked_preview == "sk-a...9999"
    assert "sk-ant-secret-9999" not in str(statuses)

    assert vault.delete_secret("ANTHROPIC_API_KEY") is True
    assert vault.delete_secret("ANTHROPIC_API_KEY") is False


def test_vault_rejects_invalid_key_and_empty_value(tmp_path: Path) -> None:
    vault = SecretsVault(tmp_path / ".secrets.json")
    with pytest.raises(ValueError):
        vault.set_secret("bad-key", "value")
    with pytest.raises(ValueError):
        vault.set_secret("ANTHROPIC_API_KEY", "   ")
