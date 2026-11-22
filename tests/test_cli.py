"""Tests for the Typer CLI."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from ts_harness.cli import app

runner = CliRunner()


def test_cli_init_status_killswitch_and_audit(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    db_file = tmp_path / "cli.db"
    cfg.write_text(f"db:\n  url: sqlite:///{db_file}\n", encoding="utf-8")

    res_init = runner.invoke(app, ["--config", str(cfg), "db", "init"])
    assert res_init.exit_code == 0

    res_pause = runner.invoke(
        app, ["--config", str(cfg), "killswitch", "pause-all", "--reason", "drill"]
    )
    assert res_pause.exit_code == 0
    assert "Global kill switch activated" in res_pause.stdout

    res_status = runner.invoke(app, ["--config", str(cfg), "status"])
    assert res_status.exit_code == 0
    assert "Active Kill Switches: 1" in res_status.stdout

    res_audit = runner.invoke(app, ["--config", str(cfg), "audit", "verify"])
    assert res_audit.exit_code == 0
    assert "Audit chain valid" in res_audit.stdout

    res_resume = runner.invoke(app, ["--config", str(cfg), "killswitch", "resume-all"])
    assert res_resume.exit_code == 0
