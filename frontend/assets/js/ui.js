/* DOM helpers. User/AI text only ever enters the page through textContent (never innerHTML). */
(function (S) {
  function el(tag, props, ...children) {
    const node = document.createElement(tag);
    Object.entries(props || {}).forEach(([k, v]) => {
      if (v === undefined || v === null || v === false) return;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
      else if (k === "dataset") Object.assign(node.dataset, v);
      else if (k === "value") node.value = v;
      else if (k === "checked" || k === "disabled" || k === "selected") node[k] = !!v;
      else node.setAttribute(k, v === true ? "" : v);
    });
    children.flat().forEach((c) => {
      if (c === null || c === undefined || c === false) return;
      node.append(c.nodeType ? c : document.createTextNode(String(c)));
    });
    return node;
  }
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const clear = (n) => { while (n.firstChild) n.removeChild(n.firstChild); return n; };
  const mount = (n, ...children) => { clear(n); children.flat().forEach((c) => c && n.append(c)); return n; };

  function fmtDate(v) {
    if (!v) return "—";
    const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(v) ? v : v + "Z");   // backend sends naive UTC
    return isNaN(d) ? "—" : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  }
  const badge = (status) => el("span", { class: `badge ${status || ""}`, text: status || "draft" });
  const synthetic = () => el("span", { class: "synthetic-tag", text: "Synthetic" });
  const debounce = (fn, ms = 300) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  function toast(message, type = "info") {
    const t = el("div", { class: `toast ${type}`, text: message });
    S.ui.$("#toastRoot").append(t);
    setTimeout(() => t.remove(), type === "error" ? 7000 : 3500);
  }

  let noticeTimer;
  function notice(message, type = "error", { retry } = {}) {
    const box = $("#notice");
    mount(box, el("span", { text: message }),
      retry ? el("button", { text: "Retry", onclick: () => { hideNotice(); retry(); } })
            : el("button", { text: "Dismiss", onclick: hideNotice }));
    box.className = `notice ${type}`;
    clearTimeout(noticeTimer);
  }
  function hideNotice() { $("#notice").className = "notice hidden"; }

  const loading = (text = "Loading…") => el("div", { class: "state-box" }, el("span", { class: "spinner" }), text);
  const empty = (text, action) => el("div", { class: "state-box" }, el("div", { text }), action || null);
  function errorBox(err, retry) {
    return el("div", { class: "state-box error" }, el("div", { text: err && err.message ? err.message : String(err) }),
      retry ? el("button", { class: "button secondary small", text: "Try again", onclick: retry }) : null);
  }

  function modal(build, { wide = false } = {}) {
    const root = $("#modalRoot");
    const card = el("div", { class: `modal-card${wide ? " wide" : ""}`, role: "dialog", "aria-modal": "true" });
    const overlay = el("div", { class: "modal" }, card);
    const close = () => { overlay.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
    document.addEventListener("keydown", onKey);
    build(card, close);
    root.append(overlay);
    const first = card.querySelector("input, textarea, select, button");
    if (first) first.focus();
    return close;
  }

  function confirmDialog({ title, message, confirmText = "Delete", danger = true }) {
    return new Promise((resolve) => {
      let settled = false;
      const done = (v, close) => { if (!settled) { settled = true; resolve(v); } close(); };
      modal((card, close) => {
        card.append(el("h2", { text: title }), el("p", { text: message, class: "muted" }),
          el("div", { class: "modal-actions" },
            el("button", { class: "button secondary", text: "Cancel", onclick: () => done(false, close) }),
            el("button", { class: `button ${danger ? "danger" : "primary"}`, text: confirmText, onclick: () => done(true, close) })));
      });
      // closing via Esc/backdrop resolves false
      const obs = new MutationObserver(() => { if (!document.querySelector(".modal")) { if (!settled) { settled = true; resolve(false); } obs.disconnect(); } });
      obs.observe($("#modalRoot"), { childList: true });
    });
  }

  /* Disable a button and show progress while an async action runs. Always re-enables. */
  async function busy(btn, label, fn) {
    const original = btn.textContent;
    btn.disabled = true; if (label) btn.textContent = label;
    try { return await fn(); } finally { btn.disabled = false; btn.textContent = original; }
  }

  function pager({ total, limit, offset, onPage }) {
    if (total <= limit) return el("span");
    const page = Math.floor(offset / limit) + 1, pages = Math.ceil(total / limit);
    return el("div", { class: "row-actions", style: "justify-content:center;margin-top:14px" },
      el("button", { class: "button secondary small", text: "Previous", disabled: offset === 0, onclick: () => onPage(Math.max(0, offset - limit)) }),
      el("span", { class: "muted", text: `Page ${page} of ${pages} · ${total} total` }),
      el("button", { class: "button secondary small", text: "Next", disabled: offset + limit >= total, onclick: () => onPage(offset + limit) }));
  }

  const personaLine = (p) => [p.occupation, p.age ? `age ${p.age}` : null, p.location].filter(Boolean).join(" · ");
  const errMsg = (e) => (e && e.message) || "Something went wrong.";

  S.ui = { el, $, $$, clear, mount, fmtDate, badge, synthetic, debounce, toast, notice, hideNotice, loading, empty, errorBox,
    modal, confirmDialog, busy, pager, personaLine, errMsg };
})(window.SynUser);
