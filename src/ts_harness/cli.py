"""Typer CLI skeleton for TS-harness."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import typer
import uvicorn
from rich.console import Console
from rich.table import Table
from sqlalchemy.orm import Session, sessionmaker

from ts_harness.audit.logger import AuditLogger
from ts_harness.config import Settings, load_settings
from ts_harness.core.store import StateStore
from ts_harness.db.base import create_db_engine, create_session_factory, init_db
from ts_harness.finops.budget import BudgetManager
from ts_harness.killswitch.manager import KillSwitchManager
from ts_harness.logging import configure_logging

app = typer.Typer(
    name="ts-harness",
    help="Personal automation and work harness with strict guardrails.",
    no_args_is_help=True,
)
db_app = typer.Typer(help="Database initialisation and inspection.")
task_app = typer.Typer(help="Task inspection commands.")
audit_app = typer.Typer(help="Audit log verification and inspection.")
killswitch_app = typer.Typer(help="Emergency kill switch controls.")
budget_app = typer.Typer(help="FinOps budget status.")

app.add_typer(db_app, name="db")
app.add_typer(task_app, name="task")
app.add_typer(audit_app, name="audit")
app.add_typer(killswitch_app, name="killswitch")
app.add_typer(budget_app, name="budget")

console = Console()


@dataclass
class AppContainer:
    """Dependency container constructed per CLI invocation."""

    settings: Settings
    session_factory: sessionmaker[Session]
    store: StateStore
    audit: AuditLogger
    budget: BudgetManager
    kill_switch: KillSwitchManager


def build_container(config_path: Path | None = None, *, init_tables: bool = True) -> AppContainer:
    """Build wired application dependencies without global mutable state."""
    settings = load_settings(config_path)
    configure_logging(level=settings.logging.level, json_format=settings.logging.json_format)
    engine = create_db_engine(settings.db.url, echo=settings.db.echo)
    if init_tables:
        init_db(engine)
    session_factory = create_session_factory(engine)
    audit = AuditLogger(session_factory)
    store = StateStore(session_factory)
    budget = BudgetManager(session_factory, settings.budget)
    kill_switch = KillSwitchManager(session_factory, audit)
    return AppContainer(
        settings=settings,
        session_factory=session_factory,
        store=store,
        audit=audit,
        budget=budget,
        kill_switch=kill_switch,
    )


@app.callback()
def main(
    ctx: typer.Context,
    config: Path | None = typer.Option(None, "--config", help="Optional YAML config file."),
) -> None:
    """Store config path on Typer context."""
    ctx.obj = {"config_path": config}


def _get_config_path(ctx: typer.Context) -> Path | None:
    obj = ctx.obj
    if isinstance(obj, dict):
        val = obj.get("config_path")
        if isinstance(val, Path):
            return val
    return None


@app.command("status")
def status_cmd(ctx: typer.Context) -> None:
    """Show overall harness status, active kill switches, and budget spend."""
    c = build_container(_get_config_path(ctx))
    summary = c.budget.get_spend_summary()
    switches = c.kill_switch.list_states(active_only=True)
    chain = c.audit.verify_chain()

    console.print(f"[bold]Environment:[/bold] {c.settings.environment}")
    console.print(f"[bold]Database:[/bold] {c.settings.db.url}")
    console.print(
        f"[bold]Audit Chain:[/bold] {'VALID' if chain.valid else 'BROKEN'} "
        f"({chain.checked_count} entries)"
    )
    console.print(
        f"[bold]Daily Spend:[/bold] {summary.daily_spend:.4f} / "
        f"{summary.daily_limit:.2f} {summary.currency}"
    )
    console.print(
        f"[bold]Monthly Spend:[/bold] {summary.monthly_spend:.4f} / "
        f"{summary.monthly_limit:.2f} {summary.currency}"
    )
    console.print(f"[bold]Active Kill Switches:[/bold] {len(switches)}")


@db_app.command("init")
def db_init(ctx: typer.Context) -> None:
    """Initialise database tables."""
    c = build_container(_get_config_path(ctx), init_tables=True)
    console.print(f"Database initialised at {c.settings.db.url}")


@task_app.command("list")
def task_list(ctx: typer.Context, limit: int = typer.Option(20, min=1, max=200)) -> None:
    """List recent tasks."""
    c = build_container(_get_config_path(ctx))
    tasks = c.store.list_tasks(limit=limit)
    table = Table(title="Tasks")
    table.add_column("ID")
    table.add_column("Workflow")
    table.add_column("Status")
    table.add_column("Tier")
    table.add_column("Title")
    for t in tasks:
        table.add_row(t.id, t.workflow_name, t.status.value, t.risk_tier.value, t.title)
    console.print(table)


@task_app.command("show")
def task_show(ctx: typer.Context, task_id: str) -> None:
    """Show details for a single task."""
    c = build_container(_get_config_path(ctx))
    task = c.store.get_task(task_id)
    if task is None:
        console.print(f"[red]Task '{task_id}' not found.[/red]")
        raise typer.Exit(code=1)
    console.print_json(task.model_dump_json())


@audit_app.command("verify")
def audit_verify(ctx: typer.Context) -> None:
    """Verify the cryptographic hash chain of the audit log."""
    c = build_container(_get_config_path(ctx))
    result = c.audit.verify_chain()
    if not result.valid:
        console.print(
            f"[red]Audit chain verification FAILED at entry {result.broken_at_id}: "
            f"{result.reason}[/red]"
        )
        raise typer.Exit(code=1)
    console.print(f"[green]Audit chain valid ({result.checked_count} entries checked).[/green]")


@audit_app.command("list")
def audit_list(ctx: typer.Context, limit: int = typer.Option(20, min=1, max=200)) -> None:
    """List recent audit events."""
    c = build_container(_get_config_path(ctx))
    events = c.audit.list_events(limit=limit)
    table = Table(title="Audit Events")
    table.add_column("ID")
    table.add_column("Timestamp")
    table.add_column("Actor")
    table.add_column("Event")
    table.add_column("Task ID")
    for ev in events:
        table.add_row(str(ev.id), ev.timestamp, ev.actor, ev.event_type, ev.task_id or "-")
    console.print(table)


@killswitch_app.command("pause-all")
def ks_pause_all(
    ctx: typer.Context,
    reason: str = typer.Option("Manual emergency pause", "--reason"),
) -> None:
    """Pause all workflows and tools globally."""
    c = build_container(_get_config_path(ctx))
    state = c.kill_switch.pause_all(reason=reason)
    console.print(f"[red]Global kill switch activated:[/red] {state.reason}")


@killswitch_app.command("resume-all")
def ks_resume_all(ctx: typer.Context) -> None:
    """Resume from global kill switch."""
    c = build_container(_get_config_path(ctx))
    state = c.kill_switch.resume_all()
    if state is None:
        console.print("Global kill switch was not active.")
    else:
        console.print("[green]Global kill switch deactivated.[/green]")


@killswitch_app.command("pause-workflow")
def ks_pause_workflow(
    ctx: typer.Context,
    workflow_name: str,
    reason: str = typer.Option("Manual workflow pause", "--reason"),
) -> None:
    """Pause a specific workflow."""
    c = build_container(_get_config_path(ctx))
    state = c.kill_switch.pause_workflow(workflow_name, reason=reason)
    console.print(f"[yellow]Paused {state.scope}:[/yellow] {state.reason}")


@killswitch_app.command("resume-workflow")
def ks_resume_workflow(ctx: typer.Context, workflow_name: str) -> None:
    """Resume a paused workflow."""
    c = build_container(_get_config_path(ctx))
    state = c.kill_switch.resume_workflow(workflow_name)
    if state is None:
        console.print(f"Workflow '{workflow_name}' was not paused.")
    else:
        console.print(f"[green]Resumed {state.scope}.[/green]")


@killswitch_app.command("revoke-connector")
def ks_revoke_connector(
    ctx: typer.Context,
    connector_name: str,
    reason: str = typer.Option("Manual connector revocation", "--reason"),
) -> None:
    """Revoke a connector."""
    c = build_container(_get_config_path(ctx))
    state = c.kill_switch.revoke_connector(connector_name, reason=reason)
    console.print(f"[red]Revoked {state.scope}:[/red] {state.reason}")


@killswitch_app.command("restore-connector")
def ks_restore_connector(ctx: typer.Context, connector_name: str) -> None:
    """Restore a revoked connector."""
    c = build_container(_get_config_path(ctx))
    state = c.kill_switch.restore_connector(connector_name)
    if state is None:
        console.print(f"Connector '{connector_name}' was not revoked.")
    else:
        console.print(f"[green]Restored {state.scope}.[/green]")


@killswitch_app.command("status")
def ks_status(ctx: typer.Context) -> None:
    """Show active kill switches."""
    c = build_container(_get_config_path(ctx))
    states = c.kill_switch.list_states(active_only=True)
    if not states:
        console.print("No active kill switches.")
        return
    table = Table(title="Active Kill Switches")
    table.add_column("Scope")
    table.add_column("Reason")
    table.add_column("Activated By")
    for s in states:
        table.add_row(s.scope, s.reason, s.activated_by)
    console.print(table)


@budget_app.command("status")
def budget_status(ctx: typer.Context) -> None:
    """Show current daily and monthly spend against limits."""
    c = build_container(_get_config_path(ctx))
    summary = c.budget.get_spend_summary()
    console.print(
        f"Daily: {summary.daily_spend:.4f} / {summary.daily_limit:.2f} {summary.currency}\n"
        f"Monthly: {summary.monthly_spend:.4f} / {summary.monthly_limit:.2f} {summary.currency}"
    )


@app.command("serve")
def serve_cmd(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host."),
    port: int = typer.Option(8000, "--port", help="Bind port."),
) -> None:
    """Start the local FastAPI API and configuration web interface."""
    from ts_harness.api.app import create_app

    fastapi_app = create_app(config_path=_get_config_path(ctx))
    uvicorn.run(fastapi_app, host=host, port=port)
