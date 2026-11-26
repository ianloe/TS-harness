"""Pydantic v2 domain models for tasks, checkpoints, and dead-letter items."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from ts_harness.config import Currency


class TaskStatus(StrEnum):
    """Lifecycle states of a task."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTERED = "dead_lettered"


class RiskTier(StrEnum):
    """Action risk tiers from T0 (read-only) to T3 (forbidden)."""

    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


class DataClass(StrEnum):
    """Data sensitivity classification."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    PERSONAL = "personal"


class TaskCreate(BaseModel):
    """Input schema for creating a task."""

    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="")
    workflow_name: str = Field(min_length=1, max_length=128)
    risk_tier: RiskTier = Field(default=RiskTier.T0)
    data_class: DataClass = Field(default=DataClass.INTERNAL)
    idempotency_key: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)
    cost_currency: Currency = Field(default="SGD")


class Task(BaseModel):
    """Domain representation of a persisted task."""

    id: str
    title: str
    description: str
    workflow_name: str
    status: TaskStatus
    risk_tier: RiskTier
    data_class: DataClass
    idempotency_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error_message: str | None = None
    cost_amount: float = 0.0
    cost_currency: Currency = "SGD"
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class Checkpoint(BaseModel):
    """Saved node execution state for resume after crash or pause."""

    id: str
    task_id: str
    node_id: str
    step_index: int
    state: dict[str, Any]
    created_at: datetime


class DeadLetterItem(BaseModel):
    """Task moved to the dead-letter queue after unrecoverable failure."""

    id: str
    task_id: str
    reason: str
    payload: dict[str, Any]
    attempts: int
    created_at: datetime
