"""Secrets vault abstraction using environment variables and 0600 local vault file."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from pydantic import BaseModel

MANAGED_SECRET_KEYS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "AGNES_AI_API_KEY",
    "DEEPSEEK_API_KEY",
    "GOOGLE_WORKSPACE_TOKEN",
    "MICROSOFT_365_TOKEN",
    "LARK_APP_ID",
    "LARK_APP_SECRET",
    "LARK_TENANT_ACCESS_TOKEN",
    "AEGIS_API_TOKEN",
    "NTFY_TOKEN",
)

_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


def mask_secret(value: str) -> str:
    """Return a masked preview of a secret without exposing its body."""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


class SecretStatus(BaseModel):
    """Non-sensitive status of a managed secret."""

    key: str
    configured: bool
    masked_preview: str | None = None
    source: str = "unset"


class SecretsVault:
    """Manages API keys outside the repository and model context."""

    def __init__(self, vault_path: Path) -> None:
        self._vault_path = vault_path

    def get_secret(self, key: str) -> str | None:
        """Retrieve a secret from the vault file or environment."""
        self._validate_key(key)
        vault_data = self._read_vault()
        if key in vault_data and vault_data[key]:
            return vault_data[key]
        env_val = os.environ.get(key)
        return env_val if env_val else None

    def set_secret(self, key: str, value: str) -> None:
        """Store a secret in the 0600-protected vault file."""
        self._validate_key(key)
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"Secret value for '{key}' cannot be empty.")
        vault_data = self._read_vault()
        vault_data[key] = cleaned
        self._write_vault(vault_data)

    def delete_secret(self, key: str) -> bool:
        """Delete a secret from the vault file."""
        self._validate_key(key)
        vault_data = self._read_vault()
        if key not in vault_data:
            return False
        del vault_data[key]
        self._write_vault(vault_data)
        return True

    def list_statuses(self, keys: tuple[str, ...] = MANAGED_SECRET_KEYS) -> list[SecretStatus]:
        """Return masked statuses for all managed keys (never raw values)."""
        vault_data = self._read_vault()
        all_keys = list(dict.fromkeys([*keys, *sorted(vault_data.keys())]))
        statuses: list[SecretStatus] = []
        for key in all_keys:
            if key in vault_data and vault_data[key]:
                statuses.append(
                    SecretStatus(
                        key=key,
                        configured=True,
                        masked_preview=mask_secret(vault_data[key]),
                        source="vault",
                    )
                )
            elif os.environ.get(key):
                env_val = os.environ[key]
                statuses.append(
                    SecretStatus(
                        key=key,
                        configured=True,
                        masked_preview=mask_secret(env_val),
                        source="environment",
                    )
                )
            else:
                statuses.append(
                    SecretStatus(
                        key=key,
                        configured=False,
                        masked_preview=None,
                        source="unset",
                    )
                )
        return statuses

    def _read_vault(self) -> dict[str, str]:
        if not self._vault_path.exists():
            return {}
        raw = json.loads(self._vault_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) for k, v in raw.items()}

    def _write_vault(self, data: dict[str, str]) -> None:
        self._vault_path.parent.mkdir(parents=True, exist_ok=True)
        self._vault_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        os.chmod(self._vault_path, 0o600)

    @staticmethod
    def _validate_key(key: str) -> None:
        if not _KEY_PATTERN.match(key):
            raise ValueError(
                f"Invalid secret key '{key}'. Must match ^[A-Z][A-Z0-9_]{{2,63}}$."
            )
