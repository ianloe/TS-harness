"""Read-only and draft-only connector interfaces and domain schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, Field


class EmailMessage(BaseModel):
    """Ingested email message (treated as untrusted-external data)."""

    id: str
    sender: str
    subject: str
    body: str
    received_at: datetime
    labels: list[str] = Field(default_factory=list)


class EmailDraft(BaseModel):
    """Draft email reply (T1 reversible write; never auto-sent)."""

    id: str
    in_reply_to: str
    recipient: str
    subject: str
    body: str


class CalendarEvent(BaseModel):
    """Calendar event metadata."""

    id: str
    title: str
    start_time: datetime
    end_time: datetime
    attendees: list[str] = Field(default_factory=list)
    notes: str = ""


class DriveDocument(BaseModel):
    """Document retrieved from Drive."""

    id: str
    title: str
    content: str
    url: str


class GitHubActivity(BaseModel):
    """GitHub issue or pull request summary."""

    repo: str
    number: int
    title: str
    state: str
    url: str


class WebSearchHit(BaseModel):
    """Bounded web research search hit."""

    title: str
    url: str
    snippet: str


class MailConnector(Protocol):
    """Mail connector interface (read-only + draft-only)."""

    def list_messages(self, *, limit: int = 10) -> list[EmailMessage]: ...
    def create_draft(
        self, *, in_reply_to: str, recipient: str, subject: str, body: str
    ) -> EmailDraft: ...
    def propose_label(self, *, message_id: str, label: str) -> dict[str, str]: ...


class CalendarConnector(Protocol):
    """Read-only calendar connector interface."""

    def list_events(self, *, limit: int = 10) -> list[CalendarEvent]: ...


class DriveConnector(Protocol):
    """Read-only Drive connector interface."""

    def search_documents(self, query: str, *, limit: int = 5) -> list[DriveDocument]: ...


class GitHubConnector(Protocol):
    """Read-only GitHub connector interface."""

    def list_recent_activity(self, repo: str, *, limit: int = 10) -> list[GitHubActivity]: ...


class WebResearchConnector(Protocol):
    """Read-only web search connector interface."""

    def search(self, query: str, *, limit: int = 5) -> list[WebSearchHit]: ...
