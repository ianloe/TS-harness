"""FastAPI application for status, configuration, secrets vault, and kill switch."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from ts_harness import __version__
from ts_harness.agents.models import ModelProviderError, VaultModelClient
from ts_harness.agents.roles import ExecutionReport, PlannerAgent, VerifierAgent
from ts_harness.api.manual import MANUAL_HTML
from ts_harness.api.ui import DASHBOARD_HTML
from ts_harness.approvals.queue import ApprovalQueue
from ts_harness.audit.logger import AuditLogger
from ts_harness.config import (
    BudgetConfig,
    LoggingConfig,
    ModelsConfig,
    Settings,
    TelemetryConfig,
    load_settings,
    resolve_config_path,
    save_settings,
)
from ts_harness.connectors.documents import DocumentStore, DocumentValidationError
from ts_harness.connectors.google_oauth import (
    build_google_auth_url,
    exchange_code_for_tokens,
    refresh_google_access_token,
)
from ts_harness.connectors.mocks import MockWebResearchConnector
from ts_harness.connectors.readonly import ReadOnlyConnectorError
from ts_harness.connectors.suites import SuiteKind, build_suite_bundle, get_suite_statuses
from ts_harness.core.models import RiskTier, TaskCreate
from ts_harness.core.store import StateStore
from ts_harness.db.base import create_db_engine, create_session_factory, init_db
from ts_harness.finops.budget import BudgetManager
from ts_harness.finops.reports import build_cost_attribution_report
from ts_harness.gateway.gateway import ToolGateway
from ts_harness.graph.engine import GraphRunner
from ts_harness.guardrails.filters import redact_pii_and_secrets
from ts_harness.killswitch.manager import KillSwitchManager
from ts_harness.observability.tracing import build_run_trace, collect_dashboard_metrics
from ts_harness.policy.engine import PolicyEngine
from ts_harness.policy.schema import PolicyRule, PolicySet, RuleEffect, RuleMatch
from ts_harness.router.router import TaskRouter
from ts_harness.security.vault import SecretStatus, SecretsVault
from ts_harness.workflows.implementations import (
    build_inbox_triage_handlers,
    build_meeting_prep_handlers,
    build_research_digest_handlers,
    build_weekly_review_handlers,
)
from ts_harness.workflows.registry import load_workflow_definition


class ConfigUpdateRequest(BaseModel):
    """Validated payload for updating non-secret harness configuration."""

    environment: str | None = None
    models: ModelsConfig | None = None
    budget: BudgetConfig | None = None
    telemetry: TelemetryConfig | None = None
    logging: LoggingConfig | None = None


class SecretUpdateRequest(BaseModel):
    """Validated payload for storing a secret in the vault."""

    key: str = Field(min_length=3, max_length=64)
    value: str = Field(min_length=1)


class KillSwitchActionRequest(BaseModel):
    """Optional reason for activating a kill switch."""

    reason: str = Field(default="Manual action via web UI")


class ChatRequest(BaseModel):
    """Interactive chat request routed through TS-Harness guardrails."""

    message: str = Field(min_length=1, max_length=4000)
    suite: str = Field(default="mock")


def _format_workflow_reply(wf_name: str, state: dict[str, Any]) -> str:
    if wf_name == "inbox_triage":
        lines = [str(state.get("summary", "Inbox triage completed."))]
        for item in state.get("summaries", [])[:5]:
            flag = " [SUSPICIOUS]" if item.get("suspicious") else ""
            subj = item.get("subject", "(No subject)")
            lines.append(f"- {subj} | From: {item.get('sender')}{flag}")
        drafts = state.get("drafts", [])
        if drafts:
            lines.append(f"\nDrafts prepared ({len(drafts)}, local draft-only):")
            for d in drafts[:3]:
                lines.append(f"  To: {d.get('recipient')} | {d.get('subject')}\n  {d.get('body')}")
        return "\n".join(lines)
    if wf_name == "meeting_prep":
        briefs = state.get("briefs", [])
        if briefs:
            return "\n\n".join(
                f"Meeting: {b.get('meeting')}\nAttendees: {', '.join(b.get('attendees', []))}\n"
                f"{b.get('brief')}"
                for b in briefs
            )
    if wf_name == "research_digest":
        return str(state.get("digest_text") or "Research digest completed.")
    if wf_name == "weekly_review":
        return str(state.get("report_text") or "Weekly review completed.")
    return str(state.get("summary") or "Workflow completed.")


def _resolve_repo_path(relative: str) -> Path:
    cwd_path = Path(relative)
    if cwd_path.exists():
        return cwd_path
    return Path(__file__).resolve().parents[3] / relative


def _default_logo_path() -> Path:
    pkg_logo = Path(__file__).resolve().parent / "assets" / "ts-harness-logo.jpg"
    if pkg_logo.exists():
        return pkg_logo
    return Path(__file__).resolve().parents[3] / "docs" / "assets" / "ts-harness-logo.jpg"


def create_app(
    *,
    config_path: Path | None = None,
    logo_path: Path | None = None,
) -> FastAPI:
    """Create a FastAPI app with dependency-injected state (no global mutable state)."""
    resolved_config_path = resolve_config_path(config_path)
    settings = load_settings(resolved_config_path)

    engine = create_db_engine(settings.db.url, echo=settings.db.echo)
    init_db(engine)
    session_factory = create_session_factory(engine)
    audit_logger = AuditLogger(session_factory)
    kill_switch = KillSwitchManager(session_factory, audit_logger)
    approval_queue = ApprovalQueue(session_factory, audit_logger)
    store = StateStore(session_factory)

    target_config_path = (
        resolved_config_path
        if resolved_config_path is not None
        else Path(settings.data_dir) / "settings.yaml"
    )
    vault = SecretsVault(Path(settings.data_dir) / ".secrets.json")
    doc_store = DocumentStore(Path(settings.data_dir) / "documents")
    resolved_logo = logo_path or _default_logo_path()
    oauth_states: set[str] = set()

    app = FastAPI(title="TS-Harness API", version=__version__)

    def _current_settings() -> Settings:
        if target_config_path.exists():
            return load_settings(target_config_path)
        return settings

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return DASHBOARD_HTML

    @app.get("/manual", response_class=HTMLResponse)
    def manual() -> str:
        return MANUAL_HTML

    @app.get("/assets/logo.jpg")
    def logo() -> FileResponse:
        if not resolved_logo.exists():
            raise HTTPException(status_code=404, detail="Logo not found")
        return FileResponse(resolved_logo, media_type="image/jpeg")

    @app.get("/api/status")
    def get_status() -> dict[str, Any]:
        cfg = _current_settings()
        budget_mgr = BudgetManager(session_factory, cfg.budget)
        summary = budget_mgr.get_spend_summary()
        chain = audit_logger.verify_chain()
        switches = kill_switch.list_states(active_only=True)
        return {
            "environment": cfg.environment,
            "audit_chain_valid": chain.valid,
            "audit_entries": chain.checked_count,
            "active_kill_switches": [s.model_dump(mode="json") for s in switches],
            "currency": summary.currency,
            "daily_spend": summary.daily_spend,
            "daily_limit": summary.daily_limit,
            "monthly_spend": summary.monthly_spend,
            "monthly_limit": summary.monthly_limit,
        }

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        cfg = _current_settings()
        secrets: list[SecretStatus] = vault.list_statuses()
        return {
            "settings": {
                "environment": cfg.environment,
                "data_dir": cfg.data_dir,
                "models": cfg.models.model_dump(mode="json"),
                "budget": cfg.budget.model_dump(mode="json"),
                "telemetry": cfg.telemetry.model_dump(mode="json"),
                "logging": cfg.logging.model_dump(mode="json"),
            },
            "secrets": [s.model_dump(mode="json") for s in secrets],
        }

    @app.post("/api/config")
    def update_config(payload: ConfigUpdateRequest) -> dict[str, Any]:
        cfg = _current_settings()
        updated_data = cfg.model_dump()
        if payload.environment is not None:
            updated_data["environment"] = payload.environment
        if payload.models is not None:
            updated_data["models"] = payload.models.model_dump()
        if payload.budget is not None:
            updated_data["budget"] = payload.budget.model_dump()
        if payload.telemetry is not None:
            updated_data["telemetry"] = payload.telemetry.model_dump()
        if payload.logging is not None:
            updated_data["logging"] = payload.logging.model_dump()

        new_settings = Settings(**updated_data)
        save_settings(new_settings, target_config_path)
        audit_logger.append(
            event_type="config.updated",
            actor="web_ui",
            payload={
                "environment": new_settings.environment,
                "currency": new_settings.budget.currency,
                "planner_model": new_settings.models.planner.model_name,
                "executor_model": new_settings.models.executor.model_name,
                "verifier_model": new_settings.models.verifier.model_name,
            },
        )
        return {"status": "saved", "config_path": str(target_config_path)}

    @app.post("/api/secrets")
    def update_secret(payload: SecretUpdateRequest) -> dict[str, str]:
        try:
            vault.set_secret(payload.key, payload.value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        audit_logger.append(
            event_type="secret.updated",
            actor="web_ui",
            payload={"key": payload.key, "action": "set"},
        )
        return {"status": "saved", "key": payload.key}

    @app.delete("/api/secrets/{key_name}")
    def delete_secret(key_name: str) -> dict[str, Any]:
        try:
            deleted = vault.delete_secret(key_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if deleted:
            audit_logger.append(
                event_type="secret.deleted",
                actor="web_ui",
                payload={"key": key_name},
            )
        return {"deleted": deleted, "key": key_name}

    @app.post("/api/killswitch/pause-all")
    def pause_all(payload: KillSwitchActionRequest) -> dict[str, Any]:
        state = kill_switch.pause_all(reason=payload.reason, actor="web_ui")
        return state.model_dump(mode="json")

    @app.post("/api/killswitch/resume-all")
    def resume_all() -> dict[str, Any]:
        state = kill_switch.resume_all(actor="web_ui")
        return {"resumed": state is not None}

    @app.get("/api/metrics")
    def get_metrics() -> dict[str, Any]:
        cfg = _current_settings()
        return collect_dashboard_metrics(session_factory, cfg.budget).model_dump(mode="json")

    @app.get("/api/finops/report")
    def get_finops_report() -> dict[str, Any]:
        cfg = _current_settings()
        return build_cost_attribution_report(
            session_factory, cfg.budget.currency
        ).model_dump(mode="json")

    @app.get("/api/traces/{task_id}")
    def get_trace(task_id: str) -> dict[str, Any]:
        return build_run_trace(task_id, audit_logger).model_dump(mode="json")

    @app.get("/api/approvals")
    def list_approvals() -> list[dict[str, Any]]:
        return [a.model_dump(mode="json") for a in approval_queue.list_pending()]

    @app.post("/api/approvals/{approval_id}/approve")
    def approve_item(approval_id: str) -> dict[str, Any]:
        try:
            req = approval_queue.approve(approval_id, actor="web_ui")
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return req.model_dump(mode="json")

    @app.post("/api/approvals/{approval_id}/reject")
    def reject_item(approval_id: str, payload: KillSwitchActionRequest) -> dict[str, Any]:
        try:
            req = approval_queue.reject(approval_id, reason=payload.reason, actor="web_ui")
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return req.model_dump(mode="json")

    @app.get("/api/connectors/status")
    def connectors_status() -> list[dict[str, Any]]:
        return [s.model_dump(mode="json") for s in get_suite_statuses(vault)]

    @app.get("/api/connectors/google/start")
    def google_oauth_start(request: Request) -> RedirectResponse:
        client_id = vault.get_secret("GOOGLE_CLIENT_ID")
        client_secret = vault.get_secret("GOOGLE_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Save GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in the Secrets Vault first."
                ),
            )
        state = secrets.token_urlsafe(24)
        oauth_states.add(state)
        redirect_uri = str(request.url_for("google_oauth_callback"))
        url = build_google_auth_url(client_id=client_id, redirect_uri=redirect_uri, state=state)
        return RedirectResponse(url=url, status_code=302)

    @app.get("/api/connectors/google/callback", name="google_oauth_callback")
    def google_oauth_callback(
        request: Request,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
    ) -> RedirectResponse:
        if error:
            raise HTTPException(status_code=400, detail=f"Google OAuth error: {error}")
        if not state or state not in oauth_states:
            raise HTTPException(status_code=400, detail="Invalid or expired OAuth state.")
        oauth_states.discard(state)
        if not code:
            raise HTTPException(status_code=400, detail="Missing authorization code.")

        client_id = vault.get_secret("GOOGLE_CLIENT_ID")
        client_secret = vault.get_secret("GOOGLE_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise HTTPException(status_code=400, detail="Missing Google client credentials.")

        redirect_uri = str(request.url_for("google_oauth_callback"))
        tokens = exchange_code_for_tokens(
            code=code,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )
        access_token = str(tokens.get("access_token", "")).strip()
        refresh_token = str(tokens.get("refresh_token", "")).strip()
        if not access_token:
            raise HTTPException(status_code=400, detail="Google did not return an access_token.")
        vault.set_secret("GOOGLE_WORKSPACE_TOKEN", access_token)
        if refresh_token:
            vault.set_secret("GOOGLE_REFRESH_TOKEN", refresh_token)

        audit_logger.append(
            event_type="google.oauth_connected",
            actor="web_ui",
            payload={"scopes": ["gmail.readonly", "calendar.readonly", "drive.readonly"]},
        )
        return RedirectResponse(url="/?oauth=google_connected", status_code=302)

    @app.post("/api/connectors/google/refresh")
    def google_oauth_refresh() -> dict[str, str]:
        try:
            refresh_google_access_token(vault)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_logger.append(
            event_type="google.oauth_refreshed",
            actor="web_ui",
            payload={"status": "refreshed"},
        )
        return {"status": "refreshed"}

    @app.get("/api/documents")
    def list_documents() -> list[dict[str, Any]]:
        return [d.model_dump(mode="json") for d in doc_store.list_documents()]

    @app.post("/api/documents/upload")
    async def upload_document(file: UploadFile = File(...)) -> dict[str, Any]:
        raw = await file.read()
        try:
            meta = doc_store.save_upload(file.filename or "upload.md", raw)
        except DocumentValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_logger.append(
            event_type="document.uploaded",
            actor="web_ui",
            payload={
                "name": meta.name,
                "size_bytes": meta.size_bytes,
                "suspicious": meta.suspicious,
            },
        )
        return meta.model_dump(mode="json")

    @app.get("/api/documents/{filename}/text")
    def read_document_text(filename: str) -> dict[str, Any]:
        try:
            extracted = doc_store.read_quarantined(filename)
        except (DocumentValidationError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return extracted.model_dump(mode="json")

    @app.get("/api/documents/{filename}/download")
    def download_document(filename: str) -> FileResponse:
        try:
            path = doc_store.get_download_path(filename)
        except (DocumentValidationError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        audit_logger.append(
            event_type="document.downloaded",
            actor="web_ui",
            payload={"name": path.name},
        )
        media_type = "application/pdf" if path.suffix.lower() == ".pdf" else "text/markdown"
        return FileResponse(path, media_type=media_type, filename=path.name)

    @app.post("/api/chat")
    def chat_with_harness(payload: ChatRequest) -> dict[str, Any]:
        cfg = _current_settings()
        blocked, block_reason = kill_switch.is_blocked()
        if blocked:
            raise HTTPException(status_code=503, detail=block_reason or "Kill switch active.")

        safe_msg = redact_pii_and_secrets(payload.message).text
        router = TaskRouter(models=cfg.models, currency=cfg.budget.currency)
        classification = router.classify(safe_msg)

        if classification.risk_tier == RiskTier.T3:
            audit_logger.append(
                event_type="chat.blocked_t3",
                actor="web_ui",
                payload={"message": safe_msg, "workflow": classification.workflow_name},
            )
            return {
                "reply": (
                    "Blocked (T3 Forbidden): Payments, trading, credential entry, and "
                    "security setting changes are permanently prohibited."
                ),
                "workflow_name": classification.workflow_name,
                "risk_tier": RiskTier.T3.value,
                "data_class": classification.data_class.value,
                "verified": False,
                "cost_amount": 0.0,
                "currency": cfg.budget.currency,
                "blocked": True,
            }

        budget_mgr = BudgetManager(session_factory, cfg.budget)
        b_status = budget_mgr.check_budget(
            workflow_name=classification.workflow_name,
            estimated_cost=classification.estimated_cost,
        )
        if not b_status.allowed:
            raise HTTPException(status_code=402, detail=b_status.reason or "Budget limit reached.")

        task, _ = store.create_task(
            TaskCreate(
                title=safe_msg[:80],
                description=safe_msg,
                workflow_name=classification.workflow_name,
                risk_tier=classification.risk_tier,
                data_class=classification.data_class,
                cost_currency=cfg.budget.currency,
            )
        )

        policy_path = _resolve_repo_path("policies/strict.yaml")
        if policy_path.exists():
            policy_engine = PolicyEngine.from_yaml(policy_path)
        else:
            policy_engine = PolicyEngine(
                PolicySet(
                    version="1.0",
                    name="chat-default",
                    rules=[
                        PolicyRule(
                            id="allow-t0-t1",
                            effect=RuleEffect.ALLOW,
                            match=RuleMatch(action_tiers=[RiskTier.T0, RiskTier.T1]),
                        )
                    ],
                )
            )

        gateway = ToolGateway(
            audit_logger=audit_logger,
            budget_manager=budget_mgr,
            kill_switch=kill_switch,
            policy_checker=policy_engine,
            currency=cfg.budget.currency,
        )
        runner = GraphRunner(
            store=store,
            audit_logger=audit_logger,
            budget_manager=budget_mgr,
            kill_switch=kill_switch,
            approval_queue=approval_queue,
            currency=cfg.budget.currency,
        )
        client = VaultModelClient(vault=vault, currency=cfg.budget.currency)
        planner = PlannerAgent(
            model_client=client,
            role_config=classification.models.planner,
            budget_manager=budget_mgr,
        )
        verifier = VerifierAgent(
            model_client=client,
            role_config=classification.models.verifier,
            budget_manager=budget_mgr,
        )

        use_mock = payload.suite == "mock"
        suite_kind: SuiteKind = (
            payload.suite  # type: ignore[assignment]
            if payload.suite in {"google_workspace", "microsoft_365", "lark_suite"}
            else "google_workspace"
        )
        bundle = build_suite_bundle(suite_kind, vault, use_mock=use_mock)

        wf_dir = _resolve_repo_path("workflows")
        wf_name = classification.workflow_name
        try:
            if wf_name in {"inbox_triage", "meeting_prep", "research_digest", "weekly_review"} and (
                wf_dir / f"{wf_name}.yaml"
            ).exists():
                wf = load_workflow_definition(wf_dir / f"{wf_name}.yaml")
                if wf_name == "inbox_triage":
                    handlers = build_inbox_triage_handlers(
                        mail=bundle.mail, gateway=gateway, planner=planner, verifier=verifier
                    )
                elif wf_name == "meeting_prep":
                    handlers = build_meeting_prep_handlers(
                        calendar=bundle.calendar,
                        drive=bundle.drive,
                        gateway=gateway,
                        planner=planner,
                        verifier=verifier,
                    )
                elif wf_name == "research_digest":
                    handlers = build_research_digest_handlers(
                        web=MockWebResearchConnector(),
                        gateway=gateway,
                        planner=planner,
                        verifier=verifier,
                    )
                else:
                    handlers = build_weekly_review_handlers(
                        store=store,
                        budget_manager=budget_mgr,
                        approval_queue=approval_queue,
                        planner=planner,
                        verifier=verifier,
                    )
                run_res = runner.run(wf.graph, task, handlers)
                reply = _format_workflow_reply(wf_name, run_res.state)
                verified = bool(run_res.state.get("verification", {}).get("passed", True))
            else:
                plan = planner.plan(safe_msg, task_id=task.id, workflow_name=wf_name)
                ver = verifier.verify(
                    safe_msg,
                    ExecutionReport(output_text=plan.rationale),
                    task_id=task.id,
                    workflow_name=wf_name,
                )
                reply = plan.rationale
                verified = ver.passed
        except (ReadOnlyConnectorError, ModelProviderError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        updated = store.get_task(task.id)
        cost = updated.cost_amount if updated is not None else 0.0
        audit_logger.append(
            event_type="chat.turn",
            actor="web_ui",
            task_id=task.id,
            payload={"workflow": wf_name, "suite": payload.suite, "verified": verified},
            cost_amount=cost,
            cost_currency=cfg.budget.currency,
        )
        return {
            "reply": reply,
            "task_id": task.id,
            "workflow_name": wf_name,
            "risk_tier": classification.risk_tier.value,
            "data_class": classification.data_class.value,
            "verified": verified,
            "cost_amount": cost,
            "currency": cfg.budget.currency,
            "blocked": False,
        }

    return app
