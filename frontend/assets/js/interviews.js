/* One-persona interview: setup, persistent chat, resume/view from history. */
(function (S) {
  const { el, $, mount, toast, notice, busy, fmtDate, badge, synthetic, loading, empty, errorBox, confirmDialog, personaLine } = S.ui;
  const iv = { id: null, d: null, personas: [], pendingPersona: null, sending: false, bound: false };
  let historyList = null, saveStatus = "";

  const storeKey = () => `synuser.interview.${S.projects.current().id}`;
  const time = () => new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  /* ---------- setup ---------- */
  function renderProfile() {
    const p = iv.personas.find((x) => x.id === Number($("#ivPersona").value));
    if (!p) { mount($("#ivProfile")); return; }
    const row = (k, v) => v ? el("div", {}, el("b", { text: `${k}: ` }), v) : null;
    mount($("#ivProfile"), el("div", { class: "persona-profile" },
      el("div", {}, el("b", { text: p.name }), " ", synthetic(), el("span", { class: "muted", text: `  ${personaLine(p)}` })),
      row("Goals", p.goals), row("Preferences", p.preferences), row("Pain points", p.pain_points), row("Personality", p.personality)));
  }

  async function loadSetup() {
    const project = S.projects.current();
    mount($("#ivProfile"), loading("Loading personas…"));
    try {
      const data = await S.api.get(`/projects/${project.id}/personas`, { limit: 500 });
      iv.personas = data.items.slice().reverse();
      const sel = $("#ivPersona");
      if (!iv.personas.length) {
        mount(sel); $("#ivStart").disabled = true;
        mount($("#ivProfile"), empty("Generate synthetic personas for this project before starting a survey or interview.", el("button", { class: "button primary small", text: "Generate personas", onclick: () => S.nav.go("personas", "generate") })));
        return;
      }
      $("#ivStart").disabled = false;
      mount(sel, iv.personas.map((p) => el("option", { value: p.id, text: `${p.name}${p.occupation ? " — " + p.occupation : ""}`, selected: p.id === iv.pendingPersona })));
      iv.pendingPersona = null; renderProfile();
    } catch (err) { mount($("#ivProfile"), errorBox(err, loadSetup)); }
  }

  async function startInterview(e) {
    e.preventDefault();
    const title = $("#ivTitle").value.trim(), pid = Number($("#ivPersona").value);
    if (!title) { notice("Enter an interview title.", "warn"); return; }
    if (!pid) { notice("Select a persona to interview.", "warn"); return; }
    S.ui.hideNotice();
    await busy($("#ivStart"), "Starting…", async () => {
      try {
        const d = await S.api.post(`/projects/${S.projects.current().id}/interviews`, {
          persona_id: pid, title, research_topic: $("#ivTopic").value.trim() || null,
          research_objective: $("#ivObjective").value.trim() || null, interview_guide: $("#ivGuide").value.trim() || null });
        adopt(d); saveStatus = "Interview saved"; renderChat(); toast("Interview started.", "ok");
      } catch (err) { notice(err.message, "error"); }
    });
  }

  function adopt(d) { iv.id = d.id; iv.d = d; S.store.set(storeKey(), d.id); }

  /* ---------- chat ---------- */
  function bubble(m, pending) {
    const who = m.role === "researcher" ? "You" : iv.d.persona.name;
    return el("div", { class: `msg ${m.role}${pending ? " pending" : ""}` }, el("small", { text: who }), m.message_text);
  }
  function scrollDown() { const b = $("#ivMessages"); if (b) b.scrollTop = b.scrollHeight; }

  function renderChat() {
    const d = iv.d, p = d.persona, active = d.status === "active";
    $("#ivSetup").classList.add("hidden"); const chat = $("#ivChat"); chat.classList.remove("hidden");
    const input = el("textarea", { id: "ivInput", rows: 1, placeholder: active ? "Ask one question… (Enter to send, Shift+Enter for a new line)" : "This interview is completed", maxlength: 2000, disabled: !active, "aria-label": "Your question" });
    const send = el("button", { class: "button primary", type: "submit", text: "Send", disabled: !active });
    const form = el("form", { class: "chat-form", onsubmit: (e) => { e.preventDefault(); sendMessage(input, send); } }, input, send);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });
    mount(chat, el("div", { class: "chat-card" },
      el("div", { class: "chat-head" },
        el("div", {}, el("div", { class: "row-actions" }, el("strong", { text: p.name }), synthetic(), badge(d.status)),
          el("div", { class: "muted", text: `${personaLine(p) || "Synthetic persona"} · ${d.title}` }),
          el("details", {}, el("summary", { class: "text-button", text: "Persona profile" }),
            el("dl", { class: "kv" }, [["Goals", p.goals], ["Preferences", p.preferences], ["Pain points", p.pain_points], ["Personality", p.personality], ["Objective", d.research_objective]]
              .filter(([, v]) => v).map(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })])))),
        el("div", { class: "row-actions" }, el("span", { id: "ivSave", class: "save-status", text: saveStatus }),
          el("button", { class: "button secondary small", text: "Download PDF", onclick: downloadPdf }),
          active ? el("button", { class: "button secondary small", id: "ivEnd", text: "End interview", onclick: endInterview }) : null,
          el("button", { class: "button secondary small", text: "New interview", onclick: newInterview }))),
      el("div", { id: "ivMessages", class: "chat-messages", "aria-live": "polite" },
        d.messages.length ? d.messages.map((m) => bubble(m)) : el("div", { class: "muted", text: active ? `Say hello to ${p.name} and ask your first question.` : "No messages were exchanged." })),
      form), el("p", { class: "fine-print", text: d.disclaimer }));
    scrollDown(); if (active) input.focus();
  }

  const setSave = (t) => { saveStatus = t; const n = $("#ivSave"); if (n) n.textContent = t; };

  async function sendMessage(input, sendBtn) {
    if (iv.sending) return;
    const text = input.value.trim(); if (!text) return;
    iv.sending = true; S.ui.hideNotice();
    const box = $("#ivMessages"); const id = iv.id;
    if (!iv.d.messages.length) mount(box);
    const mine = bubble({ role: "researcher", message_text: text }, true);
    const typing = el("div", { class: "msg persona pending" }, el("small", { text: iv.d.persona.name }), el("span", { class: "spinner" }), "thinking…");
    box.append(mine, typing); scrollDown();
    input.value = ""; input.disabled = sendBtn.disabled = true; setSave("Saving…");
    try {
      const res = await S.api.post(`/interviews/${id}/messages`, { message_text: text }, { timeout: S.api.ai.timeout() });
      if (iv.id !== id) return;
      iv.d.messages.push(res.researcher_message, res.persona_reply);
      iv.d.message_count = iv.d.messages.length;
      mine.replaceWith(bubble(res.researcher_message)); typing.replaceWith(bubble(res.persona_reply));
      setSave(`Saved at ${time()}`);
    } catch (err) {
      mine.remove(); typing.remove(); input.value = text;      // nothing was stored; let the researcher retry
      setSave("Not saved"); notice(err.message, "error");
      if (!iv.d.messages.length) mount(box, el("div", { class: "muted", text: "No messages yet." }));
    } finally {
      iv.sending = false;
      if (iv.id === id && iv.d.status === "active") { input.disabled = sendBtn.disabled = false; input.focus(); }
      scrollDown();
    }
  }

  async function endInterview() {
    if (iv.sending) return;
    if (!(await confirmDialog({ title: "End this interview?", message: "The transcript is kept, but you will not be able to ask more questions.", confirmText: "End interview", danger: false }))) return;
    try {
      await S.api.post(`/interviews/${iv.id}/complete`);
      const d = await S.api.get(`/interviews/${iv.id}`); adopt(d); saveStatus = "Interview completed"; renderChat(); toast("Interview completed.", "ok");
    } catch (err) { notice(err.message, "warn"); }
  }

  async function downloadPdf() { return pdfFor(iv.id); }
  async function pdfFor(id) {
    try { const out = await S.api.download(`/interviews/${id}/report.pdf`, null, `interview-${id}.pdf`); toast(out.warning ? `PDF downloaded. ${out.warning}` : "PDF downloaded.", "ok"); }
    catch (e) { toast(e.message, "error"); }
  }

  function newInterview() {
    Object.assign(iv, { id: null, d: null }); S.store.remove(storeKey()); saveStatus = "";
    $("#ivChat").classList.add("hidden"); $("#ivSetup").classList.remove("hidden"); loadSetup();
  }

  async function open(id, { navigate = true } = {}) {
    if (navigate) S.nav.go("interview", "start");
    try {
      const d = await S.api.get(`/interviews/${id}`);
      if (d.project_id !== S.projects.current().id) throw new Error("That interview belongs to another project.");
      adopt(d); saveStatus = "Loaded from saved transcript"; renderChat();
    } catch (err) {
      if (err.status === 404) { S.store.remove(storeKey()); iv.id = null; }
      notice(err.message, "error");
    }
  }

  /* ---------- history ---------- */
  function historyRow(s, reload) {
    return el("div", { class: "list-row" },
      el("div", { class: "main-line" }, el("div", { class: "title", text: s.title }),
        el("div", { class: "sub", text: `${S.projects.current().name} · ${s.persona_name || "Persona"} · started ${fmtDate(s.created_at)} · last activity ${fmtDate(s.last_activity_at)} · ${s.message_count} messages` })),
      el("span", { class: "row-actions" }, badge(s.status),
        el("button", { class: "button secondary small", text: s.status === "active" ? "Resume" : "View transcript", onclick: () => open(s.id) }),
        el("button", { class: "button secondary small", text: "Download PDF", onclick: () => pdfFor(s.id) }),
        el("button", { class: "button danger small", text: "Delete", onclick: async () => {
          if (!(await confirmDialog({ title: `Delete “${s.title}”?`, message: "The interview and its transcript will be removed permanently.", confirmText: "Delete interview" }))) return;
          try { await S.api.del(`/interviews/${s.id}`); if (iv.id === s.id) newInterview(); toast("Interview deleted.", "ok"); reload(); } catch (e) { toast(e.message, "error"); }
        } })));
  }

  async function show(tab) {
    if (tab === "start") {
      if (!iv.bound) { iv.bound = true; $("#ivForm").addEventListener("submit", startInterview); $("#ivPersona").addEventListener("change", renderProfile); }
      if (iv.id && iv.d) { renderChat(); return; }
      const saved = parseInt(S.store.get(storeKey()), 10);
      if (saved && !iv.pendingPersona) { await open(saved, { navigate: false }); if (iv.id) return; }
      $("#ivChat").classList.add("hidden"); $("#ivSetup").classList.remove("hidden"); loadSetup();
    } else if (tab === "history") {
      if (!historyList) historyList = S.history.create({ filtersNode: $("#ihFilters"), listNode: $("#ihList"), statuses: ["active", "completed"],
        emptyText: "No interviews have been started for this project yet.", row: historyRow,
        fetch: (p) => S.api.get(`/projects/${S.projects.current().id}/interviews`, p) });
      historyList.load();
    } else S.reports.interview(iv.id);
  }

  S.on("project-changed", () => {
    Object.assign(iv, { id: null, d: null, personas: [], sending: false });
    saveStatus = ""; if (historyList) historyList.reset();
    if (iv.bound) { $("#ivChat").classList.add("hidden"); $("#ivSetup").classList.remove("hidden"); ["#ivTitle", "#ivTopic", "#ivObjective", "#ivGuide"].forEach((i) => { $(i).value = ""; }); }
  });

  S.modules.interview = { show, open: (id) => open(id), preselect(pid) { iv.pendingPersona = pid; Object.assign(iv, { id: null, d: null }); S.store.remove(storeKey()); } };
})(window.SynUser);
