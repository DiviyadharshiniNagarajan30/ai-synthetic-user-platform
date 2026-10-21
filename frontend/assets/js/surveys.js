/* Survey builder, AI processing with live progress, saved-results view, and survey history. */
(function (S) {
  const { el, $, mount, toast, notice, busy, fmtDate, badge, loading, empty, errorBox, confirmDialog } = S.ui;
  const TYPES = [["open_ended", "Open-ended"], ["single_choice", "Single choice"], ["multiple_choice", "Multiple choice"], ["rating", "Rating (1-5)"]];
  const sv = { surveyId: null, questions: [], personaIds: new Set(), personas: [], processing: false, pending: [], poll: null, ready: false };
  let historyList = null, personaSeq = 0, listenersBound = false;

  const storeKey = () => `synuser.survey.${S.projects.current().id}`;
  const blankQ = () => ({ id: null, text: "", type: "open_ended", options: "" });

  /* ---------- results view (shared with the report tab) ---------- */
  function resultsView(r, { onRetry, onPdf } = {}) {
    const processing = r.status === "processing";
    const pct = r.expected_responses ? Math.round((r.total_responses / r.expected_responses) * 100) : 0;
    return el("div", { class: "panel results" },
      el("div", { class: "results-head" },
        el("div", {}, el("h2", { text: "Survey results" }),
          el("div", { class: "muted", text: `${r.survey_title} · ${r.total_responses} of ${r.expected_responses} responses saved · ${r.total_questions} question(s) · ${r.total_personas} persona(s)` })),
        el("span", { class: "row-actions" }, badge(r.status),
          onRetry && r.failed_items.length && !processing ? el("button", { class: "button secondary small", text: "Retry failed responses", onclick: onRetry }) : null,
          onPdf ? el("button", { class: "button secondary small", text: "Download PDF", onclick: onPdf }) : null)),
      processing ? el("div", { class: "progress" }, el("span", { class: "spinner" }), `Generating answers… ${r.total_responses} of ${r.expected_responses} saved`, el("div", { class: "bar" }, el("i", { style: `width:${pct}%` }))) : null,
      r.failed_items.length ? el("div", { class: "notice warn" }, el("span", { text: `${r.failed_items.length} response(s) could not be generated. Retry the failed item${r.failed_items.length > 1 ? "s" : ""}.` + (r.last_error ? ` Last error: ${r.last_error}` : "") })) : null,
      r.results.map((q, qi) => el("section", { class: "q-result" },
        el("h3", { text: `Question ${qi + 1}: ${q.question_text}` }),
        el("div", { class: "muted", text: `${q.answer_count} response${q.answer_count === 1 ? "" : "s"}` }),
        q.answers.map((a, ai) => el("div", { class: "answer" },
          el("div", { class: "who", text: `Persona ${ai + 1} — ${a.persona_name}` }, a.persona_occupation ? el("span", { text: `, ${a.persona_occupation}` }) : null),
          el("blockquote", { text: `“${a.answer}”` }))),
        r.failed_items.filter((f) => f.question_id === q.question_id).map((f) => el("div", { class: "answer failed" },
          el("div", { class: "who", text: f.persona_name }), el("div", { text: "This response could not be generated. Retry the failed item." + (f.error ? ` (${f.error})` : "") }))))),
      el("p", { class: "fine-print", text: r.disclaimer }));
  }

  async function downloadPdf(id, extra) {
    try {
      const out = await S.api.download(`/surveys/${id}/report.pdf`, extra, `survey-${id}.pdf`);
      toast(out.warning ? `PDF downloaded. ${out.warning}` : "PDF downloaded.", out.warning ? "info" : "ok");
    } catch (e) { toast(e.message, "error"); }
  }

  /* ---------- question editor ---------- */
  function renderQuestions() {
    const box = $("#svQuestions");
    const rows = sv.questions.map((q, i) => {
      const text = el("input", { value: q.text, maxlength: 1000, placeholder: "Write a question for your personas", "aria-label": `Question ${i + 1}`, oninput: (e) => { q.text = e.target.value; } });
      const type = el("select", { "aria-label": "Question type", onchange: (e) => { q.type = e.target.value; renderQuestions(); } }, TYPES.map(([v, l]) => el("option", { value: v, text: l, selected: v === q.type })));
      const tools = el("div", { class: "q-tools" },
        el("button", { type: "button", title: "Move up", "aria-label": "Move up", text: "↑", disabled: i === 0, onclick: () => { sv.questions.splice(i - 1, 0, sv.questions.splice(i, 1)[0]); renderQuestions(); } }),
        el("button", { type: "button", title: "Move down", "aria-label": "Move down", text: "↓", disabled: i === sv.questions.length - 1, onclick: () => { sv.questions.splice(i + 1, 0, sv.questions.splice(i, 1)[0]); renderQuestions(); } }),
        el("button", { type: "button", title: "Delete question", "aria-label": "Delete question", text: "✕", onclick: () => { sv.questions.splice(i, 1); if (!sv.questions.length) sv.questions.push(blankQ()); renderQuestions(); } }));
      const opts = (q.type === "single_choice" || q.type === "multiple_choice")
        ? el("input", { class: "opts", value: q.options, placeholder: "Options, separated by commas", "aria-label": "Options", oninput: (e) => { q.options = e.target.value; } }) : null;
      return el("div", { class: "q-row" }, el("span", { class: "num", text: String(i + 1) }), text, type, tools, opts);
    });
    mount(box, rows);
  }

  /* ---------- persona picker ---------- */
  function renderPersonas() {
    const box = $("#svPersonas");
    $("#svPersonaCount").textContent = `${sv.personaIds.size} of ${sv.personas.length} selected`;
    if (!sv.personas.length) {
      mount(box, empty("Generate synthetic personas for this project before starting a survey.", el("button", { class: "button primary small", text: "Generate personas", onclick: () => S.nav.go("personas", "generate") }))); return;
    }
    mount(box, sv.personas.map((p) => {
      const cb = el("input", { type: "checkbox", checked: sv.personaIds.has(p.id), "aria-label": `Select ${p.name}`, onchange: (e) => {
        if (e.target.checked) sv.personaIds.add(p.id); else sv.personaIds.delete(p.id);
        row.classList.toggle("on", e.target.checked); $("#svPersonaCount").textContent = `${sv.personaIds.size} of ${sv.personas.length} selected`; } });
      const row = el("label", { class: `select-item${sv.personaIds.has(p.id) ? " on" : ""}` }, cb, el("div", {}, el("b", { text: p.name }), el("span", { text: S.ui.personaLine(p) || "Synthetic persona" })));
      return row;
    }));
  }

  async function loadPersonas() {
    const project = S.projects.current(); const my = ++personaSeq;
    mount($("#svPersonas"), loading("Loading personas…"));
    try {
      const data = await S.api.get(`/projects/${project.id}/personas`, { limit: 500 });
      if (my !== personaSeq) return;
      sv.personas = data.items.slice().reverse();           // oldest first = stable order
      const valid = new Set(sv.personas.map((p) => p.id));
      sv.personaIds = new Set([...sv.personaIds, ...sv.pending].filter((id) => valid.has(id))); sv.pending = [];
      renderPersonas();
    } catch (err) { if (my === personaSeq) mount($("#svPersonas"), errorBox(err, loadPersonas)); }
  }

  /* ---------- form state ---------- */
  function resetForm() {
    stopPolling();
    Object.assign(sv, { surveyId: null, questions: [blankQ()], personaIds: new Set(), processing: false });
    $("#svTitle").value = $("#svTopic").value = $("#svObjective").value = "";
    S.store.remove(storeKey());
    $("#svEditing").classList.add("hidden"); $("#svProgress").classList.add("hidden");
    mount($("#svResults")); renderQuestions(); renderPersonas(); updateHint();
  }
  function updateHint() { $("#svHint").textContent = sv.surveyId ? "Processing again only generates missing answers." : "The survey is saved before processing starts."; }

  function formBody() {
    return {
      title: $("#svTitle").value.trim(), research_topic: $("#svTopic").value.trim() || null, research_objective: $("#svObjective").value.trim() || null,
      questions: sv.questions.filter((q) => q.text.trim()).map((q) => ({ id: q.id, question_text: q.text.trim(), question_type: q.type,
        options: q.type.endsWith("choice") ? q.options.split(",").map((o) => o.trim()).filter(Boolean) : null })),
      persona_ids: sv.personas.filter((p) => sv.personaIds.has(p.id)).map((p) => p.id),
    };
  }
  function validate(b) {
    if (!b.title) return "Enter a survey title.";
    if (!b.questions.length) return "Add at least one question.";
    const bad = b.questions.find((q) => q.question_type.endsWith("choice") && q.options.length < 2);
    if (bad) return `Add at least two comma-separated options to “${bad.question_text}”.`;
    if (!b.persona_ids.length) return "Select at least one persona.";
    return null;
  }

  async function open(id, { navigate = true } = {}) {
    if (navigate) S.nav.go("survey", "generate");
    const project = S.projects.current();
    await ensureReady();
    mount($("#svResults"), loading("Loading saved survey…"));
    try {
      const d = await S.api.get(`/surveys/${id}`);
      if (d.project_id !== project.id) throw new Error("That survey belongs to another project.");
      sv.surveyId = d.id; S.store.set(storeKey(), d.id);
      sv.questions = d.questions.map((q) => ({ id: q.id, text: q.question_text, type: q.question_type, options: (q.options || []).join(", ") }));
      sv.personaIds = new Set(d.participants.map((p) => p.id));
      $("#svTitle").value = d.title; $("#svTopic").value = d.research_topic || ""; $("#svObjective").value = d.research_objective || "";
      const banner = $("#svEditing"); banner.textContent = `Editing saved survey #${d.id} (${d.status}). Press “New survey” to start a different one.`; banner.classList.remove("hidden");
      renderQuestions(); renderPersonas(); updateHint();
      await refreshResults();
      if (d.status === "processing") startPolling(d.id);
    } catch (err) {
      mount($("#svResults"), errorBox(err));
      if (err.status === 404) { S.store.remove(storeKey()); sv.surveyId = null; }
    }
  }

  async function refreshResults() {
    if (!sv.surveyId) return;
    const id = sv.surveyId;
    try {
      const r = await S.api.get(`/surveys/${id}/results`);
      if (id !== sv.surveyId) return;
      $("#svProgress").classList.add("hidden");
      mount($("#svResults"), resultsView(r, { onRetry: () => process(), onPdf: () => downloadPdf(id) }));
      return r;
    } catch (err) { if (id === sv.surveyId) mount($("#svResults"), errorBox(err, refreshResults)); }
  }

  function startPolling(id) { stopPolling(); sv.poll = setInterval(() => { if (sv.surveyId === id) refreshResults(); }, 2500); }
  function stopPolling() { if (sv.poll) clearInterval(sv.poll); sv.poll = null; }

  async function process() {
    if (sv.processing) return;
    const body = formBody(); const bad = validate(body);
    if (bad) { notice(bad, "warn"); return; }
    S.ui.hideNotice();
    const project = S.projects.current(); const btn = $("#svProcess");
    sv.processing = true; $("#svReset").disabled = true;
    await busy(btn, "Processing…", async () => {
      try {
        const survey = sv.surveyId ? await S.api.patch(`/surveys/${sv.surveyId}`, body) : await S.api.post(`/projects/${project.id}/surveys`, body);
        sv.surveyId = survey.id; S.store.set(storeKey(), survey.id);
        survey.questions.forEach((q, i) => { if (sv.questions.filter((x) => x.text.trim())[i]) sv.questions.filter((x) => x.text.trim())[i].id = q.id; });
        const banner = $("#svEditing"); banner.textContent = `Saved as survey #${survey.id}.`; banner.classList.remove("hidden"); updateHint();
        mount($("#svProgress"), el("span", { class: "spinner" }), "Generating simulated answers with the local model. Saved answers appear below as they complete.");
        $("#svProgress").classList.remove("hidden");
        startPolling(survey.id);
        const res = await S.api.post(`/surveys/${survey.id}/process`, undefined, { timeout: S.api.ai.timeout() });
        const p = res.processing;
        if (p.failed) toast(`${p.created} saved, ${p.failed} failed. You can retry the failed items.`, "error");
        else toast(p.created ? `${p.created} response(s) saved.` : "All responses were already saved.", "ok");
      } catch (err) { notice(err.message, "error"); }
      finally { stopPolling(); sv.processing = false; $("#svReset").disabled = false; $("#svProgress").classList.add("hidden"); await refreshResults(); }
    });
  }

  /* ---------- history ---------- */
  function historyRow(s, reload) {
    const retryable = s.status === "partial" || s.status === "failed";
    return el("div", { class: "list-row" },
      el("div", { class: "main-line" }, el("div", { class: "title", text: s.title }),
        el("div", { class: "sub", text: `${S.projects.current().name} · ${fmtDate(s.created_at)} · ${s.question_count} questions · ${s.persona_count} personas · ${s.response_count}/${s.expected_responses} responses` })),
      el("span", { class: "row-actions" }, badge(s.status),
        el("button", { class: "button secondary small", text: "View results", onclick: () => open(s.id) }),
        retryable ? el("button", { class: "button secondary small", text: "Continue processing", onclick: async () => { await open(s.id); process(); } }) : null,
        el("button", { class: "button secondary small", text: "Download PDF", onclick: () => downloadPdf(s.id) }),
        el("button", { class: "button danger small", text: "Delete", onclick: async () => {
          if (!(await confirmDialog({ title: `Delete “${s.title}”?`, message: "The survey and all its saved responses will be removed permanently.", confirmText: "Delete survey" }))) return;
          try { await S.api.del(`/surveys/${s.id}`); if (sv.surveyId === s.id) resetForm(); toast("Survey deleted.", "ok"); reload(); } catch (e) { toast(e.message, "error"); }
        } })));
  }

  async function ensureReady() {
    if (!listenersBound) {
      listenersBound = true;
      $("#svAddQ").addEventListener("click", () => { sv.questions.push(blankQ()); renderQuestions(); });
      $("#svSelectAll").addEventListener("click", () => { sv.personaIds = new Set(sv.personas.map((p) => p.id)); renderPersonas(); });
      $("#svSelectNone").addEventListener("click", () => { sv.personaIds = new Set(); renderPersonas(); });
      $("#svProcess").addEventListener("click", process);
      $("#svReset").addEventListener("click", resetForm);
    }
    if (!sv.questions.length) sv.questions = [blankQ()];
    renderQuestions();
    if (!sv.personas.length || !sv.ready) { sv.ready = true; await loadPersonas(); }
  }

  async function show(tab) {
    if (tab === "generate") {
      await ensureReady();
      if (!sv.surveyId) {
        const saved = parseInt(S.store.get(storeKey()), 10);        // restore the last survey after a refresh
        const skip = sv.skipRestore; sv.skipRestore = false;
        if (saved && !skip) { await open(saved, { navigate: false }); return; }
      } else if (!sv.processing) { await loadPersonas(); await refreshResults(); }
      renderPersonas(); updateHint();
    } else if (tab === "history") {
      if (!historyList) historyList = S.history.create({ filtersNode: $("#shFilters"), listNode: $("#shList"), statuses: ["draft", "processing", "completed", "partial", "failed"],
        emptyText: "No surveys have been created for this project yet.", row: historyRow,
        fetch: (p) => S.api.get(`/projects/${S.projects.current().id}/surveys`, p) });
      historyList.load();
    } else S.reports.survey(sv.surveyId);
  }

  S.on("project-changed", () => {
    stopPolling();
    Object.assign(sv, { surveyId: null, questions: [blankQ()], personaIds: new Set(), personas: [], processing: false, pending: [], ready: false });
    if (listenersBound) { $("#svTitle").value = $("#svTopic").value = $("#svObjective").value = ""; $("#svEditing").classList.add("hidden"); mount($("#svResults")); }
    if (historyList) historyList.reset();
  });

  S.surveyUI = { resultsView, downloadPdf };
  S.modules.survey = {
    show, open: (id) => open(id),
    preselect(ids) {           // "Use in survey" from a persona card starts a fresh survey with that persona
      stopPolling();
      Object.assign(sv, { surveyId: null, questions: [blankQ()], personaIds: new Set(ids), pending: ids.slice(), ready: false, skipRestore: true });
      S.store.remove(storeKey());
      ["#svTitle", "#svTopic", "#svObjective"].forEach((id) => { $(id).value = ""; });
      $("#svEditing").classList.add("hidden"); mount($("#svResults"));
    },
  };
})(window.SynUser);
