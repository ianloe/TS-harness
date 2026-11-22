"""Google Workspace OAuth 2.0 helper for read-only Gmail, Calendar, and Drive access."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from ts_harness.security.vault import SecretsVault

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

GOOGLE_READONLY_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
)

HttpPostForm = Callable[[str, dict[str, str]], dict[str, Any]]


def _default_post_form(url: str, form_data: dict[str, str]) -> dict[str, Any]:
    encoded = urllib.parse.urlencode(form_data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=encoded,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "ts-harness/0.1",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
        return data


def build_google_auth_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: tuple[str, ...] = GOOGLE_READONLY_SCOPES,
) -> str:
    """Build the Google OAuth 2.0 consent URL requesting offline read-only access."""
    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
    )
    return f"{GOOGLE_AUTH_ENDPOINT}?{params}"


def exchange_code_for_tokens(
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    http_post: HttpPostForm = _default_post_form,
) -> dict[str, Any]:
    """Exchange an authorization code for access and refresh tokens."""
    return http_post(
        GOOGLE_TOKEN_ENDPOINT,
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )


def refresh_google_access_token(
    vault: SecretsVault,
    *,
    http_post: HttpPostForm = _default_post_form,
) -> str:
    """Refresh GOOGLE_WORKSPACE_TOKEN using stored client credentials and refresh token."""
    client_id = vault.get_secret("GOOGLE_CLIENT_ID")
    client_secret = vault.get_secret("GOOGLE_CLIENT_SECRET")
    refresh_token = vault.get_secret("GOOGLE_REFRESH_TOKEN")
    if not (client_id and client_secret and refresh_token):
        raise ValueError(
            "Missing GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, or GOOGLE_REFRESH_TOKEN in vault."
        )
    data = http_post(
        GOOGLE_TOKEN_ENDPOINT,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    access_token = str(data.get("access_token", "")).strip()
    if not access_token:
        raise ValueError("Google token endpoint did not return an access_token.")
    vault.set_secret("GOOGLE_WORKSPACE_TOKEN", access_token)
    return access_token
