/* Boot: settings, backend/database/AI status, initial project load and routing. */
(function (S) {
  const { el, $, mount, toast } = S.ui;

  function statusRow(label, state, text, title) {
    return el("div", { class: "status-row", title: title || text }, el("span", { class: `dot ${state}` }), `${label}: ${text}`);
  }

  async function refreshStatus() {
    const rows = [];
    try {
      const h = await S.api.get("/health", null, { timeout: 6000 });
      rows.push(statusRow("API", "ok", "connected"));
      rows.push(h.database ? statusRow("Database", "ok", "connected")
        : statusRow("Database", "bad", "unavailable", "The database cannot be reached. Check that MySQL is running and the configured port and credentials are correct."));
    } catch (e) {
      rows.push(statusRow("API", "bad", "unreachable", e.message));
      rows.push(statusRow("Database", "warn", "unknown"));
    }
    try {
      const o = await S.api.get("/health/ollama", null, { timeout: 8000 });
      rows.push(statusRow("Local AI", "ok", o.model));
    } catch (e) {
      const d = e.data || {};
      rows.push(statusRow("Local AI", "bad", d.reachable === false || e.network ? "offline" : "model missing", e.message));
    }
    mount($("#statusList"), rows);
  }

  function openSettings() {
    S.ui.modal((card, close) => {
      const url = el("input", { value: S.config.apiBaseUrl, placeholder: "http://127.0.0.1:8000" });
      card.append(el("h2", { text: "Backend connection" }),
        el("p", { class: "muted", text: "Address of the FastAPI backend. Interactive API docs are available at /docs on that address." }),
        el("label", {}, "API base URL", url),
        el("div", { class: "modal-actions" }, el("button", { class: "button secondary", text: "Cancel", onclick: close }),
          el("button", { class: "button primary", text: "Save and reconnect", onclick: async () => {
            try { new URL(url.value.trim()); } catch (e) { toast("Enter a valid URL such as http://127.0.0.1:8000", "error"); return; }
            S.config.apiBaseUrl = url.value; close(); await boot(); toast("Settings saved.", "ok");
          } })));
    });
  }

  async function boot() {
    await Promise.all([S.projects.load(), refreshStatus()]);
    if (S.projects.loadError) S.ui.notice(S.projects.loadError.message, "error", { retry: boot });
    S.emit("project-changed", S.projects.current());
    S.nav.render();
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("#settingsBtn").addEventListener("click", openSettings);
    $("#menuBtn").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
    boot();
    setInterval(refreshStatus, 30000);
  });
  S.refreshStatus = refreshStatus;
})(window.SynUser);
