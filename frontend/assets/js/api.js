/* One fetch helper for every backend call. Errors are never swallowed into empty data. */
(function (S) {
  class ApiError extends Error {
    constructor(message, { status = 0, code = "", network = false, data = null } = {}) {
      super(message);
      this.status = status; this.code = code; this.network = network; this.data = data;
    }
  }

  function buildUrl(path, params) {
    const url = new URL(S.config.apiBaseUrl + path);
    Object.entries(params || {}).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
    });
    return url.toString();
  }

  async function raw(method, path, { body, params, timeout } = {}) {
    const ctrl = new AbortController();
    const ms = timeout || S.config.shortTimeoutMs;
    const timer = setTimeout(() => ctrl.abort(), ms);
    let res;
    try {
      res = await fetch(buildUrl(path, params), {
        method, signal: ctrl.signal,
        headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch (err) {
      clearTimeout(timer);
      if (err && err.name === "AbortError") {
        throw new ApiError(`The request took longer than ${Math.round(ms / 1000)} seconds and was cancelled. Check the backend log; saved data is not lost.`, { network: true, code: "timeout" });
      }
      throw new ApiError(`Cannot reach the backend at ${S.config.apiBaseUrl}. Start it with "uvicorn app.main:app --port 8000" or fix the URL in settings.`, { network: true, code: "unreachable" });
    }
    clearTimeout(timer);
    if (!res.ok) {
      let data = null;
      try { data = await res.json(); } catch (e) { /* non-JSON error body */ }
      let message = data && typeof data.detail === "string" ? data.detail : `Request failed (HTTP ${res.status}).`;
      if (data && Array.isArray(data.detail)) message = data.detail.map((d) => d.msg).join("; ");
      throw new ApiError(message, { status: res.status, code: (data && data.code) || "", data });
    }
    return res;
  }

  async function json(method, path, opts) {
    const res = await raw(method, path, opts);
    try { return await res.json(); } catch (e) { throw new ApiError("The backend returned an unreadable response."); }
  }

  async function download(path, params, fallbackName) {
    const res = await raw("GET", path, { params, timeout: S.config.aiTimeoutMs });
    const blob = await res.blob();
    const disp = res.headers.get("Content-Disposition") || "";
    const m = /filename="?([^";]+)"?/i.exec(disp);
    const name = (m && m[1]) || fallbackName || "report.pdf";
    const a = document.createElement("a");
    const href = URL.createObjectURL(blob);
    a.href = href; a.download = name; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(href), 4000);
    return { name, warning: res.headers.get("X-Report-Warning"), size: blob.size, type: blob.type };
  }

  S.ApiError = ApiError;
  S.api = {
    get: (p, params, opts) => json("GET", p, { params, ...(opts || {}) }),
    post: (p, body, opts) => json("POST", p, { body: body === undefined ? {} : body, ...(opts || {}) }),
    patch: (p, body, opts) => json("PATCH", p, { body, ...(opts || {}) }),
    del: (p, params) => json("DELETE", p, { params }),
    download,
    ai: { timeout: () => S.config.aiTimeoutMs },
  };
})(window.SynUser);
