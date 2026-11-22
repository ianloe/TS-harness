# TS-Harness Incident & Kill Switch Runbook

This runbook documents operational procedures for halting execution, investigating incidents, verifying audit integrity, and rotating credentials.

## 1. Emergency Kill Switch

### Pause All Execution Immediately

Via CLI:
```bash
uv run ts-harness killswitch pause-all --reason "Incident investigation"
```

Via Web UI / API:
- Click **Pause All (Kill Switch)** in the dashboard header at `/`, or:
```bash
curl -X POST http://127.0.0.1:8000/api/killswitch/pause-all \
  -H "Content-Type: application/json" \
  -d '{"reason": "Incident investigation"}'
```

### Pause a Single Workflow or Revoke a Connector

```bash
uv run ts-harness killswitch pause-workflow inbox_triage --reason "Unexpected drafts"
uv run ts-harness killswitch revoke-connector mail --reason "Token rotation"
```

### Check Active Kill Switches and Resume

```bash
uv run ts-harness killswitch status
uv run ts-harness killswitch resume-all
```

## 2. Verify Audit Chain Integrity

If tampering or unexpected behaviour is suspected, verify the SHA-256 hash chain:

```bash
uv run ts-harness audit verify
uv run ts-harness audit list --limit 50
```

## 3. Secret Rotation

1. Revoke the affected connector with `ts-harness killswitch revoke-connector <name>`.
2. Rotate the key at the provider (Anthropic, OpenAI, Gemini, OpenRouter, Agnes-AI, DeepSeek, or OAuth).
3. Update the key in the `SecretsVault` via the Web Configuration UI (`/`) or environment variables.
4. Restore the connector with `ts-harness killswitch restore-connector <name>`.

## 4. Monthly Attestation

Generate the Markdown and PDF attestation reports:

```bash
make attest
```
