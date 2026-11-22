"""Tests for Google Workspace OAuth 2.0 read-only flow and token refresh."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from ts_harness.api.app import create_app
from ts_harness.connectors.google_oauth import (
    GOOGLE_READONLY_SCOPES,
    build_google_auth_url,
    exchange_code_for_tokens,
    refresh_google_access_token,
)
from ts_harness.security.vault import SecretsVault


def test_google_oauth_url_exchange_and_refresh(tmp_path: Path) -> None:
    url = build_google_auth_url(
        client_id="cid-123",
        redirect_uri="http://localhost:8000/api/connectors/google/callback",
        state="state-xyz",
    )
    assert "accounts.google.com/o/oauth2/v2/auth" in url
    assert "access_type=offline" in url
    for scope in GOOGLE_READONLY_SCOPES:
        assert scope.split("/")[-1] in url

    def fake_post(endpoint: str, form: dict[str, str]) -> dict[str, Any]:
        if form.get("grant_type") == "authorization_code":
            return {"access_token": "ya29.initial", "refresh_token": "1//refresh"}
        return {"access_token": "ya29.refreshed"}

    tokens = exchange_code_for_tokens(
        code="auth-code",
        client_id="cid-123",
        client_secret="csec-456",
        redirect_uri="http://localhost:8000/api/connectors/google/callback",
        http_post=fake_post,
    )
    assert tokens["access_token"] == "ya29.initial"

    vault = SecretsVault(tmp_path / ".secrets.json")
    vault.set_secret("GOOGLE_CLIENT_ID", "cid-123")
    vault.set_secret("GOOGLE_CLIENT_SECRET", "csec-456")
    vault.set_secret("GOOGLE_REFRESH_TOKEN", "1//refresh")

    new_token = refresh_google_access_token(vault, http_post=fake_post)
    assert new_token == "ya29.refreshed"
    assert vault.get_secret("GOOGLE_WORKSPACE_TOKEN") == "ya29.refreshed"


def test_api_google_oauth_start_and_state_validation(tmp_path: Path) -> None:
    cfg_path = tmp_path / "settings.yaml"
    db_path = tmp_path / "oauth.db"
    data_dir = tmp_path / "data"
    cfg_path.write_text(
        f"data_dir: {data_dir}\ndb:\n  url: sqlite:///{db_path}\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(config_path=cfg_path))

    # Missing creds -> 400
    missing = client.get("/api/connectors/google/start", follow_redirects=False)
    assert missing.status_code == 400

    # Set client ID & secret via vault API
    client.post("/api/secrets", json={"key": "GOOGLE_CLIENT_ID", "value": "cid-123"})
    client.post("/api/secrets", json={"key": "GOOGLE_CLIENT_SECRET", "value": "csec-456"})

    started = client.get("/api/connectors/google/start", follow_redirects=False)
    assert started.status_code == 302
    assert "accounts.google.com/o/oauth2/v2/auth" in started.headers["location"]

    bad_cb = client.get(
        "/api/connectors/google/callback?code=abc&state=bad",
        follow_redirects=False,
    )
    assert bad_cb.status_code == 400
