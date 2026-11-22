"""Unified read-only connectors for Google Workspace, Microsoft 365, and Lark Suite."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel

from ts_harness.connectors.interfaces import (
    CalendarConnector,
    CalendarEvent,
    DriveConnector,
    DriveDocument,
    EmailDraft,
    EmailMessage,
    MailConnector,
)
from ts_harness.connectors.mocks import (
    MockCalendarConnector,
    MockDriveConnector,
    MockMailConnector,
)
from ts_harness.connectors.readonly import (
    ReadOnlyConnectorError,
    ReadOnlyGmailConnector,
    ReadOnlyGoogleCalendarConnector,
    ReadOnlyGoogleDriveConnector,
)
from ts_harness.security.vault import SecretsVault

SuiteKind = Literal["google_workspace", "microsoft_365", "lark_suite"]
HttpGetJson = Callable[[str, str], dict[str, Any]]


def _default_http_get(url: str, token: str) -> dict[str, Any]:
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


@dataclass
class ConnectorBundle:
    """Bundled mail, calendar, and drive connectors for a workspace suite."""

    suite: str
    mail: MailConnector
    calendar: CalendarConnector
    drive: DriveConnector


class SuiteStatus(BaseModel):
    """Configuration readiness status for a workspace suite."""

    suite: SuiteKind
    label: str
    configured: bool
    mode: str = "read-only"
    required_keys: list[str]
    missing_keys: list[str]


class ReadOnlyM365MailConnector:
    """Read-only Microsoft 365 Outlook Mail connector via Microsoft Graph."""

    def __init__(
        self,
        vault: SecretsVault,
        token_key: str = "MICROSOFT_365_TOKEN",
        http_get: HttpGetJson = _default_http_get,
    ) -> None:
        self._vault = vault
        self._token_key = token_key
        self._http_get = http_get

    def list_messages(self, *, limit: int = 10) -> list[EmailMessage]:
        token = self._vault.get_secret(self._token_key)
        if not token:
            raise ReadOnlyConnectorError(f"Missing secret '{self._token_key}'.")
        data = self._http_get(
            f"https://graph.microsoft.com/v1.0/me/messages?$top={limit}",
            token,
        )
        now = datetime.now(UTC)
        results: list[EmailMessage] = []
        for item in data.get("value", []):
            sender_info = item.get("from", {}).get("emailAddress", {})
            results.append(
                EmailMessage(
                    id=str(item.get("id", "")),
                    sender=str(sender_info.get("address", "unknown")),
                    subject=str(item.get("subject", "(No subject)")),
                    body=str(item.get("bodyPreview", "")),
                    received_at=now,
                )
            )
        return results

    def create_draft(
        self, *, in_reply_to: str, recipient: str, subject: str, body: str
    ) -> EmailDraft:
        raise ReadOnlyConnectorError(
            "Read-only Microsoft 365 connector cannot create remote drafts."
        )

    def propose_label(self, *, message_id: str, label: str) -> dict[str, str]:
        return {"message_id": message_id, "proposed_label": label}


class ReadOnlyM365CalendarConnector:
    """Read-only Microsoft 365 Calendar connector via Microsoft Graph."""

    def __init__(
        self,
        vault: SecretsVault,
        token_key: str = "MICROSOFT_365_TOKEN",
        http_get: HttpGetJson = _default_http_get,
    ) -> None:
        self._vault = vault
        self._token_key = token_key
        self._http_get = http_get

    def list_events(self, *, limit: int = 10) -> list[CalendarEvent]:
        token = self._vault.get_secret(self._token_key)
        if not token:
            raise ReadOnlyConnectorError(f"Missing secret '{self._token_key}'.")
        data = self._http_get(
            f"https://graph.microsoft.com/v1.0/me/events?$top={limit}",
            token,
        )
        now = datetime.now(UTC)
        return [
            CalendarEvent(
                id=str(item.get("id", "")),
                title=str(item.get("subject", "Untitled")),
                start_time=now,
                end_time=now,
                attendees=[
                    str(a.get("emailAddress", {}).get("address", ""))
                    for a in item.get("attendees", [])
                ],
            )
            for item in data.get("value", [])
        ]


class ReadOnlyM365DriveConnector:
    """Read-only Microsoft 365 OneDrive connector via Microsoft Graph."""

    def __init__(
        self,
        vault: SecretsVault,
        token_key: str = "MICROSOFT_365_TOKEN",
        http_get: HttpGetJson = _default_http_get,
    ) -> None:
        self._vault = vault
        self._token_key = token_key
        self._http_get = http_get

    def search_documents(self, query: str, *, limit: int = 5) -> list[DriveDocument]:
        token = self._vault.get_secret(self._token_key)
        if not token:
            raise ReadOnlyConnectorError(f"Missing secret '{self._token_key}'.")
        encoded = urllib.parse.quote(query)
        data = self._http_get(
            f"https://graph.microsoft.com/v1.0/me/drive/root/search(q='{encoded}')?$top={limit}",
            token,
        )
        return [
            DriveDocument(
                id=str(item.get("id", "")),
                title=str(item.get("name", "Untitled")),
                content="",
                url=str(item.get("webUrl", "")),
            )
            for item in data.get("value", [])
        ]


class ReadOnlyLarkMailConnector:
    """Read-only Lark Suite Mail connector via Lark Open Platform."""

    def __init__(
        self,
        vault: SecretsVault,
        token_key: str = "LARK_TENANT_ACCESS_TOKEN",
        http_get: HttpGetJson = _default_http_get,
    ) -> None:
        self._vault = vault
        self._token_key = token_key
        self._http_get = http_get

    def list_messages(self, *, limit: int = 10) -> list[EmailMessage]:
        token = self._vault.get_secret(self._token_key)
        if not token:
            raise ReadOnlyConnectorError(f"Missing secret '{self._token_key}'.")
        data = self._http_get(
            f"https://open.larksuite.com/open-apis/mail/v1/user_mailboxes/me/messages?page_size={limit}",
            token,
        )
        now = datetime.now(UTC)
        items = data.get("data", {}).get("items", [])
        return [
            EmailMessage(
                id=str(item.get("message_id", item.get("id", ""))),
                sender=str(item.get("sender", "unknown")),
                subject=str(item.get("subject", "(Lark message)")),
                body=str(item.get("body_plain_text", "")),
                received_at=now,
            )
            for item in items
        ]

    def create_draft(
        self, *, in_reply_to: str, recipient: str, subject: str, body: str
    ) -> EmailDraft:
        raise ReadOnlyConnectorError("Read-only Lark Suite connector cannot create remote drafts.")

    def propose_label(self, *, message_id: str, label: str) -> dict[str, str]:
        return {"message_id": message_id, "proposed_label": label}


class ReadOnlyLarkCalendarConnector:
    """Read-only Lark Suite Calendar connector via Lark Open Platform."""

    def __init__(
        self,
        vault: SecretsVault,
        token_key: str = "LARK_TENANT_ACCESS_TOKEN",
        http_get: HttpGetJson = _default_http_get,
    ) -> None:
        self._vault = vault
        self._token_key = token_key
        self._http_get = http_get

    def list_events(self, *, limit: int = 10) -> list[CalendarEvent]:
        token = self._vault.get_secret(self._token_key)
        if not token:
            raise ReadOnlyConnectorError(f"Missing secret '{self._token_key}'.")
        data = self._http_get(
            f"https://open.larksuite.com/open-apis/calendar/v4/calendars/primary/events?page_size={limit}",
            token,
        )
        now = datetime.now(UTC)
        items = data.get("data", {}).get("items", [])
        return [
            CalendarEvent(
                id=str(item.get("event_id", "")),
                title=str(item.get("summary", "Untitled")),
                start_time=now,
                end_time=now,
                notes=str(item.get("description", "")),
            )
            for item in items
        ]


class ReadOnlyLarkDriveConnector:
    """Read-only Lark Suite Drive connector via Lark Open Platform."""

    def __init__(
        self,
        vault: SecretsVault,
        token_key: str = "LARK_TENANT_ACCESS_TOKEN",
        http_get: HttpGetJson = _default_http_get,
    ) -> None:
        self._vault = vault
        self._token_key = token_key
        self._http_get = http_get

    def search_documents(self, query: str, *, limit: int = 5) -> list[DriveDocument]:
        token = self._vault.get_secret(self._token_key)
        if not token:
            raise ReadOnlyConnectorError(f"Missing secret '{self._token_key}'.")
        data = self._http_get(
            f"https://open.larksuite.com/open-apis/drive/v1/files?page_size={limit}",
            token,
        )
        items = data.get("data", {}).get("files", [])
        lower_q = query.lower()
        docs = [
            DriveDocument(
                id=str(item.get("token", "")),
                title=str(item.get("name", "Untitled")),
                content="",
                url=str(item.get("url", "")),
            )
            for item in items
        ]
        filtered = [d for d in docs if not lower_q or lower_q in d.title.lower()]
        return (filtered or docs)[:limit]


def build_suite_bundle(
    suite: SuiteKind,
    vault: SecretsVault,
    *,
    use_mock: bool = False,
) -> ConnectorBundle:
    """Return a ready-to-use ConnectorBundle for Google Workspace, Microsoft 365, or Lark Suite."""
    if use_mock:
        return ConnectorBundle(
            suite=f"{suite}:mock",
            mail=MockMailConnector(),
            calendar=MockCalendarConnector(),
            drive=MockDriveConnector(),
        )
    if suite == "google_workspace":
        return ConnectorBundle(
            suite=suite,
            mail=ReadOnlyGmailConnector(vault, token_key="GOOGLE_WORKSPACE_TOKEN"),
            calendar=ReadOnlyGoogleCalendarConnector(vault, token_key="GOOGLE_WORKSPACE_TOKEN"),
            drive=ReadOnlyGoogleDriveConnector(vault, token_key="GOOGLE_WORKSPACE_TOKEN"),
        )
    if suite == "microsoft_365":
        return ConnectorBundle(
            suite=suite,
            mail=ReadOnlyM365MailConnector(vault),
            calendar=ReadOnlyM365CalendarConnector(vault),
            drive=ReadOnlyM365DriveConnector(vault),
        )
    return ConnectorBundle(
        suite=suite,
        mail=ReadOnlyLarkMailConnector(vault),
        calendar=ReadOnlyLarkCalendarConnector(vault),
        drive=ReadOnlyLarkDriveConnector(vault),
    )


def get_suite_statuses(vault: SecretsVault) -> list[SuiteStatus]:
    """Check credential readiness for Google Workspace, Microsoft 365, and Lark Suite."""
    specs: list[tuple[SuiteKind, str, list[str]]] = [
        ("google_workspace", "Google Workspace", ["GOOGLE_WORKSPACE_TOKEN"]),
        ("microsoft_365", "Microsoft 365", ["MICROSOFT_365_TOKEN"]),
        ("lark_suite", "Lark Suite", ["LARK_TENANT_ACCESS_TOKEN"]),
    ]
    statuses: list[SuiteStatus] = []
    for suite, label, keys in specs:
        missing = [k for k in keys if not vault.get_secret(k)]
        statuses.append(
            SuiteStatus(
                suite=suite,
                label=label,
                configured=len(missing) == 0,
                required_keys=keys,
                missing_keys=missing,
            )
        )
    return statuses
