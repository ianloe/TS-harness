"""Declarative initial workflows: inbox triage, meeting prep, research digest, weekly review."""

from ts_harness.workflows.implementations import (
    build_inbox_triage_handlers,
    build_meeting_prep_handlers,
    build_research_digest_handlers,
    build_weekly_review_handlers,
)
from ts_harness.workflows.registry import WorkflowDefinition, load_workflow_definition

__all__ = [
    "WorkflowDefinition",
    "build_inbox_triage_handlers",
    "build_meeting_prep_handlers",
    "build_research_digest_handlers",
    "build_weekly_review_handlers",
    "load_workflow_definition",
]
