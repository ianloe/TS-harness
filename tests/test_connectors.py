"""Tests for mock connectors, scope-enforced filesystem, and read-only real adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from ts_harness.connectors.mocks import (
    LocalFilesystemConnector,
    MockCalendarConnector,
    MockDriveConnector,
    MockGitHubConnector,
    MockMailConnector,
    MockWebResearchConnector,
)
from ts_harness.connectors.readonly import (
    ReadOnlyConnectorError,
    ReadOnlyGitHubConnector,
    ReadOnlyGmailConnector,
    ReadOnlyGoogleCalendarConnector,
    ReadOnlyGoogleDriveConnector,
)
from ts_harness.security.classification import ScopeContract
from ts_harness.security.vault import SecretsVault


def test_mock_connectors_and_scoped_filesystem(tmp_path: Path) -> None:
    mail = MockMailConnector()
    msgs = mail.list_messages()
    assert len(msgs) == 2
    draft = mail.create_draft(
        in_reply_to="msg-1",
        recipient="alice@company.com",
        subject="Re: Q4",
        body="Draft",
    )
    assert draft.recipient == "alice@company.com"

    assert len(MockCalendarConnector().list_events()) == 1
    assert len(MockDriveConnector().search_documents("Q4")) == 1
    assert len(MockGitHubConnector().list_recent_activity("ianloe/TS-harness")) == 1
    assert len(MockWebResearchConnector().search("LLM")) == 2

    allowed_dir = tmp_path / "notes"
    allowed_dir.mkdir()
    note_file = allowed_dir / "agenda.md"
    note_file.write_text("# Agenda", encoding="utf-8")

    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("TOP SECRET", encoding="utf-8")

    fs = LocalFilesystemConnector(ScopeContract(allowed_folders=[str(allowed_dir)]))
    assert fs.read_file(str(note_file)) == "# Agenda"
    assert fs.list_files(str(allowed_dir)) == [str(note_file.resolve())]
    with pytest.raises(PermissionError):
        fs.read_file(str(outside_file))


def test_readonly_connectors_require_credentials(tmp_path: Path) -> None:
    vault = SecretsVault(tmp_path / ".secrets.json")
    with pytest.raises(ReadOnlyConnectorError):
        ReadOnlyGmailConnector(vault).list_messages()
    with pytest.raises(ReadOnlyConnectorError):
        ReadOnlyGoogleCalendarConnector(vault).list_events()
    with pytest.raises(ReadOnlyConnectorError):
        ReadOnlyGoogleDriveConnector(vault).search_documents("test")
    with pytest.raises(ReadOnlyConnectorError):
        ReadOnlyGitHubConnector(vault).list_recent_activity("ianloe/TS-harness")
