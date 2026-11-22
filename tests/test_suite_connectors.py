"""Tests for Google Workspace, Microsoft 365, and Lark Suite connector bundles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ts_harness.api.app import create_app
from ts_harness.connectors.readonly import ReadOnlyConnectorError
from ts_harness.connectors.suites import (
    ReadOnlyLarkCalendarConnector,
    ReadOnlyLarkDriveConnector,
    ReadOnlyLarkMailConnector,
    ReadOnlyM365CalendarConnector,
    ReadOnlyM365DriveConnector,
    ReadOnlyM365MailConnector,
    build_suite_bundle,
    get_suite_statuses,
)
from ts_harness.security.vault import SecretsVault


def test_suite_bundle_mock_and_readonly_factory(tmp_path: Path) -> None:
    vault = SecretsVault(tmp_path / ".secrets.json")

    mock_bundle = build_suite_bundle("microsoft_365", vault, use_mock=True)
    assert len(mock_bundle.mail.list_messages()) == 2
    assert len(mock_bundle.calendar.list_events()) == 1
    assert len(mock_bundle.drive.search_documents("Q4")) == 1

    for suite in ("google_workspace", "microsoft_365", "lark_suite"):
        bundle = build_suite_bundle(suite, vault)  # type: ignore[arg-type]
        with pytest.raises(ReadOnlyConnectorError):
            bundle.mail.list_messages()


def test_m365_and_lark_connectors_parse_responses(tmp_path: Path) -> None:
    vault = SecretsVault(tmp_path / ".secrets.json")
    vault.set_secret("MICROSOFT_365_TOKEN", "m365-token-1234")
    vault.set_secret("LARK_TENANT_ACCESS_TOKEN", "lark-token-1234")

    def fake_m365_get(url: str, token: str) -> dict[str, Any]:
        if "/messages" in url:
            return {
                "value": [
                    {
                        "id": "m1",
                        "subject": "M365 Agenda",
                        "bodyPreview": "Please review.",
                        "from": {"emailAddress": {"address": "bob@contoso.com"}},
                    }
                ]
            }
        if "/events" in url:
            return {
                "value": [
                    {
                        "id": "e1",
                        "subject": "Sync",
                        "attendees": [{"emailAddress": {"address": "bob@contoso.com"}}],
                    }
                ]
            }
        return {"value": [{"id": "d1", "name": "Q4 Plan.docx", "webUrl": "https://onedrive/d1"}]}

    m365_mail = ReadOnlyM365MailConnector(vault, http_get=fake_m365_get)
    m365_cal = ReadOnlyM365CalendarConnector(vault, http_get=fake_m365_get)
    m365_drive = ReadOnlyM365DriveConnector(vault, http_get=fake_m365_get)

    assert m365_mail.list_messages()[0].sender == "bob@contoso.com"
    assert m365_cal.list_events()[0].title == "Sync"
    assert m365_drive.search_documents("Q4")[0].title == "Q4 Plan.docx"

    def fake_lark_get(url: str, token: str) -> dict[str, Any]:
        if "/mail/" in url:
            return {
                "data": {
                    "items": [
                        {
                            "message_id": "lm1",
                            "sender": "lin@lark.example",
                            "subject": "Lark Update",
                            "body_plain_text": "All on track.",
                        }
                    ]
                }
            }
        if "/calendar/" in url:
            return {"data": {"items": [{"event_id": "le1", "summary": "Lark Standup"}]}}
        return {"data": {"files": [{"token": "lf1", "name": "OKRs.md", "url": "https://lark/lf1"}]}}

    lark_mail = ReadOnlyLarkMailConnector(vault, http_get=fake_lark_get)
    lark_cal = ReadOnlyLarkCalendarConnector(vault, http_get=fake_lark_get)
    lark_drive = ReadOnlyLarkDriveConnector(vault, http_get=fake_lark_get)

    assert lark_mail.list_messages()[0].subject == "Lark Update"
    assert lark_cal.list_events()[0].title == "Lark Standup"
    assert lark_drive.search_documents("OKR")[0].title == "OKRs.md"

    statuses = {s.suite: s for s in get_suite_statuses(vault)}
    assert statuses["microsoft_365"].configured is True
    assert statuses["lark_suite"].configured is True
    assert statuses["google_workspace"].configured is False


def test_api_connectors_status_endpoint(tmp_path: Path) -> None:
    cfg_path = tmp_path / "settings.yaml"
    db_path = tmp_path / "conn.db"
    data_dir = tmp_path / "data"
    cfg_path.write_text(
        f"data_dir: {data_dir}\ndb:\n  url: sqlite:///{db_path}\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(config_path=cfg_path))
    res = client.get("/api/connectors/status")
    assert res.status_code == 200
    suites = {item["suite"]: item for item in res.json()}
    assert set(suites.keys()) == {"google_workspace", "microsoft_365", "lark_suite"}
