/* Persona generation, library (search/filter/edit/delete), generation history and persona report. */
(function (S) {
  const { el, $, mount, toast, notice, busy, fmtDate, badge, synthetic, loading, empty, errorBox, confirmDialog, personaLine, debounce } = S.ui;
  const DEFAULT_OCC = ["College student", "Software developer", "Teacher", "Healthcare professional", "Business owner",
    "Manager", "Accountant", "Freelancer", "Homemaker", "Retired individual"];
  const selectedOcc = new Set();
  let libSeq = 0, libOffset = 0, historyList = null, initialised = false;
  const LIB_LIMIT = 12;

  const val = (id) => $(id).value.trim();
  const num = (id) => { const v = $(id).value; return v === "" ? null : Number(v); };

  /* ---------- shared persona UI (also used by surveys/interviews) ---------- */
  function field(label, value) {
    return value ? [el("dt", { text: label }), el("dd", { text: value })] : null;
  }
  function card(p, { onChange, compact = false } = {}) {
    const actions = compact ? null : el("div", { class: "card-actions" },
      el("button", { class: "button secondary small", text: "View details", onclick: () => openDetail(p.id, onChange) }),
      el("button", { class: "button secondary small", text: "Use in survey", onclick: () => { S.modules.survey.preselect([p.id]); S.nav.go("survey", "generate"); } }),
      el("button", { class: "button secondary small", text: "Interview", onclick: () => { S.modules.interview.preselect(p.id); S.nav.go("interview", "start"); } }),
      el("button", { class: "button danger small", text: "Delete", onclick: () => removePersona(p, onChange) }));
    return el("article", { class: "persona-card" },
      el("header", {}, el("div", {}, el("h3", { text: p.name }), el("div", { class: "role", text: personaLine(p) || "No occupation or age recorded" })), synthetic()),
      el("dl", {}, field("Goals", p.goals), field("Pain points", p.pain_points), field("Preferences", p.preferences)), actions);
  }

  async function removePersona(p, onChange) {
    if (!(await confirmDialog({ title: `Delete ${p.name}?`, message: "This synthetic persona will be removed permanently.", confirmText: "Delete persona" }))) return;
    try {
      try { await S.api.del(`/personas/${p.id}`); }
      catch (e) {
        if (e.code !== "persona_in_use") throw e;
        if (!(await confirmDialog({ title: "Delete persona and its research?", message: e.message, confirmText: "Delete everything" }))) return;
        await S.api.del(`/personas/${p.id}`, { force: true });
      }
      toast("Persona deleted.", "ok");
      if (onChange) onChange(); else loadLibrary();
    } catch (e) { toast(e.message, "error"); }
  }

  function personaForm(p, onSaved, close) {
    const fields = [["name", "Name", "input"], ["age", "Age", "input", "number"], ["occupation", "Occupation", "input"], ["income", "Monthly income (INR)", "input", "number"],
      ["location", "Location", "input"], ["experience_level", "Experience level", "input"], ["personality", "Personality", "textarea"],
      ["goals", "Goals", "textarea"], ["preferences", "Preferences", "textarea"], ["pain_points", "Pain points", "textarea"], ["research_interests", "Research interests", "textarea"]];
    const inputs = {};
    const err = el("div", { class: "notice error hidden" });
    const save = el("button", { class: "button primary", type: "submit", text: p ? "Save changes" : "Add persona" });
    const form = el("form", { class: "form-panel", novalidate: true },
      fields.map(([k, label, tag, type]) => {
        inputs[k] = el(tag, { type, rows: tag === "textarea" ? 2 : null, min: type === "number" ? 0 : null });
        inputs[k].value = p && p[k] !== null && p[k] !== undefined ? p[k] : "";
        return el("label", {}, label, inputs[k]);
      }), err,
      el("div", { class: "modal-actions" }, el("button", { class: "button secondary", type: "button", text: "Cancel", onclick: close }), save));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = {};
      fields.forEach(([k, , , type]) => { const v = inputs[k].value.trim(); body[k] = type === "number" ? (v === "" ? null : Number(v)) : v; });
      if (!body.name) { err.textContent = "Name is required."; err.classList.remove("hidden"); return; }
      await busy(save, "Saving…", async () => {
        try {
          if (p) await S.api.patch(`/personas/${p.id}`, body);
          else await S.api.post(`/projects/${S.projects.current().id}/personas`, body);
          close(); toast(p ? "Persona updated." : "Persona added.", "ok"); onSaved();
        } catch (e2) { err.textContent = e2.message; err.classList.remove("hidden"); }
      });
    });
    return form;
  }

  async function openDetail(id, onChange) {
    let p;
    try { p = await S.api.get(`/personas/${id}`); } catch (e) { toast(e.message, "error"); return; }
    S.ui.modal((cardEl, close) => {
      const show = () => {
        const rows = [["Age", p.age], ["Occupation", p.occupation], ["Monthly income (INR)", p.income], ["Location", p.location],
          ["Experience", p.experience_level], ["Personality", p.personality], ["Goals", p.goals], ["Preferences", p.preferences],
          ["Pain points", p.pain_points], ["Research interests", p.research_interests], ["Created", fmtDate(p.created_at)]];
        if (p.behavior) Object.entries(p.behavior).forEach(([k, v]) => v !== null && rows.push([k.replace(/_/g, " ") + " (1-5)", v]));
        mount(cardEl, el("div", { class: "row-actions", style: "justify-content:space-between" }, el("h2", { text: p.name }), synthetic()),
          el("p", { class: "muted", text: "AI-generated synthetic persona — not a real person." }),
          el("dl", { class: "kv" }, rows.filter(([, v]) => v !== null && v !== undefined && v !== "").map(([k, v]) => [el("dt", { text: k }), el("dd", { text: String(v) })])),
          el("div", { class: "modal-actions" },
            el("button", { class: "button secondary", text: "Edit", onclick: () => mount(cardEl, el("h2", { text: `Edit ${p.name}` }),
              personaForm(p, () => { (onChange || loadLibrary)(); }, close)) }),
            el("button", { class: "button primary", text: "Close", onclick: close })));
      };
      show();
    }, { wide: true });
  }

  /* ---------- generate tab ---------- */
  function initForm() {
    if (initialised) return; initialised = true;
    mount($("#pgOccupations"), DEFAULT_OCC.map((o) => el("button", { type: "button", class: "chip", text: o, "aria-pressed": "false", onclick: (e) => {
      if (selectedOcc.has(o)) selectedOcc.delete(o); else selectedOcc.add(o);
      e.currentTarget.classList.toggle("on", selectedOcc.has(o)); e.currentTarget.setAttribute("aria-pressed", selectedOcc.has(o)); } })));
    $("#personaForm").addEventListener("submit", submit);
    $("#plSearch").addEventListener("input", debounce(() => { libOffset = 0; loadLibrary(); }, 350));
    $("#plOccupation").addEventListener("change", () => { libOffset = 0; loadLibrary(); });
    $("#plManual").addEventListener("click", () => S.ui.modal((c, close) => c.append(el("h2", { text: "Add a persona manually" }),
      el("p", { class: "muted", text: "Manually entered personas are still treated as synthetic research inputs." }), personaForm(null, loadLibrary, close)), { wide: true }));
  }

  async function submit(e) {
    e.preventDefault();
    const project = S.projects.current();
    const count = num("#pgCount");
    if (!count || count < 1 || count > 20) { notice("Choose between 1 and 20 personas per request.", "warn"); return; }
    const a = num("#pgAgeMin"), b = num("#pgAgeMax");
    if (a && b && a > b) { notice("The minimum age cannot be greater than the maximum age.", "warn"); return; }
    const body = {
      count, research_topic: val("#pgTopic") || null, product_context: val("#pgContext") || null,
      occupations: Array.from(selectedOcc), custom_occupation: val("#pgCustomOcc") || null,
      age_min: a, age_max: b, include_income: $("#pgIncomeOn").checked, income_min: num("#pgIncMin"), income_max: num("#pgIncMax"),
      experience_level: val("#pgExperience") || null, location: val("#pgLocation") || null, personality: val("#pgPersonality") || null,
      goals: val("#pgGoals") || null, preferences: val("#pgPrefs") || null, pain_points: val("#pgPains") || null,
      custom_instructions: val("#pgInstructions") || null, include_behavior_scores: $("#pgScores").checked,
    };
    S.ui.hideNotice();
    const progress = $("#pgProgress");
    mount(progress, el("span", { class: "spinner" }), `Generating ${count} persona${count > 1 ? "s" : ""} with the local model. Each persona can take up to a minute — keep this page open.`);
    progress.classList.remove("hidden");
    mount($("#pgResult"));
    await busy($("#pgSubmit"), "Generating…", async () => {
      try {
        const res = await S.api.post(`/projects/${project.id}/personas/generate`, body, { timeout: S.api.ai.timeout() });
        if (S.projects.current().id !== project.id) return;
        const g = res.generation;
        mount($("#pgResult"), el("div", { class: "panel" },
          el("div", { class: "results-head" }, el("h2", { text: `Generated ${g.created_count} of ${g.requested_count} persona(s)` }), badge(g.status)),
          res.errors.length ? el("div", { class: "notice warn" }, el("span", { text: "Some personas could not be generated: " + res.errors.join(" · ") })) : null,
          el("div", { class: "persona-grid" }, g.personas.map((p) => card(p, { onChange: loadLibrary })))));
        toast(`${g.created_count} persona(s) saved.`, "ok");
      } catch (err) { notice(err.message, "error"); }
      finally { progress.classList.add("hidden"); loadLibrary(); }
    });
  }

  async function loadLibrary() {
    const project = S.projects.current(); const my = ++libSeq;
    const grid = $("#plGrid");
    mount(grid, loading("Loading personas…")); mount($("#plMore"));
    try {
      const data = await S.api.get(`/projects/${project.id}/personas`, { q: val("#plSearch"), occupation: $("#plOccupation").value, limit: LIB_LIMIT, offset: libOffset });
      if (my !== libSeq) return;
      const sel = $("#plOccupation"), cur = sel.value;
      mount(sel, el("option", { value: "", text: "All occupations" }), data.occupations.map((o) => el("option", { value: o, text: o, selected: o === cur })));
      $("#plSubtitle").textContent = `${data.total} persona${data.total === 1 ? "" : "s"} in this project.`;
      if (!data.items.length) {
        mount(grid, el("div", { class: "state-box", style: "grid-column:1/-1" }, val("#plSearch") || cur ? "No personas match your search." : "Generate synthetic personas for this project before starting a survey or interview."));
        return;
      }
      mount(grid, data.items.map((p) => card(p, { onChange: loadLibrary })));
      mount($("#plMore"), S.ui.pager({ total: data.total, limit: LIB_LIMIT, offset: libOffset, onPage: (o) => { libOffset = o; loadLibrary(); } }));
    } catch (err) { if (my === libSeq) mount(grid, errorBox(err, loadLibrary)); }
  }

  /* ---------- history tab ---------- */
  function generationRow(g) {
    const c = g.criteria || {};
    const bits = [c.custom_occupation, (c.occupations || []).join(", "), c.age_min || c.age_max ? `age ${c.age_min || "…"}–${c.age_max || "…"}` : null, c.location, c.research_topic].filter(Boolean);
    const body = el("div", { class: "persona-grid hidden", style: "margin-top:12px" }, g.personas.map((p) => card(p, { compact: true })));
    const toggle = el("button", { class: "text-button", text: `View ${g.personas.length} persona(s)`, onclick: () => {
      body.classList.toggle("hidden"); toggle.textContent = body.classList.contains("hidden") ? `View ${g.personas.length} persona(s)` : "Hide personas"; } });
    return el("div", { class: "list-row", style: "display:block" },
      el("div", { class: "list-row", style: "border:0;padding:0" },
        el("div", { class: "main-line" }, el("div", { class: "title", text: `${g.created_count} of ${g.requested_count} personas · ${fmtDate(g.created_at)}` }),
          el("div", { class: "sub", text: bits.length ? bits.join(" · ") : "No specific criteria" + (g.model_name ? ` · model ${g.model_name}` : "") })),
        el("span", { class: "row-actions" }, badge(g.status), g.personas.length ? toggle : null)),
      g.error_message ? el("div", { class: "sub", style: "color:#8a2a20;margin-top:6px", text: g.error_message }) : null,
      g.personas.length ? body : null);
  }
  function showHistory() {
    if (!historyList) historyList = S.history.create({ filtersNode: $("#pghFilters"), listNode: $("#pghList"), statuses: ["completed", "partial", "failed"],
      searchPlaceholder: "Search disabled for generations", emptyText: "No personas have been generated for this project yet.",
      fetch: (p) => S.api.get(`/projects/${S.projects.current().id}/persona-generations`, { status: p.status, date_from: p.date_from, date_to: p.date_to, limit: p.limit, offset: p.offset }),
      row: generationRow });
    $("#pghFilters input[type=search]").classList.add("hidden");
    historyList.load();
  }

  /* ---------- report tab ---------- */
  async function showReport() {
    const body = $("#prBody"); mount(body, loading("Building report…"));
    try {
      const data = await S.api.get(`/projects/${S.projects.current().id}/personas`, { limit: 500 });
      const ps = data.items;
      if (!ps.length) { mount(body, empty("Generate synthetic personas for this project before building a report.", el("button", { class: "button primary", text: "Generate personas", onclick: () => S.nav.go("personas", "generate") }))); return; }
      const ages = ps.map((p) => p.age).filter((a) => a), incomes = ps.map((p) => p.income).filter((i) => i !== null && i !== undefined);
      const avg = (a) => a.length ? Math.round(a.reduce((x, y) => x + y, 0) / a.length) : "—";
      const tally = (key) => { const m = {}; ps.forEach((p) => { const k = p[key] || "Not specified"; m[k] = (m[k] || 0) + 1; }); return Object.entries(m).sort((x, y) => y[1] - x[1]); };
      const bars = (pairs) => pairs.map(([k, n]) => el("div", { class: "list-row" }, el("div", { class: "main-line" }, el("div", { class: "title", text: k }),
        el("div", { class: "bar" }, el("i", { style: `width:${Math.round((n / ps.length) * 100)}%` }))), el("strong", { text: String(n) })));
      mount(body,
        el("div", { class: "metric-grid" }, ...[["Personas", ps.length], ["Average age", avg(ages)], ["Age range", ages.length ? `${Math.min(...ages)}–${Math.max(...ages)}` : "—"], ["Average income (INR/mo)", avg(incomes)]]
          .map(([l, v]) => el("div", { class: "metric-card" }, el("span", { class: "metric-label", text: l }), el("strong", { text: String(v) })))),
        el("div", { class: "two-col" }, el("div", { class: "panel" }, el("h2", { text: "By occupation" }), bars(tally("occupation"))),
          el("div", { class: "panel" }, el("h2", { text: "By location" }), bars(tally("location")))),
        el("div", { class: "panel" }, el("div", { class: "results-head" }, el("h2", { text: "Pain points and goals" }),
          el("button", { class: "button secondary small", text: "Export CSV", onclick: () => exportCsv(ps) })),
          ps.map((p) => el("div", { class: "answer" }, el("div", { class: "who", text: p.name }, " ", el("span", { text: personaLine(p) })),
            el("blockquote", { text: `Goals: ${p.goals || "—"}\nPain points: ${p.pain_points || "—"}` })))),
        el("p", { class: "fine-print", text: "Synthetic personas generated by a language model; not representative of a real population." }));
    } catch (err) { mount(body, errorBox(err, showReport)); }
  }
  function exportCsv(ps) {
    const cols = ["name", "age", "occupation", "income", "location", "experience_level", "personality", "goals", "preferences", "pain_points", "research_interests"];
    const q = (v) => `"${String(v === null || v === undefined ? "" : v).replace(/"/g, '""')}"`;
    const csv = "\ufeff" + [cols.join(",")].concat(ps.map((p) => cols.map((c) => q(p[c])).join(","))).join("\r\n");
    const a = el("a", { href: URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" })), download: "synuser-personas.csv" });
    document.body.append(a); a.click(); a.remove();
  }

  function show(tab) {
    initForm();
    if (tab === "generate") { $("#pgContext").placeholder = S.projects.current().product_description || "Defaults to the project description"; loadLibrary(); }
    else if (tab === "history") showHistory();
    else showReport();
  }
  S.on("project-changed", () => {
    libOffset = 0;
    if (initialised) { $("#plSearch").value = ""; mount($("#plOccupation"), el("option", { value: "", text: "All occupations" })); mount($("#pgResult")); }
    if (historyList) historyList.reset();
  });

  S.personaUI = { card, openDetail };
  S.modules.personas = { show };
})(window.SynUser);
