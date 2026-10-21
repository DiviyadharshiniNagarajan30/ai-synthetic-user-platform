/* Sidebar pages + contextual top tabs. The route lives in the URL hash so a refresh keeps your place. */
(function (S) {
  const { $, $$, el, mount } = S.ui;
  const PAGES = {
    overview: { title: "Overview", tabs: [["dashboard", "Dashboard"]] },
    personas: { title: "Persona Generation", tabs: [["generate", "Generate"], ["history", "History"], ["report", "Report"]] },
    survey: { title: "Survey", tabs: [["generate", "Generate"], ["history", "History"], ["report", "Report"]] },
    interview: { title: "Interview", tabs: [["start", "Start Interview"], ["history", "History"], ["report", "Report"]] },
  };
  const state = { page: "overview", tab: "dashboard" };

  function parse() {
    const [page, tab] = (location.hash.replace(/^#\/?/, "") || "overview/dashboard").split("/");
    const cfg = PAGES[page] || PAGES.overview;
    const key = PAGES[page] ? page : "overview";
    const valid = cfg.tabs.some(([id]) => id === tab);
    return { page: key, tab: valid ? tab : cfg.tabs[0][0] };
  }

  let skipNextHashChange = false;
  function go(page, tab) {
    const target = `#/${page}/${tab || PAGES[page].tabs[0][0]}`;
    if (location.hash !== target) { skipNextHashChange = true; location.hash = target; }
    render();                                   // render synchronously so the UI never lags the click
  }

  function render() {
    Object.assign(state, parse());
    const cfg = PAGES[state.page];
    $("#pageTitle").textContent = cfg.title;
    $$(".side-link").forEach((b) => b.classList.toggle("active", b.dataset.page === state.page));
    mount($("#topTabs"), cfg.tabs.map(([id, label]) =>
      el("button", { class: `nav-tab${id === state.tab ? " active" : ""}`, text: label, "aria-current": id === state.tab ? "page" : null,
        onclick: () => go(state.page, id) })));
    $("#sidebar").classList.remove("open");

    const hasProject = !!S.projects.current();
    $("#noProject").classList.toggle("hidden", hasProject);
    $$(".page").forEach((p) => p.classList.toggle("hidden", !hasProject || p.id !== `page-${state.page}`));
    if (!hasProject) return;
    $$(`#page-${state.page} .tab-panel`).forEach((p) => p.classList.toggle("hidden", p.dataset.tab !== state.tab));
    const mod = S.modules[state.page];
    if (mod && mod.show) mod.show(state.tab);
  }

  S.nav = { go, render, state, PAGES };
  window.addEventListener("hashchange", () => { if (skipNextHashChange) { skipNextHashChange = false; return; } render(); });  // back/forward/manual edits
  document.addEventListener("click", (e) => {
    const g = e.target.closest("[data-goto]");
    if (g) { const [p, t] = g.dataset.goto.split("/"); go(p, t); }
    const a = e.target.closest("[data-action='new-project']");
    if (a) S.projects.openForm();
    const l = e.target.closest(".side-link");
    if (l) go(l.dataset.page);
  });
})(window.SynUser);
