"""Connector interfaces, mock implementations, and read-only real adapters."""

from ts_harness.connectors.interfaces import (
    CalendarConnector,
    CalendarEvent,
    DriveConnector,
    DriveDocument,
    EmailDraft,
    EmailMessage,
    GitHubActivity,
    GitHubConnector,
    MailConnector,
    WebResearchConnector,
    WebSearchHit,
)
from ts_harness.connectors.mocks import (
    LocalFilesystemConnector,
    MockCalendarConnector,
    MockDriveConnector,
    MockGitHubConnector,
    MockMailConnector,
    MockWebResearchConnector,
)
from ts_harness.connectors.readonly import (
    ReadOnlyGitHubConnector,
    ReadOnlyGmailConnector,
    ReadOnlyGoogleCalendarConnector,
    ReadOnlyGoogleDriveConnector,
)

__all__ = [
    "CalendarConnector",
    "CalendarEvent",
    "DriveConnector",
    "DriveDocument",
    "EmailDraft",
    "EmailMessage",
    "GitHubActivity",
    "GitHubConnector",
    "LocalFilesystemConnector",
    "MailConnector",
    "MockCalendarConnector",
    "MockDriveConnector",
    "MockGitHubConnector",
    "MockMailConnector",
    "MockWebResearchConnector",
    "ReadOnlyGitHubConnector",
    "ReadOnlyGmailConnector",
    "ReadOnlyGoogleCalendarConnector",
    "ReadOnlyGoogleDriveConnector",
    "WebResearchConnector",
    "WebSearchHit",
]
