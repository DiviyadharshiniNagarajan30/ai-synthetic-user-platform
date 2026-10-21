/* Central frontend configuration. The API URL can be changed in the UI (gear icon) or by
   defining window.SYNUSER_API_BASE before this script loads. Nothing else is hardcoded. */
window.SynUser = window.SynUser || { modules: {}, handlers: {} };
(function (S) {
  const KEY = "synuser.apiBase";
  const store = {
    get(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } },
    remove(k) { try { window.localStorage.removeItem(k); } catch (e) { /* ignore */ } },
  };
  S.store = store;
  S.config = {
    get apiBaseUrl() {
      return (store.get(KEY) || window.SYNUSER_API_BASE || "http://127.0.0.1:8000").replace(/\/+$/, "");
    },
    set apiBaseUrl(v) { store.set(KEY, String(v).trim().replace(/\/+$/, "")); },
    shortTimeoutMs: 30000,
    aiTimeoutMs: 20 * 60 * 1000,   // local models can be slow; long operations get a generous timeout
  };
  // tiny event bus
  S.on = (name, fn) => { (S.handlers[name] = S.handlers[name] || []).push(fn); };
  S.emit = (name, data) => { (S.handlers[name] || []).forEach((fn) => { try { fn(data); } catch (e) { console.error(e); } }); };
})(window.SynUser);
