/* Report tabs for surveys and interviews: preview saved data, optional AI summary, real PDF download. */
(function (S) {
  const { el, $, mount, toast, fmtDate, badge, synthetic, loading, empty, errorBox, personaLine, busy } = S.ui;

  function kv(rows) {
    return el("dl", { class: "kv" }, rows.filter(([, v]) => v !== null && v !== undefined && v !== "").map(([k, v]) => [el("dt", { text: k }), el("dd", { text: String(v) })]));
  }
  const projectPanel = (p) => el("div", { class: "panel" }, el("h2", { text: "Project details" }),
    kv([["Project", p.name], ["Category", p.category], ["Description", p.description], ["Target audience", p.target_market], ["Objective", p.research_objective]]));

  function summaryPanel(s, extra) {
    return el("div", { class: "panel" }, el("h2", { text: "AI-generated summary" }),
      el("p", { class: "muted", text: s.disclaimer }), el("p", { text: s.summary }),
      extra || null, s.themes && s.themes.length ? el("ul", {}, s.themes.map((t) => el("li", { text: t }))) : null);
  }
  function summaryLists(s) {
    return [["Main needs", s.needs], ["Preferences", s.preferences], ["Pain points", s.pain_points], ["Recommendations", s.recommendations]]
      .filter(([, l]) => l && l.length).map(([t, l]) => el("div", {}, el("h3", { text: t }), el("ul", {}, l.map((x) => el("li", { text: x })))));
  }

  async function picker(select, fetchItems, label, currentId, onPick, noneText, container) {
    let items;
    try { items = (await fetchItems()).items; } catch (err) { mount(container, errorBox(err)); mount(select); return; }
    if (!items.length) { mount(select); select.classList.add("hidden"); mount(container, empty(noneText)); return; }
    select.classList.remove("hidden");
    const pick = items.some((i) => i.id === currentId) ? currentId : items[0].id;
    mount(select, items.map((i) => el("option", { value: i.id, text: `${i.title} (${i.status})`, selected: i.id === pick })));
    select.onchange = () => onPick(Number(select.value));
    onPick(pick);
  }

  /* ---------- survey ---------- */
  async function survey(currentId) {
    const box = $("#srBody"); const pid = S.projects.current().id;
    mount(box, loading("Loading surveys…"));
    await picker($("#srPick"), () => S.api.get(`/projects/${pid}/surveys`, { limit: 100 }), "survey", currentId, loadSurveyReport,
      "No surveys have been created for this project yet.", box);
  }
  async function loadSurveyReport(id) {
    const box = $("#srBody"); mount(box, loading("Building report…"));
    try {
      const r = await S.api.get(`/surveys/${id}/results`);
      const withSummary = el("input", { type: "checkbox", id: "srSummary" });
      const summaryBox = el("div");
      const aiBtn = el("button", { class: "button secondary small", text: "Generate AI summary", onclick: () => busy(aiBtn, "Summarising…", async () => {
        mount(summaryBox, loading("Asking the local model…"));
        try { mount(summaryBox, summaryPanel(await S.api.post(`/surveys/${id}/summary`, undefined, { timeout: S.api.ai.timeout() }))); }
        catch (e) { mount(summaryBox, errorBox(e)); }
      }) });
      mount(box,
        el("div", { class: "panel" }, el("div", { class: "results-head" }, el("div", {}, el("h2", { text: r.survey_title }), el("div", { class: "muted", text: `Generated from saved records · ${fmtDate(r.completed_at || r.created_at)}` })),
          badge(r.status)),
          kv([["Research objective", r.research_objective], ["Research topic", r.research_topic], ["Created", fmtDate(r.created_at)], ["Completed", r.completed_at ? fmtDate(r.completed_at) : null],
            ["Responses", `${r.total_responses} of ${r.expected_responses}`]]),
          el("div", { class: "row-actions", style: "margin-top:14px" },
            el("button", { class: "button primary", text: "Download PDF", onclick: (e) => busy(e.currentTarget, "Preparing PDF…", () => S.surveyUI.downloadPdf(id, withSummary.checked ? { include_summary: true } : null)) }),
            el("label", { class: "check-inline", style: "padding:0" }, withSummary, "Include AI summary in the PDF"), aiBtn)),
        summaryBox, projectPanel(r.project),
        el("div", { class: "panel" }, el("h2", { text: "Questions" }), el("ol", {}, r.results.map((q) => el("li", { text: q.question_text })))),
        el("div", { class: "panel" }, el("h2", { text: "Participating personas" }), r.personas.map((p) => el("div", { class: "list-row" },
          el("div", { class: "main-line" }, el("div", { class: "title", text: p.name }, " ", synthetic()), el("div", { class: "sub", text: personaLine(p) || "No details" }),
            p.goals ? el("div", { class: "sub", text: `Goals: ${p.goals}` }) : null, p.pain_points ? el("div", { class: "sub", text: `Pain points: ${p.pain_points}` }) : null)))),
        S.surveyUI.resultsView(r));
    } catch (err) { mount(box, errorBox(err, () => loadSurveyReport(id))); }
  }

  /* ---------- interview ---------- */
  async function interview(currentId) {
    const box = $("#irBody"); const pid = S.projects.current().id;
    mount(box, loading("Loading interviews…"));
    await picker($("#irPick"), () => S.api.get(`/projects/${pid}/interviews`, { limit: 100 }), "interview", currentId, loadInterviewReport,
      "No interviews have been started for this project yet.", box);
  }
  async function loadInterviewReport(id) {
    const box = $("#irBody"); mount(box, loading("Building report…"));
    try {
      const d = await S.api.get(`/interviews/${id}`); const p = d.persona;
      const withSummary = el("input", { type: "checkbox" }); const summaryBox = el("div");
      const aiBtn = el("button", { class: "button secondary small", text: "Generate AI summary", onclick: () => busy(aiBtn, "Summarising…", async () => {
        mount(summaryBox, loading("Asking the local model…"));
        try { const s = await S.api.post(`/interviews/${id}/summary`, undefined, { timeout: S.api.ai.timeout() }); mount(summaryBox, summaryPanel({ ...s, themes: [] }, summaryLists(s))); }
        catch (e) { mount(summaryBox, errorBox(e)); }
      }) });
      mount(box,
        el("div", { class: "panel" }, el("div", { class: "results-head" }, el("div", {}, el("h2", { text: d.title }), el("div", { class: "muted", text: `${d.message_count} messages · last activity ${fmtDate(d.last_activity_at)}` })), badge(d.status)),
          kv([["Research topic", d.research_topic], ["Objective", d.research_objective], ["Interview guide", d.interview_guide], ["Started", fmtDate(d.created_at)], ["Completed", d.completed_at ? fmtDate(d.completed_at) : null]]),
          el("div", { class: "row-actions", style: "margin-top:14px" },
            el("button", { class: "button primary", text: "Download PDF", onclick: (e) => busy(e.currentTarget, "Preparing PDF…", async () => {
              try { const o = await S.api.download(`/interviews/${id}/report.pdf`, withSummary.checked ? { include_summary: true } : null, `interview-${id}.pdf`); toast(o.warning ? `PDF downloaded. ${o.warning}` : "PDF downloaded.", "ok"); }
              catch (er) { toast(er.message, "error"); } }) }),
            el("label", { class: "check-inline", style: "padding:0" }, withSummary, "Include AI summary in the PDF"), aiBtn)),
        summaryBox, projectPanel(d.project),
        el("div", { class: "panel" }, el("h2", {}, "Persona profile ", synthetic()), kv([["Name", p.name], ["Age", p.age], ["Occupation", p.occupation], ["Location", p.location], ["Experience", p.experience_level],
          ["Personality", p.personality], ["Goals", p.goals], ["Preferences", p.preferences], ["Pain points", p.pain_points]])),
        el("div", { class: "panel" }, el("h2", { text: "Transcript" }), d.messages.length ? el("div", { class: "chat-messages", style: "max-height:none;background:#fff;padding:0" },
          d.messages.map((m) => el("div", { class: `msg ${m.role}` }, el("small", { text: `${m.role === "researcher" ? "Researcher" : p.name} · #${m.sequence_number}` }), m.message_text))) : empty("No messages were exchanged.")),
        el("p", { class: "fine-print", text: d.disclaimer }));
    } catch (err) { mount(box, errorBox(err, () => loadInterviewReport(id))); }
  }

  S.reports = { survey, interview };
})(window.SynUser);
