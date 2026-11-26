"""Tests for governance registry, FRAME/AAEF control mapping, and attestation reports."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from ts_harness.audit.logger import AuditLogger
from ts_harness.cli import app
from ts_harness.config import BudgetConfig
from ts_harness.governance.attestation import (
    generate_attestation_report,
    write_attestation_artifacts,
)
from ts_harness.governance.controls import load_control_mappings
from ts_harness.governance.registry import GovernanceRegistry


def test_registry_controls_and_attestation_generation(
    tmp_path: Path,
    session_factory: Any,
    audit_logger: AuditLogger,
    budget_config: BudgetConfig,
) -> None:
    registry = GovernanceRegistry.from_yaml(Path("governance/registry.yaml"))
    assert len(registry.entries) == 7
    assert registry.due_for_review(as_of=date(2026, 11, 22)) == []
    assert len(registry.due_for_review(as_of=date(2028, 1, 1))) == 7

    registry.record_change(actor="ianloe", target_id="inbox_triage", summary="Reviewed")
    saved_reg = tmp_path / "registry.yaml"
    registry.to_yaml(saved_reg)
    assert GovernanceRegistry.from_yaml(saved_reg).changelog[-1].target_id == "inbox_triage"

    controls = load_control_mappings(Path("governance/control_mapping.yaml"))
    assert len(controls) == 6
    assert controls[0].frame_id.startswith("FRAME-")
    assert controls[0].aaef_id.startswith("AAEF-")

    audit_logger.append(event_type="task.created", actor="user", task_id="gov-1")
    report = generate_attestation_report(
        session_factory=session_factory,
        budget_config=budget_config,
        audit_logger=audit_logger,
        registry=registry,
        controls=controls,
        period="2026-11",
    )
    assert report.audit_chain_valid is True
    assert report.controls_mapped == 6

    md_path, pdf_path = write_attestation_artifacts(report, tmp_path / "reports")
    assert md_path.exists()
    assert pdf_path.exists()
    assert "TS-Harness Monthly Governance Attestation (2026-11)" in md_path.read_text("utf-8")
    pdf_bytes = pdf_path.read_bytes()
    assert pdf_bytes.startswith(b"%PDF-1.4")
    assert b"%%EOF" in pdf_bytes


def test_cli_attest_command(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    db_file = tmp_path / "gov.db"
    cfg.write_text(f"db:\n  url: sqlite:///{db_file}\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    runner = CliRunner()
    res = runner.invoke(
        app,
        ["--config", str(cfg), "attest", "--output-dir", str(out_dir), "--period", "2026-11"],
    )
    assert res.exit_code == 0
    assert (out_dir / "2026-11-attestation.md").exists()
    assert (out_dir / "2026-11-attestation.pdf").exists()
