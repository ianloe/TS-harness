"""Tests for observability, FinOps reports/caching/anomalies, and CI eval suite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from ts_harness.api.app import create_app
from ts_harness.audit.logger import AuditLogger
from ts_harness.config import BudgetConfig
from ts_harness.core.models import TaskCreate, TaskStatus
from ts_harness.core.store import StateStore
from ts_harness.evals.runner import run_eval_suite
from ts_harness.finops.budget import BudgetManager
from ts_harness.finops.reports import (
    PromptCache,
    ProviderRateLimiter,
    SpendAnomalyDetector,
    build_cost_attribution_report,
)
from ts_harness.observability.tracing import (
    build_run_trace,
    collect_dashboard_metrics,
    configure_otel,
)


def test_finops_reports_cache_anomaly_and_rate_limiter(
    session_factory: Any,
    store: StateStore,
    budget_manager: BudgetManager,
) -> None:
    t1, _ = store.create_task(TaskCreate(title="T1", workflow_name="inbox_triage"))
    store.update_task_status(t1.id, TaskStatus.COMPLETED)
    budget_manager.record_spend(
        amount=0.2,
        currency="SGD",
        task_id=t1.id,
        workflow_name="inbox_triage",
        model_name="claude-sonnet",
        tool_name="read_mail",
    )

    report = build_cost_attribution_report(session_factory, "SGD")
    assert report.total_spend == 0.2
    assert report.completed_tasks == 1
    assert report.cost_per_useful_outcome == 0.2
    assert report.by_workflow["inbox_triage"] == 0.2

    cache = PromptCache(ttl_seconds=60)
    now = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)
    k = cache.make_key("plan", "hello")
    assert cache.get(k, now=now) is None
    cache.set(k, "cached_val", now=now)
    assert cache.get(k, now=now + timedelta(seconds=10)) == "cached_val"
    assert cache.get(k, now=now + timedelta(seconds=61)) is None

    detector = SpendAnomalyDetector(spike_multiplier=3.0, min_baseline_samples=3)
    for amt in (0.1, 0.1, 0.1):
        assert detector.observe(amt)[0] is False
    is_anom, reason = detector.observe(1.0)
    assert is_anom is True and reason is not None

    limiter = ProviderRateLimiter(max_rpm=2, max_concurrent=1)
    assert limiter.acquire("anthropic", now=now)[0] is True
    assert limiter.acquire("anthropic", now=now)[0] is False  # concurrency cap
    limiter.release("anthropic")
    assert limiter.acquire("anthropic", now=now)[0] is True
    limiter.release("anthropic")
    assert limiter.acquire("anthropic", now=now)[0] is False  # 2 RPM exceeded


def test_observability_traces_and_dashboard_api(
    tmp_path: Path,
    session_factory: Any,
    audit_logger: AuditLogger,
    budget_config: BudgetConfig,
) -> None:
    tracer = configure_otel(service_name="ts-harness-test", enabled=False)
    assert tracer is not None

    audit_logger.append(event_type="task.created", actor="user", task_id="t-trace", cost_amount=0.1)
    audit_logger.append(event_type="tool.denied", actor="gateway", task_id="t-trace")
    trace = build_run_trace("t-trace", audit_logger)
    assert trace.event_count == 2
    assert trace.total_cost == 0.1

    metrics = collect_dashboard_metrics(session_factory, budget_config)
    assert metrics.policy_blocks == 1

    cfg_path = tmp_path / "settings.yaml"
    db_path = tmp_path / "obs.db"
    cfg_path.write_text(f"db:\n  url: sqlite:///{db_path}\n", encoding="utf-8")
    client = TestClient(create_app(config_path=cfg_path))
    assert client.get("/api/metrics").status_code == 200
    assert client.get("/api/finops/report").status_code == 200
    assert client.get("/api/traces/t-trace").status_code == 200
    assert client.get("/api/approvals").status_code == 200


def test_eval_suite_passes_all_scenarios() -> None:
    summary = run_eval_suite()
    assert summary.total_cases == 6
    assert summary.passed_cases == 6
    assert summary.success_rate == 1.0
    assert summary.escape_rate == 0.0
    assert summary.injection_resistance_rate == 1.0
