"""HTML dashboard and configuration UI for TS-harness."""

from __future__ import annotations

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en-GB">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TS-Harness Control &amp; Configuration</title>
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
      --danger: #b91c1c;
      --ok: #15803d;
      --warn: #b45309;
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
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }
    .container { max-width: 1080px; margin: 0 auto; padding: 24px 16px 48px; }
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
    .brand img { height: 52px; border-radius: 6px; background: #fff; padding: 4px; }
    .brand h1 { margin: 0; font-size: 1.25rem; }
    .brand p { margin: 0; font-size: 0.875rem; color: var(--muted); }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 18px;
      margin-bottom: 16px;
    }
    h2 { margin: 0 0 12px; font-size: 1.05rem; }
    h3 { margin: 14px 0 8px; font-size: 0.95rem; color: var(--muted); }
    label { display: block; font-size: 0.85rem; font-weight: 600; margin-bottom: 4px; }
    input, select {
      width: 100%;
      padding: 8px 10px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: transparent;
      color: inherit;
      font-size: 0.9rem;
    }
    .field { margin-bottom: 12px; }
    .row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
    button {
      cursor: pointer;
      border: 0;
      border-radius: 6px;
      padding: 9px 14px;
      font-weight: 600;
      font-size: 0.875rem;
      background: var(--primary);
      color: #fff;
    }
    button:hover { background: var(--primary-hover); }
    button.danger { background: var(--danger); }
    button.secondary { background: #475569; }
    .badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 600;
      border: 1px solid var(--border);
    }
    .badge.ok { color: var(--ok); border-color: var(--ok); }
    .badge.warn { color: var(--warn); border-color: var(--warn); }
    .badge.danger { color: var(--danger); border-color: var(--danger); }
    .secret-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 8px 0;
      border-bottom: 1px solid var(--border);
      flex-wrap: wrap;
    }
    .secret-row:last-child { border-bottom: 0; }
    .toast {
      padding: 10px 14px;
      border-radius: 8px;
      margin-bottom: 16px;
      border: 1px solid var(--border);
      background: var(--card);
      display: none;
    }
    .muted { color: var(--muted); font-size: 0.85rem; }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="brand">
        <img src="/assets/logo.jpg" alt="Tactics Solutions TS-Harness logo">
        <div>
          <h1>TS-Harness Control &amp; Configuration</h1>
          <p>Draft-only by default, deny-by-default tool gateway, bounded FinOps</p>
        </div>
      </div>
      <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
        <a href="/manual" style="font-weight:600; color:var(--primary); text-decoration:none;">
          User Manual
        </a>
        <button id="theme-toggle" type="button" class="secondary" onclick="toggleTheme()">
          Dark Mode
        </button>
        <button class="danger" onclick="toggleKillSwitch(true)">Pause All (Kill Switch)</button>
        <button class="secondary" onclick="toggleKillSwitch(false)">Resume All</button>
      </div>
    </header>

    <div id="toast" class="toast" role="status"></div>

    <div class="grid">
      <div class="card">
        <h2>System Status</h2>
        <div id="status-box" class="muted">Loading status...</div>
      </div>
      <div class="card">
        <h2>API Keys &amp; Secrets Vault</h2>
        <p class="muted">
          Secrets are stored in a 0600-protected vault outside the repository and are never
          returned in plain text or exposed to model context.
        </p>
        <div id="secrets-list" style="margin-bottom:14px;">Loading...</div>
        <form onsubmit="saveSecret(event)">
          <div class="row">
            <div class="field">
              <label for="secret-key">Secret Key</label>
              <select id="secret-key">
                <option value="ANTHROPIC_API_KEY">ANTHROPIC_API_KEY</option>
                <option value="OPENAI_API_KEY">OPENAI_API_KEY</option>
                <option value="GEMINI_API_KEY">GEMINI_API_KEY</option>
                <option value="OPENROUTER_API_KEY">OPENROUTER_API_KEY</option>
                <option value="AGNES_AI_API_KEY">AGNES_AI_API_KEY</option>
                <option value="DEEPSEEK_API_KEY">DEEPSEEK_API_KEY</option>
                <option value="GOOGLE_WORKSPACE_TOKEN">GOOGLE_WORKSPACE_TOKEN</option>
                <option value="MICROSOFT_365_TOKEN">MICROSOFT_365_TOKEN</option>
                <option value="LARK_APP_ID">LARK_APP_ID</option>
                <option value="LARK_APP_SECRET">LARK_APP_SECRET</option>
                <option value="LARK_TENANT_ACCESS_TOKEN">LARK_TENANT_ACCESS_TOKEN</option>
                <option value="AEGIS_API_TOKEN">AEGIS_API_TOKEN</option>
                <option value="NTFY_TOKEN">NTFY_TOKEN</option>
              </select>
            </div>
            <div class="field">
              <label for="secret-value">New Secret Value</label>
              <input
                id="secret-value"
                type="password"
                placeholder="sk-..."
                autocomplete="off"
                required
              >
            </div>
          </div>
          <button type="submit">Save Secret</button>
        </form>
      </div>
    </div>

    <form class="card" onsubmit="saveConfig(event)">
      <h2>Models, Budgets &amp; Harness Configuration</h2>

      <h3>Role-Based Model Routing</h3>
      <div class="grid">
        <div>
          <label>Planner Provider</label>
          <select id="planner-provider">
            <option value="anthropic">anthropic</option>
            <option value="openai">openai</option>
            <option value="gemini">gemini</option>
            <option value="openrouter">openrouter</option>
            <option value="agnes-ai">agnes-ai</option>
            <option value="deepseek">deepseek</option>
            <option value="ollama">ollama</option>
          </select>
          <div class="field" style="margin-top:8px;">
            <label>Planner Model</label>
            <input id="planner-model" type="text" required>
          </div>
        </div>
        <div>
          <label>Executor Provider</label>
          <select id="executor-provider">
            <option value="anthropic">anthropic</option>
            <option value="openai">openai</option>
            <option value="gemini">gemini</option>
            <option value="openrouter">openrouter</option>
            <option value="agnes-ai">agnes-ai</option>
            <option value="deepseek">deepseek</option>
            <option value="ollama">ollama</option>
          </select>
          <div class="field" style="margin-top:8px;">
            <label>Executor Model</label>
            <input id="executor-model" type="text" required>
          </div>
        </div>
        <div>
          <label>Verifier Provider</label>
          <select id="verifier-provider">
            <option value="anthropic">anthropic</option>
            <option value="openai">openai</option>
            <option value="gemini">gemini</option>
            <option value="openrouter">openrouter</option>
            <option value="agnes-ai">agnes-ai</option>
            <option value="deepseek">deepseek</option>
            <option value="ollama">ollama</option>
          </select>
          <div class="field" style="margin-top:8px;">
            <label>Verifier Model</label>
            <input id="verifier-model" type="text" required>
          </div>
        </div>
      </div>

      <h3>FinOps Budget Limits (SGD or USD only)</h3>
      <div class="row">
        <div class="field">
          <label for="budget-currency">Currency</label>
          <select id="budget-currency">
            <option value="SGD">SGD</option>
            <option value="USD">USD</option>
          </select>
        </div>
        <div class="field">
          <label for="budget-task">Task Limit</label>
          <input id="budget-task" type="number" step="0.01" min="0.01" required>
        </div>
        <div class="field">
          <label for="budget-workflow">Workflow Limit</label>
          <input id="budget-workflow" type="number" step="0.01" min="0.01" required>
        </div>
        <div class="field">
          <label for="budget-daily">Daily Limit</label>
          <input id="budget-daily" type="number" step="0.01" min="0.01" required>
        </div>
        <div class="field">
          <label for="budget-monthly">Monthly Limit</label>
          <input id="budget-monthly" type="number" step="0.01" min="0.01" required>
        </div>
        <div class="field">
          <label for="budget-preflight">Pre-flight Approval Threshold</label>
          <input id="budget-preflight" type="number" step="0.01" min="0" required>
        </div>
      </div>

      <h3>Telemetry &amp; Environment</h3>
      <div class="row">
        <div class="field">
          <label for="env-name">Environment</label>
          <input id="env-name" type="text" required>
        </div>
        <div class="field">
          <label for="telemetry-enabled">Aegis / OpenTelemetry Export</label>
          <select id="telemetry-enabled">
            <option value="false">Disabled</option>
            <option value="true">Enabled</option>
          </select>
        </div>
        <div class="field">
          <label for="aegis-url">Aegis Export URL (optional)</label>
          <input id="aegis-url" type="url" placeholder="https://aegis.local/v1/telemetry">
        </div>
        <div class="field">
          <label for="log-level">Log Level</label>
          <select id="log-level">
            <option value="DEBUG">DEBUG</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </select>
        </div>
      </div>

      <button type="submit">Save Configuration</button>
    </form>

    <div class="card">
      <h2>Documents (PDF &amp; Markdown)</h2>
      <p class="muted">
        Upload <code>.pdf</code> or <code>.md</code> files for workflow input. Extracted text is
        automatically quarantined as untrusted data and scanned for prompt injection.
      </p>
      <form onsubmit="uploadDocument(event)" style="margin-bottom:14px;">
        <div class="row">
          <div class="field">
            <label for="doc-file">Select PDF or Markdown file</label>
            <input id="doc-file" type="file" accept=".pdf,.md,.markdown" required>
          </div>
        </div>
        <button type="submit">Upload Document</button>
      </form>
      <div id="docs-list" class="muted">Loading documents...</div>
    </div>

    <div class="card">
      <h2>Workspace Connectors (Read-Only by Default)</h2>
      <p class="muted">
        Configure suite tokens in the Secrets Vault above to connect Google Workspace,
        Microsoft 365, or Lark Suite.
      </p>
      <div id="connectors-list" class="muted">Loading connector status...</div>
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

    function showToast(msg, isError = false) {
      const el = document.getElementById("toast");
      el.style.display = "block";
      el.style.borderColor = isError ? "var(--danger)" : "var(--ok)";
      el.textContent = msg;
    }

    async function loadStatus() {
      const res = await fetch("/api/status");
      const data = await res.json();
      const box = document.getElementById("status-box");
      const chainBadge = data.audit_chain_valid
        ? `<span class="badge ok">VALID (${data.audit_entries} entries)</span>`
        : `<span class="badge danger">BROKEN</span>`;
      const ksBadge = data.active_kill_switches.length === 0
        ? `<span class="badge ok">None active</span>`
        : `<span class="badge danger">${data.active_kill_switches.length} active</span>`;
      box.innerHTML = `
        <p><strong>Environment:</strong> ${data.environment}</p>
        <p><strong>Audit Chain:</strong> ${chainBadge}</p>
        <p><strong>Kill Switches:</strong> ${ksBadge}</p>
        <p><strong>Daily Spend:</strong>
          ${data.daily_spend.toFixed(4)} / ${data.daily_limit.toFixed(2)} ${data.currency}</p>
        <p><strong>Monthly Spend:</strong>
          ${data.monthly_spend.toFixed(4)} / ${data.monthly_limit.toFixed(2)} ${data.currency}</p>
      `;
    }

    async function loadConfig() {
      const res = await fetch("/api/config");
      const data = await res.json();
      const cfg = data.settings;

      document.getElementById("env-name").value = cfg.environment;
      document.getElementById("planner-provider").value = cfg.models.planner.provider;
      document.getElementById("planner-model").value = cfg.models.planner.model_name;
      document.getElementById("executor-provider").value = cfg.models.executor.provider;
      document.getElementById("executor-model").value = cfg.models.executor.model_name;
      document.getElementById("verifier-provider").value = cfg.models.verifier.provider;
      document.getElementById("verifier-model").value = cfg.models.verifier.model_name;

      document.getElementById("budget-currency").value = cfg.budget.currency;
      document.getElementById("budget-task").value = cfg.budget.task_limit;
      document.getElementById("budget-workflow").value = cfg.budget.workflow_limit;
      document.getElementById("budget-daily").value = cfg.budget.daily_limit;
      document.getElementById("budget-monthly").value = cfg.budget.monthly_limit;
      document.getElementById("budget-preflight").value = cfg.budget.preflight_approval_threshold;

      document.getElementById("telemetry-enabled").value = String(cfg.telemetry.enabled);
      document.getElementById("aegis-url").value = cfg.telemetry.aegis_export_url || "";
      document.getElementById("log-level").value = cfg.logging.level;

      const list = document.getElementById("secrets-list");
      list.innerHTML = data.secrets.map(s => `
        <div class="secret-row">
          <div>
            <strong>${s.key}</strong>
            <span class="muted">(${s.source})</span>
          </div>
          <div style="display:flex; align-items:center; gap:8px;">
            <span class="badge ${s.configured ? "ok" : "warn"}">
              ${s.configured ? s.masked_preview : "Not configured"}
            </span>
            ${s.source === "vault"
              ? `<button type="button" class="secondary"
                  onclick="deleteSecret('${s.key}')">Remove</button>`
              : ""}
          </div>
        </div>
      `).join("");
    }

    async function saveConfig(event) {
      event.preventDefault();
      const payload = {
        environment: document.getElementById("env-name").value,
        models: {
          planner: {
            provider: document.getElementById("planner-provider").value,
            model_name: document.getElementById("planner-model").value,
          },
          executor: {
            provider: document.getElementById("executor-provider").value,
            model_name: document.getElementById("executor-model").value,
          },
          verifier: {
            provider: document.getElementById("verifier-provider").value,
            model_name: document.getElementById("verifier-model").value,
          },
        },
        budget: {
          currency: document.getElementById("budget-currency").value,
          task_limit: parseFloat(document.getElementById("budget-task").value),
          workflow_limit: parseFloat(document.getElementById("budget-workflow").value),
          daily_limit: parseFloat(document.getElementById("budget-daily").value),
          monthly_limit: parseFloat(document.getElementById("budget-monthly").value),
          preflight_approval_threshold: parseFloat(
            document.getElementById("budget-preflight").value
          ),
        },
        telemetry: {
          enabled: document.getElementById("telemetry-enabled").value === "true",
          aegis_export_url: document.getElementById("aegis-url").value || null,
        },
        logging: {
          level: document.getElementById("log-level").value,
        },
      };
      const res = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json();
        showToast("Failed to save configuration: " + (err.detail || res.statusText), true);
        return;
      }
      showToast("Configuration saved and audited.");
      await Promise.all([loadConfig(), loadStatus()]);
    }

    async function saveSecret(event) {
      event.preventDefault();
      const key = document.getElementById("secret-key").value;
      const value = document.getElementById("secret-value").value;
      const res = await fetch("/api/secrets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, value }),
      });
      document.getElementById("secret-value").value = "";
      if (!res.ok) {
        const err = await res.json();
        showToast("Failed to save secret: " + (err.detail || res.statusText), true);
        return;
      }
      showToast(`Secret ${key} stored in vault.`);
      await loadConfig();
    }

    async function deleteSecret(key) {
      const res = await fetch(`/api/secrets/${encodeURIComponent(key)}`, { method: "DELETE" });
      if (res.ok) {
        showToast(`Secret ${key} removed from vault.`);
        await loadConfig();
      }
    }

    async function toggleKillSwitch(pause) {
      const endpoint = pause ? "/api/killswitch/pause-all" : "/api/killswitch/resume-all";
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "Triggered from web UI" }),
      });
      if (res.ok) {
        showToast(pause ? "Global kill switch activated." : "Global kill switch deactivated.");
        await loadStatus();
      }
    }

    async function loadDocuments() {
      const res = await fetch("/api/documents");
      const docs = await res.json();
      const box = document.getElementById("docs-list");
      if (docs.length === 0) {
        box.textContent = "No documents uploaded yet.";
        return;
      }
      box.innerHTML = docs.map(d => `
        <div class="secret-row">
          <div><strong>${d.name}</strong> <span class="muted">(${d.size_bytes} bytes)</span></div>
          <div>
            <a href="/api/documents/${encodeURIComponent(d.name)}/download">Download</a>
          </div>
        </div>
      `).join("");
    }

    async function uploadDocument(event) {
      event.preventDefault();
      const input = document.getElementById("doc-file");
      if (!input.files || input.files.length === 0) return;
      const form = new FormData();
      form.append("file", input.files[0]);
      const res = await fetch("/api/documents/upload", { method: "POST", body: form });
      if (!res.ok) {
        const err = await res.json();
        showToast("Upload failed: " + (err.detail || res.statusText), true);
        return;
      }
      const meta = await res.json();
      input.value = "";
      showToast(
        meta.suspicious
          ? `Uploaded ${meta.name} (warning: injection signals detected)`
          : `Uploaded ${meta.name}`,
        meta.suspicious
      );
      await loadDocuments();
    }

    async function loadConnectors() {
      const res = await fetch("/api/connectors/status");
      const suites = await res.json();
      const box = document.getElementById("connectors-list");
      box.innerHTML = suites.map(s => `
        <div class="secret-row">
          <div><strong>${s.label}</strong> <span class="muted">(${s.mode})</span></div>
          <div>
            <span class="badge ${s.configured ? "ok" : "warn"}">
              ${s.configured ? "Ready" : "Needs " + s.missing_keys.join(", ")}
            </span>
          </div>
        </div>
      `).join("");
    }

    loadStatus();
    loadConfig();
    loadDocuments();
    loadConnectors();
  </script>
</body>
</html>
"""
