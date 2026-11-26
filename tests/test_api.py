"""Tests for the FastAPI web interface and configuration API."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ts_harness.api.app import create_app


def test_api_health_dashboard_config_secrets_and_killswitch(tmp_path: Path) -> None:
    cfg_path = tmp_path / "settings.yaml"
    db_path = tmp_path / "api.db"
    data_dir = tmp_path / "data"
    cfg_path.write_text(
        f"environment: test\ndata_dir: {data_dir}\ndb:\n  url: sqlite:///{db_path}\n",
        encoding="utf-8",
    )

    app = create_app(config_path=cfg_path)
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    home = client.get("/")
    assert home.status_code == 200
    assert "TS-Harness Control" in home.text

    manual = client.get("/manual")
    assert manual.status_code == 200
    assert "TS-Harness User Manual" in manual.text

    logo = client.get("/assets/logo.jpg")
    assert logo.status_code == 200
    assert logo.headers["content-type"].startswith("image/jpeg")

    # Update models and budget via /api/config
    update_res = client.post(
        "/api/config",
        json={
            "environment": "staging",
            "models": {
                "planner": {"provider": "openai", "model_name": "gpt-4o"},
                "executor": {"provider": "anthropic", "model_name": "claude-sonnet-4-20250514"},
                "verifier": {"provider": "gemini", "model_name": "gemini-2.5-flash"},
            },
            "budget": {
                "currency": "USD",
                "task_limit": 3.0,
                "workflow_limit": 12.0,
                "daily_limit": 30.0,
                "monthly_limit": 250.0,
                "preflight_approval_threshold": 2.0,
            },
        },
    )
    assert update_res.status_code == 200

    # Reject unsupported currency
    bad_currency = client.post("/api/config", json={"budget": {"currency": "EUR"}})
    assert bad_currency.status_code == 422

    # Store and mask secret; verify raw secret never leaks in GET /api/config
    sec_res = client.post(
        "/api/secrets",
        json={"key": "ANTHROPIC_API_KEY", "value": "sk-ant-super-secret-5678"},
    )
    assert sec_res.status_code == 200

    cfg_res = client.get("/api/config")
    assert cfg_res.status_code == 200
    body = cfg_res.json()
    assert body["settings"]["environment"] == "staging"
    assert body["settings"]["budget"]["currency"] == "USD"
    assert body["settings"]["models"]["planner"]["provider"] == "openai"
    assert "sk-ant-super-secret-5678" not in cfg_res.text

    # Delete secret
    del_res = client.delete("/api/secrets/ANTHROPIC_API_KEY")
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True

    # Kill switch toggle
    ks_on = client.post("/api/killswitch/pause-all", json={"reason": "test"})
    assert ks_on.status_code == 200
    status = client.get("/api/status").json()
    assert len(status["active_kill_switches"]) == 1

    ks_off = client.post("/api/killswitch/resume-all")
    assert ks_off.status_code == 200
    assert ks_off.json()["resumed"] is True

    # Interactive chat: workflow routing + T3 block + kill switch block
    chat_ok = client.post(
        "/api/chat",
        json={"message": "Triage my morning inbox", "suite": "mock"},
    )
    assert chat_ok.status_code == 200
    assert chat_ok.json()["workflow_name"] == "inbox_triage"
    assert chat_ok.json()["verified"] is True

    chat_t3 = client.post(
        "/api/chat",
        json={"message": "Make a wire transfer payment of 500 SGD", "suite": "mock"},
    )
    assert chat_t3.status_code == 200
    assert chat_t3.json()["risk_tier"] == "T3"
    assert chat_t3.json()["blocked"] is True

    client.post("/api/killswitch/pause-all", json={"reason": "halt"})
    chat_ks = client.post("/api/chat", json={"message": "Hello", "suite": "mock"})
    assert chat_ks.status_code == 503

    # Policy config, explain mode, and audit chain API
    pol_get = client.get("/api/policy")
    assert pol_get.status_code == 200
    assert "rules:" in pol_get.json()["yaml_text"]

    pol_bad = client.post("/api/policy", json={"yaml_text": "not: [valid"})
    assert pol_bad.status_code == 400

    pol_save = client.post("/api/policy", json={"preset": "relaxed"})
    assert pol_save.status_code == 200
    assert pol_save.json()["name"] == "relaxed-personal"

    pol_exp = client.post(
        "/api/policy/explain",
        json={"tool_name": "wire_transfer", "risk_tier": "T3", "trust_level": "user"},
    )
    assert pol_exp.status_code == 200
    assert pol_exp.json()["decision"]["allowed"] is False

    audit_res = client.get("/api/audit?limit=10")
    assert audit_res.status_code == 200
    assert audit_res.json()["verification"]["valid"] is True
    assert len(audit_res.json()["events"]) >= 1
