/* Dashboard: every number is fetched from the backend for the selected project. */
(function (S) {
  const { el, $, mount, fmtDate, badge, loading, empty, errorBox } = S.ui;
  let seq = 0;

  function metric(label, value, hint) {
    return el("div", { class: "metric-card" }, el("span", { class: "metric-label", text: label }), el("strong", { text: String(value) }), el("small", { text: hint }));
  }
  const rows = (items, render) => items.length ? items.map(render) : null;

  async function show() {
    const project = S.projects.current(); const my = ++seq;
    $("#ovName").textContent = project.name;
    $("#ovDesc").textContent = project.product_description || "No description yet.";
    $("#ovEdit").onclick = () => S.projects.openForm(project);
    [$("#ovMetrics"), $("#ovSurveys"), $("#ovInterviews"), $("#ovActivity")].forEach((n) => mount(n, loading()));

    const id = project.id;
    const [stats, surveys, interviews, activity] = await Promise.allSettled([
      S.api.get(`/projects/${id}/statistics`),
      S.api.get(`/projects/${id}/surveys`, { limit: 5 }),
      S.api.get(`/projects/${id}/interviews`, { limit: 5 }),
      S.api.get(`/projects/${id}/activity`, { limit: 10 }),
    ]);
    if (my !== seq) return;           // user switched project/tab while loading

    if (stats.status === "fulfilled") {
      const s = stats.value;
      mount($("#ovMetrics"),
        metric("Synthetic personas", s.total_personas, `${s.persona_generations} generation run(s)`),
        metric("Completed surveys", s.completed_surveys, `${s.total_surveys} total`),
        metric("Completed interviews", s.completed_interviews, `${s.active_interviews} in progress`),
        metric("Reports generated", s.reports_generated, "PDF downloads"));
    } else mount($("#ovMetrics"), errorBox(stats.reason, show));

    const list = (res, node, kind, none) => {
      if (res.status !== "fulfilled") return mount(node, errorBox(res.reason, show));
      const items = res.value.items;
      mount(node, items.length ? items.map((it) => el("div", { class: "list-row" },
        el("div", { class: "main-line" }, el("div", { class: "title", text: it.title }),
          el("div", { class: "sub", text: kind === "survey" ? `${it.question_count} questions · ${it.response_count}/${it.expected_responses} responses · ${fmtDate(it.created_at)}`
            : `${it.persona_name || "Persona"} · ${it.message_count} messages · ${fmtDate(it.last_activity_at)}` })),
        el("span", { class: "row-actions" }, badge(it.status),
          el("button", { class: "text-button", text: "Open", onclick: () => S.modules[kind === "survey" ? "survey" : "interview"].open(it.id) }))))
        : empty(none));
    };
    list(surveys, $("#ovSurveys"), "survey", "No surveys have been created for this project yet.");
    list(interviews, $("#ovInterviews"), "interview", "No interviews have been started for this project yet.");

    if (activity.status === "fulfilled") {
      const items = activity.value.items;
      const label = { survey: "Survey", interview: "Interview", persona_generation: "Persona generation" };
      mount($("#ovActivity"), items.length ? items.map((a) => el("div", { class: "list-row" },
        el("div", { class: "main-line" }, el("div", { class: "title", text: a.title }), el("div", { class: "sub", text: `${label[a.type] || a.type} · ${fmtDate(a.timestamp)}` })),
        badge(a.status)))
        : empty("No research activity yet. Generate personas to get started.", el("button", { class: "button primary", text: "Generate personas", onclick: () => S.nav.go("personas", "generate") })));
    } else mount($("#ovActivity"), errorBox(activity.reason, show));
  }

  S.modules.overview = { show };
})(window.SynUser);
