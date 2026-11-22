"""Data classification policies and per-task scope contracts."""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

from pydantic import BaseModel, Field

from ts_harness.core.models import DataClass


class DataClassificationPolicy(BaseModel):
    """Maps data classes to permitted model providers and tool patterns."""

    allowed_providers: dict[DataClass, list[str]] = Field(
        default_factory=lambda: {
            DataClass.PUBLIC: ["anthropic", "openai", "gemini", "ollama"],
            DataClass.INTERNAL: ["anthropic", "openai", "gemini", "ollama"],
            DataClass.CONFIDENTIAL: ["anthropic", "ollama"],
            DataClass.PERSONAL: ["anthropic", "ollama"],
        }
    )
    allowed_tools: dict[DataClass, list[str]] = Field(
        default_factory=lambda: {
            DataClass.PUBLIC: ["*"],
            DataClass.INTERNAL: ["*"],
            DataClass.CONFIDENTIAL: ["read_*", "draft_*", "note_*", "verify_*"],
            DataClass.PERSONAL: ["read_*", "draft_*", "note_*", "calendar_*", "label_*"],
        }
    )

    def is_provider_allowed(self, data_class: DataClass, provider: str) -> bool:
        """Return True if the provider may process data of this classification."""
        return provider.lower() in [p.lower() for p in self.allowed_providers.get(data_class, [])]

    def is_tool_allowed(self, data_class: DataClass, tool_name: str) -> bool:
        """Return True if the tool may operate on data of this classification."""
        patterns = self.allowed_tools.get(data_class, [])
        return any(fnmatch(tool_name, pat) for pat in patterns)


class ScopeContract(BaseModel):
    """Per-task resource boundaries for folders, mailboxes, and projects."""

    allowed_folders: list[str] = Field(default_factory=list)
    allowed_mailboxes: list[str] = Field(default_factory=list)
    allowed_projects: list[str] = Field(default_factory=list)

    def is_folder_allowed(self, folder: str) -> bool:
        """Verify that ``folder`` resolves within one of ``allowed_folders``."""
        if not self.allowed_folders:
            return False
        target = Path(folder).resolve()
        for allowed in self.allowed_folders:
            base = Path(allowed).resolve()
            if target == base or base in target.parents:
                return True
        return False

    def is_mailbox_allowed(self, mailbox: str) -> bool:
        """Verify that ``mailbox`` is in ``allowed_mailboxes``."""
        return mailbox.lower() in [m.lower() for m in self.allowed_mailboxes]

    def is_project_allowed(self, project: str) -> bool:
        """Verify that ``project`` is in ``allowed_projects``."""
        return project in self.allowed_projects
