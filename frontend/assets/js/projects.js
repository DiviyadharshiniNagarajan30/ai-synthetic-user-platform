/* Project list (sidebar), selection persistence and project CRUD. */
(function (S) {
  const { el, $, mount, toast, notice, confirmDialog, busy } = S.ui;
  const KEY = "synuser.projectId";
  const P = { list: [], loadError: null, currentId: null };

  P.current = () => P.list.find((p) => p.id === P.currentId) || null;

  P.load = async function () {
    try {
      P.list = await S.api.get("/projects/");
      P.loadError = null;
    } catch (err) {
      P.loadError = err; P.list = [];
    }
    const saved = parseInt(S.store.get(KEY), 10);
    // keep the stored selection only if it still exists in the backend
    P.currentId = P.list.some((p) => p.id === saved) ? saved : (P.list[0] ? P.list[0].id : null);
    if (P.currentId) S.store.set(KEY, P.currentId); else S.store.remove(KEY);
    P.renderSidebar(); P.renderEmpty(); updatePill();
  };

  function updatePill() {
    const c = P.current();
    $("#projectPill").textContent = c ? c.name : "No project selected";
  }

  P.renderEmpty = function () {
    const box = $("#noProject");
    if (P.loadError) {
      mount(box, el("h2", { text: "The project list could not be loaded." }), el("p", { text: P.loadError.message }),
        el("button", { class: "button primary", text: "Try again", onclick: () => P.reload() }));
    } else {
      mount(box, el("h2", { text: "Create a project to begin your research." }),
        el("p", { text: "Projects keep personas, surveys, interviews and reports together." }),
        el("button", { class: "button primary", text: "Create project", onclick: () => P.openForm() }));
    }
  };

  P.renderSidebar = function () {
    const box = $("#projectList");
    if (P.loadError) { mount(box, el("div", { class: "side-title", style: "padding:8px", text: "Could not load projects." })); return; }
    if (!P.list.length) { mount(box, el("div", { class: "side-title", style: "padding:8px", text: "No projects yet." })); return; }
    mount(box, P.list.map((p) => el("div", { class: `project-item${p.id === P.currentId ? " active" : ""}` },
      el("button", { class: "pname", text: p.name, title: p.name, "aria-current": p.id === P.currentId ? "true" : null, onclick: () => P.select(p.id) }),
      el("button", { class: "pbtn", text: "✎", title: "Edit project", "aria-label": `Edit ${p.name}`, onclick: () => P.openForm(p) }),
      el("button", { class: "pbtn", text: "✕", title: "Delete project", "aria-label": `Delete ${p.name}`, onclick: () => P.remove(p) }))));
  };

  P.select = function (id) {
    if (id === P.currentId) { S.nav.render(); return; }
    P.currentId = id;
    if (id) S.store.set(KEY, id); else S.store.remove(KEY);
    S.ui.hideNotice();
    P.renderSidebar(); updatePill();
    S.emit("project-changed", P.current());
    S.nav.render();
  };

  P.reload = async function () {
    const before = P.currentId;
    await P.load();
    if (!P.loadError) S.ui.hideNotice();          // connection restored: drop the stale error banner
    if (before !== P.currentId) S.emit("project-changed", P.current());
    S.nav.render();
  };

  P.openForm = function (project) {
    const editing = !!project;
    S.ui.modal((card, close) => {
      const f = {
        name: el("input", { required: true, maxlength: 255, value: project ? project.name : "", placeholder: "AI Personal Finance and Budgeting App" }),
        category: el("input", { maxlength: 100, value: (project && project.category) || "", placeholder: "e.g. Fintech, Health, Education" }),
        desc: el("textarea", { rows: 3, maxlength: 5000, placeholder: "What product or idea are you researching?" }),
        market: el("textarea", { rows: 2, maxlength: 2000, placeholder: "Who is it for?" }),
        obj: el("textarea", { rows: 2, maxlength: 3000, placeholder: "What do you want to learn?" }),
      };
      f.desc.value = (project && project.product_description) || "";
      f.market.value = (project && project.target_market) || "";
      f.obj.value = (project && project.research_objective) || "";
      const err = el("div", { class: "notice error hidden" });
      const save = el("button", { class: "button primary", type: "submit", text: editing ? "Save changes" : "Create project" });
      const form = el("form", { class: "form-panel", novalidate: true },
        el("label", {}, "Project name", f.name), el("label", {}, "Category", f.category),
        el("label", {}, "Description", f.desc), el("label", {}, "Target audience", f.market),
        el("label", {}, "Research objectives", f.obj), err,
        el("div", { class: "modal-actions" }, el("button", { class: "button secondary", type: "button", text: "Cancel", onclick: close }), save));
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const name = f.name.value.trim();
        if (!name) { err.textContent = "Project name is required."; err.classList.remove("hidden"); f.name.focus(); return; }
        const body = { name, category: f.category.value.trim() || null, product_description: f.desc.value.trim(),
          target_market: f.market.value.trim(), research_objective: f.obj.value.trim() };
        await busy(save, "Saving…", async () => {
          try {
            const saved = editing ? await S.api.patch(`/projects/${project.id}`, body) : await S.api.post("/projects/", body);
            close();
            await P.load();
            P.currentId = saved.id; S.store.set(KEY, saved.id);
            P.renderSidebar(); updatePill();
            S.emit("project-changed", P.current()); S.nav.render();
            toast(editing ? "Project updated." : "Project created.", "ok");
          } catch (e2) { err.textContent = e2.message; err.classList.remove("hidden"); }
        });
      });
      card.append(el("h2", { text: editing ? "Edit project" : "Create a project" }), form);
    });
  };

  P.remove = async function (project) {
    if (!(await confirmDialog({ title: `Delete “${project.name}”?`, message: "The project will be removed permanently.", confirmText: "Delete project" }))) return;
    try {
      await S.api.del(`/projects/${project.id}`);
    } catch (err) {
      if (err.code === "project_not_empty") {
        const ok = await confirmDialog({ title: "Delete project and all its research?", message: err.message, confirmText: "Delete everything" });
        if (!ok) return;
        try { await S.api.del(`/projects/${project.id}`, { force: true }); }
        catch (e2) { toast(e2.message, "error"); return; }
      } else { toast(err.message, "error"); return; }
    }
    toast("Project deleted.", "ok");
    await P.reload();
  };

  S.projects = P;
  $("#newProjectBtn").addEventListener("click", () => P.openForm());
})(window.SynUser);
