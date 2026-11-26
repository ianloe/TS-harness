"""Initial Phase 1 schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-22 19:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("workflow_name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("risk_tier", sa.String(8), nullable=False),
        sa.Column("data_class", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=True, unique=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cost_amount", sa.Float(), nullable=False),
        sa.Column("cost_currency", sa.String(3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tasks_workflow_name", "tasks", ["workflow_name"])
    op.create_index("ix_tasks_status", "tasks", ["status"])

    op.create_table(
        "state_checkpoints",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(64),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_id", sa.String(128), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_state_checkpoints_task_id", "state_checkpoints", ["task_id"])

    op.create_table(
        "dead_letters",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(64),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dead_letters_task_id", "dead_letters", ["task_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.String(64), nullable=False),
        sa.Column("task_id", sa.String(64), nullable=True),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("cost_amount", sa.Float(), nullable=False),
        sa.Column("cost_currency", sa.String(3), nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("entry_hash", sa.String(64), nullable=False, unique=True),
    )
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])
    op.create_index("ix_audit_logs_task_id", "audit_logs", ["task_id"])
    op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"])

    op.create_table(
        "budget_ledger",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), nullable=True),
        sa.Column("workflow_name", sa.String(128), nullable=True),
        sa.Column("model_name", sa.String(128), nullable=True),
        sa.Column("tool_name", sa.String(128), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_budget_ledger_task_id", "budget_ledger", ["task_id"])
    op.create_index("ix_budget_ledger_workflow_name", "budget_ledger", ["workflow_name"])
    op.create_index("ix_budget_ledger_created_at", "budget_ledger", ["created_at"])

    op.create_table(
        "kill_switches",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("scope", sa.String(128), nullable=False, unique=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("activated_by", sa.String(128), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_kill_switches_scope", "kill_switches", ["scope"])


def downgrade() -> None:
    op.drop_table("kill_switches")
    op.drop_table("budget_ledger")
    op.drop_table("audit_logs")
    op.drop_table("dead_letters")
    op.drop_table("state_checkpoints")
    op.drop_table("tasks")
