"""Monthly governance attestation report generator (Markdown and PDF)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from ts_harness.audit.logger import AuditLogger
from ts_harness.config import BudgetConfig, Currency
from ts_harness.governance.controls import ControlMapping
from ts_harness.governance.registry import GovernanceRegistry
from ts_harness.observability.tracing import collect_dashboard_metrics


class AttestationReport(BaseModel):
    """Structured monthly governance attestation report."""

    period: str
    generated_at: datetime
    environment: str
    audit_chain_valid: bool
    audit_entries: int
    total_tasks: int
    policy_blocks: int
    monthly_spend: float
    currency: Currency
    registry_count: int
    controls_mapped: int
    overdue_reviews: list[str]
    markdown: str


def generate_attestation_report(
    *,
    session_factory: sessionmaker[Session],
    budget_config: BudgetConfig,
    audit_logger: AuditLogger,
    registry: GovernanceRegistry,
    controls: list[ControlMapping],
    environment: str = "production",
    period: str | None = None,
) -> AttestationReport:
    """Generate a monthly governance attestation report from live telemetry and registry."""
    now = datetime.now(UTC)
    effective_period = period or now.strftime("%Y-%m")
    chain = audit_logger.verify_chain()
    metrics = collect_dashboard_metrics(session_factory, budget_config)
    overdue = [e.id for e in registry.due_for_review(as_of=now.date())]

    lines = [
        f"# TS-Harness Monthly Governance Attestation ({effective_period})",
        "",
        f"- **Generated (UTC)**: {now.isoformat()}",
        f"- **Environment**: {environment}",
        f"- **Audit Chain Integrity**: {'VALID' if chain.valid else 'BROKEN'} "
        f"({chain.checked_count} entries)",
        f"- **Total Tasks**: {metrics.total_tasks}",
        f"- **Policy Blocks Recorded**: {metrics.policy_blocks}",
        f"- **Monthly Spend**: {metrics.monthly_spend:.4f} / "
        f"{metrics.monthly_limit:.2f} {metrics.currency}",
        f"- **Registered Agents & Workflows**: {len(registry.entries)}",
        f"- **Overdue Reviews**: {', '.join(overdue) if overdue else 'None'}",
        "",
        "## Control Mapping Summary (FRAME / AAEF)",
        "",
        "| Control ID | Name | Module | FRAME ID | AAEF ID |",
        "| --- | --- | --- | --- | --- |",
    ]
    for ctrl in controls:
        lines.append(
            f"| {ctrl.control_id} | {ctrl.name} | `{ctrl.module}` | "
            f"{ctrl.frame_id} | {ctrl.aaef_id} |"
        )
    lines.append("")
    markdown = "\n".join(lines)

    return AttestationReport(
        period=effective_period,
        generated_at=now,
        environment=environment,
        audit_chain_valid=chain.valid,
        audit_entries=chain.checked_count,
        total_tasks=metrics.total_tasks,
        policy_blocks=metrics.policy_blocks,
        monthly_spend=metrics.monthly_spend,
        currency=metrics.currency,
        registry_count=len(registry.entries),
        controls_mapped=len(controls),
        overdue_reviews=overdue,
        markdown=markdown,
    )


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _render_simple_pdf(text: str) -> bytes:
    """Render plain text lines into a valid single-page PDF 1.4 document."""
    lines = text.splitlines()[:48]
    stream_cmds = ["BT", "/F1 10 Tf", "40 760 Td", "14 TL"]
    for line in lines:
        safe = _escape_pdf_text(line[:100])
        stream_cmds.append(f"({safe}) Tj T*")
    stream_cmds.append("ET")
    stream_bytes = "\n".join(stream_cmds).encode("latin-1", errors="replace")

    objects: list[bytes] = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        (
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n"
        ),
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        (
            f"5 0 obj << /Length {len(stream_bytes)} >> stream\n".encode("ascii")
            + stream_bytes
            + b"\nendstream endobj\n"
        ),
    ]

    buf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = [0]
    for obj in objects:
        offsets.append(len(buf))
        buf.extend(obj)

    xref_pos = len(buf)
    buf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    buf.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        buf.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    buf.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return bytes(buf)


def write_attestation_artifacts(
    report: AttestationReport,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Write both Markdown and PDF attestation reports to ``output_dir``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / f"{report.period}-attestation.md"
    pdf_path = output_dir / f"{report.period}-attestation.pdf"

    md_path.write_text(report.markdown, encoding="utf-8")
    pdf_path.write_bytes(_render_simple_pdf(report.markdown))
    return md_path, pdf_path
