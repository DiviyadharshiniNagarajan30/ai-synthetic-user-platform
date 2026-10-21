/* Reusable, backend-driven history list: search, status/date filters, pagination, loading/empty/error states. */
(function (S) {
  const { el, mount, debounce, loading, empty, errorBox, pager } = S.ui;
  const LIMIT = 10;

  function create({ filtersNode, listNode, fetch, row, statuses = [], searchPlaceholder = "Search by title…", emptyText }) {
    const state = { q: "", status: "", from: "", to: "", offset: 0, seq: 0 };
    const search = el("input", { type: "search", placeholder: searchPlaceholder, "aria-label": "Search" });
    const status = el("select", { "aria-label": "Status" }, el("option", { value: "", text: "All statuses" }),
      statuses.map((s) => el("option", { value: s, text: s })));
    const from = el("input", { type: "date", "aria-label": "From date", title: "From date" });
    const to = el("input", { type: "date", "aria-label": "To date", title: "To date" });
    const clearBtn = el("button", { class: "button secondary small", text: "Clear filters", onclick: () => {
      search.value = status.value = from.value = to.value = ""; apply(); } });
    const apply = () => { Object.assign(state, { q: search.value.trim(), status: status.value, from: from.value, to: to.value, offset: 0 }); load(); };
    search.addEventListener("input", debounce(apply, 350));
    [status, from, to].forEach((n) => n.addEventListener("change", apply));
    mount(filtersNode, search, status, from, to, clearBtn);

    async function load() {
      const my = ++state.seq;
      mount(listNode, loading("Loading history…"));
      try {
        const data = await fetch({ q: state.q, status: state.status, date_from: state.from, date_to: state.to, limit: LIMIT, offset: state.offset });
        if (my !== state.seq) return;
        if (!data.items.length) {
          const filtered = state.q || state.status || state.from || state.to;
          mount(listNode, empty(filtered ? "No records match these filters." : emptyText)); return;
        }
        mount(listNode, el("div", { class: "panel" }, data.items.map((it) => row(it, load))),
          pager({ total: data.total, limit: LIMIT, offset: state.offset, onPage: (o) => { state.offset = o; load(); } }));
      } catch (err) { if (my === state.seq) mount(listNode, errorBox(err, load)); }
    }
    return { load, reset() { search.value = status.value = from.value = to.value = ""; Object.assign(state, { q: "", status: "", from: "", to: "", offset: 0 }); } };
  }

  S.history = { create };
})(window.SynUser);
