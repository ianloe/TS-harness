"""Beginner-friendly User Manual HTML page for the TS-Harness web app."""

from __future__ import annotations

MANUAL_HTML = """<!DOCTYPE html>
<html lang="en-GB">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TS-Harness User Manual</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fb;
      --card: #ffffff;
      --text: #0f172a;
      --muted: #475569;
      --border: #e2e8f0;
      --primary: #0369a1;
      --primary-hover: #075985;
      --code-bg: #f1f5f9;
    }
    :root[data-theme="dark"] {
      color-scheme: dark;
      --bg: #0b1120;
      --card: #111827;
      --text: #f1f5f9;
      --muted: #94a3b8;
      --border: #1e293b;
      --primary: #38bdf8;
      --primary-hover: #0ea5e9;
      --code-bg: #1e293b;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
    }
    .container { max-width: 960px; margin: 0 auto; padding: 24px 16px 56px; }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--border);
    }
    .brand { display: flex; align-items: center; gap: 14px; }
    .brand img { height: 48px; border-radius: 6px; background: #fff; padding: 4px; }
    .brand h1 { margin: 0; font-size: 1.25rem; }
    .brand p { margin: 0; font-size: 0.875rem; color: var(--muted); }
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 20px;
      margin-bottom: 18px;
    }
    h2 { margin: 0 0 10px; font-size: 1.1rem; }
    h3 { margin: 14px 0 6px; font-size: 0.98rem; }
    code, pre {
      background: var(--code-bg);
      border-radius: 6px;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.85rem;
    }
    code { padding: 2px 6px; }
    pre { padding: 12px; overflow-x: auto; border: 1px solid var(--border); }
    .btn {
      display: inline-block;
      text-decoration: none;
      cursor: pointer;
      border: 0;
      border-radius: 6px;
      padding: 8px 14px;
      font-weight: 600;
      font-size: 0.875rem;
      background: var(--primary);
      color: #fff;
    }
    .btn.secondary { background: #475569; }
    table { width: 100%; border-collapse: collapse; margin-top: 8px; }
    th, td {
      text-align: left;
      padding: 8px 10px;
      border-bottom: 1px solid var(--border);
      font-size: 0.9rem;
    }
    .muted { color: var(--muted); }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="brand">
        <img src="/assets/logo.jpg" alt="Tactics Solutions TS-Harness logo">
        <div>
          <h1>TS-Harness User Manual</h1>
          <p>Beginner guide to setting up, configuring, and running safe workflows</p>
        </div>
      </div>
      <div style="display:flex; gap:8px; flex-wrap:wrap;">
        <button id="theme-toggle" type="button" class="btn secondary" onclick="toggleTheme()">
          Dark Mode
        </button>
        <a class="btn" href="/">Back to Dashboard</a>
      </div>
    </header>

    <div class="card">
      <h2>1. What is TS-Harness?</h2>
      <p>
        TS-Harness is a personal AI work assistant that runs day-to-day tasks such as email triage,
        meeting preparation, research digests, and weekly reviews inside strict safety guardrails.
      </p>
      <ul>
        <li><strong>Draft-only by default</strong>: Workflows prepare drafts and briefs for you,
          and never send emails or publish externally without your approval.</li>
        <li><strong>Deny by default</strong>: Every tool call is blocked unless an explicit rule
          in <code>policies/strict.yaml</code> allows it.</li>
        <li><strong>Untrusted data isolation</strong>: Emails, web pages, and uploaded PDF/Markdown
          files are quarantined as data so hidden instructions inside them cannot hijack
          actions.</li>
        <li><strong>Budget hard stops</strong>: Spend is tracked in <code>SGD</code> or
          <code>USD</code> only, with a warning at 75% and a hard stop at 100%.</li>
      </ul>
    </div>

    <div class="card">
      <h2>2. First-Time Setup (4 Simple Steps)</h2>
      <ol>
        <li>
          <strong>Add an API key in the Secrets Vault</strong>: On the
          <a href="/">Dashboard</a>, pick your provider key (for example
          <code>ANTHROPIC_API_KEY</code>, <code>OPENROUTER_API_KEY</code>,
          <code>AGNES_AI_API_KEY</code>, or <code>DEEPSEEK_API_KEY</code>), paste the key, and
          click <em>Save Secret</em>. Keys are stored in a <code>0600</code>-protected vault and
          are never shown in plain text.
        </li>
        <li>
          <strong>Choose your role-based models</strong>: Set the provider and model name for
          <em>Planner</em> (breaks down the task), <em>Executor</em> (runs tools), and
          <em>Verifier</em> (checks facts, URLs, and arithmetic independently), then click
          <em>Save Configuration</em>.
        </li>
        <li>
          <strong>Set your FinOps budget</strong>: Pick <code>SGD</code> or <code>USD</code>, and
          set your task, workflow, daily, and monthly limits.
        </li>
        <li>
          <strong>(Optional) Connect workspace suites or upload files</strong>: Add
          <code>GOOGLE_WORKSPACE_TOKEN</code>, <code>MICROSOFT_365_TOKEN</code>, or
          <code>LARK_TENANT_ACCESS_TOKEN</code> in the Secrets Vault for read-only access, or
          upload <code>.pdf</code> and <code>.md</code> files in the <em>Documents</em> panel.
        </li>
      </ol>
    </div>

    <div class="card">
      <h2>3. Understanding Risk Tiers</h2>
      <table>
        <thead>
          <tr><th>Tier</th><th>Meaning</th><th>Example</th><th>Behaviour</th></tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>T0</strong></td>
            <td>Read-only</td>
            <td>Read emails, search calendar, read PDF</td>
            <td>Automatic</td>
          </tr>
          <tr>
            <td><strong>T1</strong></td>
            <td>Reversible write</td>
            <td>Create email draft, propose label, save note</td>
            <td>Automatic and logged</td>
          </tr>
          <tr>
            <td><strong>T2</strong></td>
            <td>Outward-facing / hard to undo</td>
            <td>Send email, publish post, delete file</td>
            <td>Held in approval queue</td>
          </tr>
          <tr>
            <td><strong>T3</strong></td>
            <td>Forbidden</td>
            <td>Payments, credential entry, trading, security changes</td>
            <td>Always blocked</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="card">
      <h2>4. Example Workflows</h2>

      <h3>Example A: Morning Inbox Triage (Draft-Only)</h3>
      <p class="muted">Definition: <code>workflows/inbox_triage.yaml</code></p>
      <p>
        Reads unread messages (<code>T0</code>), quarantines suspicious or prompt-injected emails,
        proposes labels (<code>T1</code>), and writes reply drafts (<code>T1</code>). It
        <strong>never sends</strong> an email.
      </p>

      <h3>Example B: Meeting Preparation Brief</h3>
      <p class="muted">Definition: <code>workflows/meeting_prep.yaml</code></p>
      <p>
        Reads your upcoming calendar events (<code>T0</code>), searches related Drive documents
        (<code>T0</code>), and compiles a concise one-page brief verified against source URLs.
      </p>

      <h3>Example C: Bounded Research Digest</h3>
      <p class="muted">Definition: <code>workflows/research_digest.yaml</code></p>
      <p>
        Runs a bounded search loop (max 3 iterations, 60s timeout, no-progress detection),
        collects citations, and passes the draft to the separate <em>Verifier</em> agent to check
        for ungrounded URLs or style issues.
      </p>

      <h3>Example D: Weekly Review Report</h3>
      <p class="muted">Definition: <code>workflows/weekly_review.yaml</code></p>
      <p>
        Aggregates completed tasks, daily/monthly spend in <code>SGD</code> or <code>USD</code>,
        and pending approvals into a weekly summary, verifying arithmetic before output.
      </p>
    </div>

    <div class="card">
      <h2>5. Useful CLI &amp; Emergency Commands</h2>
      <pre><code># Check overall status, audit chain, and spend
uv run ts-harness status

# Run the built-in safety &amp; workflow evaluation suite
uv run ts-harness eval

# Verify the SHA-256 hash-chained audit log
uv run ts-harness audit verify

# Emergency stop (halts all workflows and tools immediately)
uv run ts-harness killswitch pause-all --reason "Manual check"
uv run ts-harness killswitch resume-all

# Generate monthly Markdown &amp; PDF governance attestation reports
uv run ts-harness attest</code></pre>
    </div>
  </div>

  <script>
    function applyTheme(theme) {
      document.documentElement.setAttribute("data-theme", theme);
      const btn = document.getElementById("theme-toggle");
      if (btn) {
        btn.textContent = theme === "dark" ? "Light Mode" : "Dark Mode";
      }
    }
    function initTheme() {
      const saved = localStorage.getItem("ts_harness_theme");
      if (saved === "light" || saved === "dark") {
        applyTheme(saved);
        return;
      }
      const prefersDark =
        window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
      applyTheme(prefersDark ? "dark" : "light");
    }
    function toggleTheme() {
      const current = document.documentElement.getAttribute("data-theme") || "light";
      const next = current === "dark" ? "light" : "dark";
      localStorage.setItem("ts_harness_theme", next);
      applyTheme(next);
    }
    initTheme();
  </script>
</body>
</html>
"""
