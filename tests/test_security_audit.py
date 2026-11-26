"""Regression tests for security audit findings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ts_harness.agents.models import ModelMessage, ModelProviderError, VaultModelClient
from ts_harness.api.app import create_app
from ts_harness.config import ModelRoleConfig, TelemetryConfig
from ts_harness.connectors.readonly import ReadOnlyConnectorError, ReadOnlyGitHubConnector
from ts_harness.guardrails.filters import redact_pii_and_secrets
from ts_harness.logging import REDACTED, redact_value
from ts_harness.security.vault import SecretsVault


def test_security_headers_present_on_responses(tmp_path: Path) -> None:
    cfg_path = tmp_path / "settings.yaml"
    db_path = tmp_path / "sec.db"
    cfg_path.write_text(f"db:\n  url: sqlite:///{db_path}\n", encoding="utf-8")
    client = TestClient(create_app(config_path=cfg_path))

    res = client.get("/health")
    assert res.status_code == 200
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    assert res.headers["referrer-policy"] == "no-referrer"


def test_telemetry_url_rejects_non_http_schemes() -> None:
    with pytest.raises(ValidationError):
        TelemetryConfig(enabled=True, aegis_export_url="file:///etc/passwd")
    with pytest.raises(ValidationError):
        TelemetryConfig(enabled=True, aegis_export_url="javascript:alert(1)")
    ok = TelemetryConfig(enabled=True, aegis_export_url="https://aegis.local/v1")
    assert ok.aegis_export_url == "https://aegis.local/v1"


def test_github_repo_validation_blocks_path_traversal(tmp_path: Path) -> None:
    vault = SecretsVault(tmp_path / ".secrets.json")
    vault.set_secret("GITHUB_READONLY_TOKEN", "ghp_1234567890abcdef")
    gh = ReadOnlyGitHubConnector(vault)
    with pytest.raises(ReadOnlyConnectorError, match="Invalid GitHub repository"):
        gh.list_recent_activity("../../user/repos")


def test_google_api_key_redaction_and_header_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_key = "AIzaSyDummyGoogleKey1234567890abcd"
    assert fake_key not in redact_pii_and_secrets(f"key={fake_key}").text
    assert REDACTED in redact_value({"msg": f"using {fake_key}"})["msg"]

    vault = SecretsVault(tmp_path / ".secrets.json")
    vault.set_secret("GEMINI_API_KEY", fake_key)
    client = VaultModelClient(vault)

    captured: dict[str, Any] = {}

    def fake_post(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        captured["url"] = url
        captured["headers"] = headers
        return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    monkeypatch.setattr(client, "_post_json", fake_post)
    resp = client.complete(
        [ModelMessage(role="user", content="Hi")],
        role_config=ModelRoleConfig(provider="gemini", model_name="gemini-2.5-flash"),
    )
    assert resp.content == "ok"
    assert fake_key not in captured["url"]
    assert captured["headers"]["x-goog-api-key"] == fake_key

    with pytest.raises(ModelProviderError, match="Invalid model_name"):
        client.complete(
            [ModelMessage(role="user", content="Hi")],
            role_config=ModelRoleConfig(provider="gemini", model_name="../bad?x=1"),
        )
