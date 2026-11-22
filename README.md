<p align="center">
  <img src="docs/assets/ts-harness-logo.jpg" alt="Tactics Solutions TS-Harness" width="560">
</p>

# TS-Harness

**TS-Harness** is a personal automation and work harness built for day-to-day tasks (email triage, meeting preparation, research digests, document drafting, and weekly reviews) under strict guardrails, versioned policies, security controls, and FinOps cost limits.

It is the general-purpose sibling of `aegis-harness` (which focuses on software engineering) and supports optional OpenTelemetry / Aegis telemetry export.

---

## Core Principles

1. **Deny by default**: No tool executes unless an explicit policy rule permits it.
2. **Policy as code and config**: Rules live in versioned configuration and Python, never in prompts.
3. **Untrusted data isolation**: Content from email, web pages, files, and external tools is treated as untrusted data, never instructions.
4. **Reversible or human-approved**: Actions are either reversible drafts/notes (T0/T1) or held behind human approval (T2); forbidden actions (T3) cannot be overridden.
5. **Bounded execution**: Every loop has iteration, wall-clock, token, spend, and no-progress limits.
6. **Draft-only by default**: Workflows start in draft-only mode and are promoted to autonomous execution individually.
7. **Full auditability**: Every prompt, tool call, policy decision, approval, and cost is recorded in an append-only, SHA-256 hash-chained audit log.

---

## Architecture

```mermaid
flowchart TD
    User["User / CLI / Web UI"] --> API["FastAPI Control Plane & Config UI"]
    User --> CLI["Typer CLI"]
    API --> KS["Kill Switch Manager"]
    CLI --> KS
    API --> Vault["Secrets Vault (0600 / Env)"]
    API --> Store["State Store (SQLite / Postgres)"]
    KS --> Gateway["Governed Tool Gateway (Deny by Default)"]
    Policy["Policy Engine (YAML + Risk Tiers)"] --> Gateway
    Budget["FinOps Budget Manager (SGD / USD)"] --> Gateway
    Gateway --> Tools["Native Tools & MCP Servers"]
    Gateway --> Audit["Hash-Chained Audit Log (SHA-256)"]
    Store --> Audit
```

---

## Quickstart with Docker Compose (Recommended for Portability)

### 1. Start with SQLite (default)

```bash
git clone https://github.com/ianloe/TS-harness.git
cd TS-harness
docker compose up -d --build
```

Open the web configuration and control interface at:
- **Web UI**: [http://localhost:8000](http://localhost:8000)
- **User Manual**: [http://localhost:8000/manual](http://localhost:8000/manual)
- **Healthcheck**: [http://localhost:8000/health](http://localhost:8000/health)

Persistent database, `settings.yaml`, and the `0600`-protected `.secrets.json` vault are stored in the `ts_harness_data` Docker volume (`/data`).

### 2. Optional: Start with PostgreSQL

```bash
TS_HARNESS_DB__URL=postgresql+psycopg://tsharness:tsharness_change_me@postgres:5432/ts_harness \
  docker compose --profile postgres up -d --build
```

---

## Quickstart for Local Development (`uv`)

Requires Python 3.12 and [`uv`](https://docs.astral.sh/uv/).

```bash
make setup
make lint
make test
```

Start the local web configuration UI and API:

```bash
uv run ts-harness serve --host 127.0.0.1 --port 8000
```

Run CLI commands:

```bash
uv run ts-harness status
uv run ts-harness audit verify
uv run ts-harness killswitch pause-all --reason "Maintenance"
uv run ts-harness killswitch resume-all
```

---

## Web Configuration Interface

The built-in web interface at `/` provides two tabs (**Interactive Chat** and **Configuration & Vault**) allowing you to:
- **Interactive Chat**: Chat directly with TS-Harness (`POST /api/chat`) using mock or read-only workspace connectors; every message is PII/secret-redacted, classified by risk tier (`T0`–`T3`), routed through `ToolGateway` and `GraphRunner`, and verified before output.
- **Role-based model routing**: Configure provider (`anthropic`, `openai`, `gemini`, `openrouter`, `agnes-ai`, `deepseek`, `ollama`) and model name independently for `planner`, `executor`, and `verifier` roles.
- **Secrets Vault**: Store or remove `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `AGNES_AI_API_KEY`, `DEEPSEEK_API_KEY`, `GOOGLE_WORKSPACE_TOKEN`, `MICROSOFT_365_TOKEN`, `LARK_APP_ID`, `LARK_APP_SECRET`, `LARK_TENANT_ACCESS_TOKEN`, `AEGIS_API_TOKEN`, and `NTFY_TOKEN`. Secrets are written to a `0600`-protected vault outside the repository, are never returned in plain text, and are automatically redacted from logs and audit records.
- **Workspace Connectors**: One-step read-only connector bundles (`build_suite_bundle`), one-click **Google Workspace OAuth** (`/api/connectors/google/start` requesting `gmail.readonly`, `calendar.readonly`, `drive.readonly` with automatic token refresh), and live readiness status (`/api/connectors/status`) for **Google Workspace**, **Microsoft 365** (Microsoft Graph), and **Lark Suite** (Lark Open Platform).
- **FinOps budgets**: Set task, workflow, daily, and monthly limits in `SGD` or `USD` only, plus pre-flight approval thresholds.
- **Telemetry & logging**: Toggle OpenTelemetry / Aegis export and log verbosity.
- **Documents (PDF & Markdown)**: Upload `.pdf` and `.md`/`.markdown` files (up to 10 MiB, with `%PDF-` magic-byte validation, `pypdf` text extraction, prompt-injection scanning, and `<untrusted_data>` quarantine) and download stored documents via `/api/documents/{filename}/download`.
- **Emergency kill switch**: Pause or resume all execution directly from the header.

---

## Threat Model & Mitigating Controls

| Threat | Mitigating Control |
| --- | --- |
| **Prompt injection** | Trust-labelling of all ingested content, delimited data quarantine, and blocking T1+ actions whose justification traces solely to untrusted content. |
| **Tool abuse** | Deny-by-default `ToolGateway`, risk tiers (T0 to T3), YAML policy rules with explain mode, and human approval queue for T2 actions. |
| **Data exfiltration** | Data classification (`public`, `internal`, `confidential`, `personal`) mapped to permitted models/tools, PII/secret redaction before model calls, and sandboxed execution with no network by default. |
| **Runaway cost** | Hard-capped task, workflow, daily, and monthly budgets in `SGD`/`USD` (soft warning at 75%, hard stop at 100%), loop iteration caps, and no-progress detection. |
| **Connector compromise** | Scoped read-only credentials by default, secrets stored outside repo/model context, and per-connector kill switch revocation checked before every execution. |

---

## Build Roadmap

- **Phase 1 (Complete)**: Foundation (config, SQLite/Postgres ORM + Alembic, state store, checkpoints, DLQ, hash-chained audit log, FinOps budgets, kill switch, deny-by-default gateway, CLI, Docker Compose, and Web Configuration UI).
- **Phase 2 (Complete)**: Safety (risk tiers, YAML policy engine with explain mode, approval queue, guardrails, prompt-injection corpus, Docker sandbox).
- **Phase 3 (Complete)**: Orchestration (workflow graph engine with bounded loops, planner/executor/verifier agents, model router, crash resume).
- **Phase 4 (Complete)**: Workflows (`inbox_triage`, `meeting_prep`, `research_digest`, `weekly_review` against mock and read-only connectors, layered memory, and triggers).
- **Phase 5 (Complete)**: Visibility (OpenTelemetry tracing, dashboard metrics & FinOps attribution API, prompt cache, anomaly detector, and regression eval harness).
- **Phase 6 (Complete)**: Governance (agent/workflow registry, FRAME/AAEF control mapping, monthly Markdown/PDF attestation report generator, and [incident runbook](docs/runbook.md)).

## Documentation

- [Default Policy Set](docs/policies.md) (`policies/strict.yaml`, `policies/relaxed.yaml`)
- [Incident & Kill Switch Runbook](docs/runbook.md)
- [Architecture & Design Decisions](docs/decisions.md)
- [CI Workflow Template](docs/ci-workflow.yml)
