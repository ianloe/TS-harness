"""Phase 2 approvals table.

Revision ID: 0002_phase2_approvals
Revises: 0001_initial
Create Date: 2026-11-22 19:42:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase2_approvals"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), nullable=True),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("summary", sa.String(512), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("estimated_cost", sa.Float(), nullable=False),
        sa.Column("cost_currency", sa.String(3), nullable=False),
        sa.Column("reversibility", sa.String(64), nullable=False),
        sa.Column("preview_diff", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.String(128), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_approvals_task_id", "approvals", ["task_id"])
    op.create_index("ix_approvals_status", "approvals", ["status"])


def downgrade() -> None:
    op.drop_table("approvals")
