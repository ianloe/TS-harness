"""Read-only real connector adapters using scoped tokens from SecretsVault."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

from ts_harness.connectors.google_oauth import refresh_google_access_token
from ts_harness.connectors.interfaces import (
    CalendarEvent,
    DriveDocument,
    EmailDraft,
    EmailMessage,
    GitHubActivity,
)
from ts_harness.security.vault import SecretsVault


def _resolve_google_token(vault: SecretsVault, token_key: str) -> str:
    token = vault.get_secret(token_key)
    if token:
        return token
    if (
        vault.get_secret("GOOGLE_CLIENT_ID")
        and vault.get_secret("GOOGLE_CLIENT_SECRET")
        and vault.get_secret("GOOGLE_REFRESH_TOKEN")
    ):
        return refresh_google_access_token(vault)
    raise ReadOnlyConnectorError(f"Missing secret '{token_key}'.")


class ReadOnlyConnectorError(RuntimeError):
    """Raised when a read-only connector lacks credentials or fails a request."""


def _fetch_json(url: str, token: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "ts-harness/0.1",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
        return data


class ReadOnlyGmailConnector:
    """Read-only Gmail API adapter (drafts/labels remain local until write scope granted)."""

    def __init__(self, vault: SecretsVault, token_key: str = "GMAIL_READONLY_TOKEN") -> None:
        self._vault = vault
        self._token_key = token_key

    def list_messages(self, *, limit: int = 10) -> list[EmailMessage]:
        token = _resolve_google_token(self._vault, self._token_key)
        data = _fetch_json(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults={limit}",
            token,
        )
        results: list[EmailMessage] = []
        now = datetime.now(UTC)
        for item in data.get("messages", [])[:limit]:
            msg_id = str(item.get("id", ""))
            if not msg_id:
                continue
            safe_id = urllib.parse.quote(msg_id, safe="")
            detail = _fetch_json(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{safe_id}"
                "?format=metadata&metadataHeaders=Subject&metadataHeaders=From",
                token,
            )
            headers = {
                str(h.get("name", "")).lower(): str(h.get("value", ""))
                for h in detail.get("payload", {}).get("headers", [])
            }
            results.append(
                EmailMessage(
                    id=msg_id,
                    sender=headers.get("from", "unknown"),
                    subject=headers.get("subject", "(No subject)"),
                    body=str(detail.get("snippet", "")),
                    received_at=now,
                )
            )
        return results

    def create_draft(
        self,
        *,
        in_reply_to: str,
        recipient: str,
        subject: str,
        body: str,
    ) -> EmailDraft:
        """Create a local-only draft when using a read-only Gmail token."""
        return EmailDraft(
            id=f"local-draft-{in_reply_to}",
            in_reply_to=in_reply_to,
            recipient=recipient,
            subject=subject,
            body=body,
        )

    def propose_label(self, *, message_id: str, label: str) -> dict[str, str]:
        return {"message_id": message_id, "proposed_label": label}


class ReadOnlyGoogleCalendarConnector:
    """Read-only Google Calendar API adapter."""

    def __init__(self, vault: SecretsVault, token_key: str = "GCAL_READONLY_TOKEN") -> None:
        self._vault = vault
        self._token_key = token_key

    def list_events(self, *, limit: int = 10) -> list[CalendarEvent]:
        token = _resolve_google_token(self._vault, self._token_key)
        data = _fetch_json(
            f"https://www.googleapis.com/calendar/v3/calendars/primary/events?maxResults={limit}",
            token,
        )
        now = datetime.now(UTC)
        return [
            CalendarEvent(
                id=str(item.get("id", "")),
                title=str(item.get("summary", "Untitled")),
                start_time=now,
                end_time=now,
            )
            for item in data.get("items", [])
        ]


class ReadOnlyGoogleDriveConnector:
    """Read-only Google Drive API adapter."""

    def __init__(self, vault: SecretsVault, token_key: str = "GDRIVE_READONLY_TOKEN") -> None:
        self._vault = vault
        self._token_key = token_key

    def search_documents(self, query: str, *, limit: int = 5) -> list[DriveDocument]:
        token = _resolve_google_token(self._vault, self._token_key)
        encoded = urllib.parse.quote(f"name contains '{query}'")
        data = _fetch_json(
            f"https://www.googleapis.com/drive/v3/files?q={encoded}&pageSize={limit}",
            token,
        )
        return [
            DriveDocument(
                id=str(item.get("id", "")),
                title=str(item.get("name", "Untitled")),
                content="",
                url=f"https://drive.google.com/file/d/{item.get('id', '')}",
            )
            for item in data.get("files", [])
        ]


class ReadOnlyGitHubConnector:
    """Read-only GitHub REST API adapter."""

    def __init__(self, vault: SecretsVault, token_key: str = "GITHUB_READONLY_TOKEN") -> None:
        self._vault = vault
        self._token_key = token_key

    def list_recent_activity(self, repo: str, *, limit: int = 10) -> list[GitHubActivity]:
        if not re.match(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$", repo):
            raise ReadOnlyConnectorError(f"Invalid GitHub repository format: '{repo}'.")
        token = self._vault.get_secret(self._token_key)
        if not token:
            raise ReadOnlyConnectorError(f"Missing secret '{self._token_key}'.")
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/issues?per_page={limit}&state=all",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "ts-harness/0.1",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            items: list[dict[str, Any]] = json.loads(resp.read().decode("utf-8"))
        return [
            GitHubActivity(
                repo=repo,
                number=int(item.get("number", 0)),
                title=str(item.get("title", "")),
                state=str(item.get("state", "open")),
                url=str(item.get("html_url", "")),
            )
            for item in items
        ]
