"""Shared pytest fixtures for TS-harness."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from ts_harness.audit.logger import AuditLogger
from ts_harness.config import BudgetConfig
from ts_harness.core.store import StateStore
from ts_harness.db.base import create_db_engine, create_session_factory, init_db
from ts_harness.finops.budget import BudgetManager
from ts_harness.killswitch.manager import KillSwitchManager


@pytest.fixture()
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    """Create an isolated temporary SQLite database per test."""
    db_path = tmp_path / "test_harness.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    init_db(engine)
    return create_session_factory(engine)


@pytest.fixture()
def store(session_factory: sessionmaker[Session]) -> StateStore:
    return StateStore(session_factory)


@pytest.fixture()
def audit_logger(session_factory: sessionmaker[Session]) -> AuditLogger:
    return AuditLogger(session_factory)


@pytest.fixture()
def budget_config() -> BudgetConfig:
    return BudgetConfig(
        currency="SGD",
        task_limit=2.0,
        workflow_limit=5.0,
        daily_limit=10.0,
        monthly_limit=50.0,
        soft_limit_pct=0.75,
        hard_limit_pct=1.0,
        preflight_approval_threshold=1.0,
    )


@pytest.fixture()
def budget_manager(
    session_factory: sessionmaker[Session],
    budget_config: BudgetConfig,
) -> BudgetManager:
    return BudgetManager(session_factory, budget_config)


@pytest.fixture()
def kill_switch(
    session_factory: sessionmaker[Session],
    audit_logger: AuditLogger,
) -> KillSwitchManager:
    return KillSwitchManager(session_factory, audit_logger)
