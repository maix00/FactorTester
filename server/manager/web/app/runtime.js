(() => {
  function create() {
    const state = {
      session: null, token: "", modules: [], report: null,
      languagePreference: "system",
      tabs: [], activeTabID: "home", tabSessions: new Map(),
      referenceSnapshots: new Map(),
      pendingScrollCapture: null,
    };
    const content = document.querySelector("#content");
    const title = document.querySelector("#page-title");
    const eyebrow = document.querySelector("#page-eyebrow");
    const toolbar = document.querySelector("#page-toolbar");
    const notice = document.querySelector("#notice");

    const savedToken = () =>
      localStorage.getItem("ft-session") || sessionStorage.getItem("ft-session") || "";

    const readOnlyRetryDelays = [150, 400, 900];

    function readOnlyMethod(options) {
      return String(options.method || "GET").toUpperCase();
    }

    function retryableNetworkError(error, method, signal) {
      if (!["GET", "HEAD", "OPTIONS"].includes(method) || signal?.aborted) {
        return false;
      }
      // WebKit reports a dropped connection as either TypeError/Load failed
      // or NetworkError.  A hot-reloaded local Manager can briefly close all
      // in-flight GETs; never retry mutations because they may not be safe.
      return error?.name === "TypeError" || error?.name === "NetworkError";
    }

    async function fetchReadOnly(path, options, headers) {
      const method = readOnlyMethod(options);
      const retry = ["GET", "HEAD", "OPTIONS"].includes(method);
      for (let attempt = 0; ; attempt += 1) {
        try {
          const response = await fetch(path, {...options, headers});
          if (retry && [502, 503, 504].includes(response.status)
              && attempt < readOnlyRetryDelays.length) {
            await new Promise(resolve => setTimeout(
              resolve, readOnlyRetryDelays[attempt],
            ));
            continue;
          }
          return response;
        } catch (error) {
          if (!retryableNetworkError(error, method, options.signal)
              || attempt >= readOnlyRetryDelays.length) {
            throw error;
          }
          await new Promise(resolve => setTimeout(
            resolve, readOnlyRetryDelays[attempt],
          ));
        }
      }
    }

    async function api(path, options = {}) {
      if (isLocalCatalogPath(path)) {
        const handler = localCatalogHandler();
        if (!handler?.postMessage) {
          const error = new Error("client-local catalog is unavailable");
          error.status = 404;
          error.path = path;
          throw error;
        }
        const value = await handler.postMessage({
          action: "request",
          path: String(path),
          method: String(options.method || "GET").toUpperCase(),
          body: typeof options.body === "string" ? options.body : "",
        });
        return value && typeof value === "object" ? value : {};
      }
      const headers = new Headers(options.headers || {});
      if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
      if (options.body && !headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json");
      }
      const response = await fetchReadOnly(path, options, headers);
      const value = response.status === 204 ? {} : await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error(value.error || `HTTP ${response.status}`);
        error.status = response.status;
        error.code = value.code || "";
        error.detail = value.detail || "";
        error.details = value.details || null;
        error.candidates = value.candidates || value.failures || null;
        error.payload = value;
        error.redirect = value.redirect || "";
        error.path = path;
        throw error;
      }
      return value;
    }

    function isLocalCatalogPath(path) {
      const value = String(path || "");
      return value.startsWith("/api/client/product")
        || value.startsWith("/api/client/contract_tree");
    }

    function localCatalogHandler() {
      return window.webkit?.messageHandlers?.factorTesterLocalCatalog;
    }

    async function raw(path, options = {}) {
      const headers = new Headers(options.headers || {});
      if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
      const response = await fetchReadOnly(path, options, headers);
      if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try { message = (await response.json()).error || message; } catch (_) {}
        const error = new Error(message);
        error.status = response.status;
        error.path = path;
        throw error;
      }
      return response;
    }

    const noticeQueue = createNoticeQueue(notice);
    const showNotice = (message, isError = false) =>
      noticeQueue.enqueue(message, isError);

    function setHeading(name, scope = "FTClient") {
      title.textContent = name;
      eyebrow.textContent = scope;
      toolbar.replaceChildren();
    }

    function button(label, action, help = label) {
      const item = document.createElement("button");
      item.textContent = label;
      item.title = help;
      item.addEventListener("click", action);
      return item;
    }

    return Object.freeze({
      state, content, title, eyebrow, toolbar, notice,
      savedToken, api, raw, showNotice, setHeading, button,
    });
  }

  function createNoticeQueue(container, options = {}) {
    const now = options.now || Date.now;
    const schedule = options.setTimeout || setTimeout;
    const cancel = options.clearTimeout || clearTimeout;
    const recent = new Map();
    const active = [];
    let nextID = 0;
    const maxVisible = 5;
    const repeatWindowMS = 10000;

    function dismiss(id) {
      const index = active.findIndex(entry => entry.id === id);
      if (index < 0) return;
      const [entry] = active.splice(index, 1);
      cancel(entry.timer);
      recent.set(entry.key, now());
      entry.element.remove();
    }

    function enqueue(message, isError = false) {
      const value = String(message || "").trim();
      // Empty messages used to clear the old inline banner. A transient queue
      // expires independently; clearing it during navigation would lose useful
      // feedback from the preceding action.
      if (!value || !container) return null;
      const key = `${Boolean(isError) ? "error" : "info"}:${value}`;
      const existing = active.find(entry => entry.key === key);
      if (existing) return existing.id; // Never extend a repeatedly fired notice.
      const current = now();
      if (current - (recent.get(key) ?? -Infinity) < repeatWindowMS) return null;
      for (const [oldKey, at] of recent) {
        if (current - at >= repeatWindowMS) recent.delete(oldKey);
      }

      const element = document.createElement("div");
      element.className = `notice-item${isError ? " is-error" : ""}`;
      if (isError) element.setAttribute("role", "alert");
      const body = document.createElement("span");
      body.className = "notice-item-text";
      body.textContent = value;
      const close = document.createElement("button");
      close.type = "button";
      close.className = "notice-item-close";
      close.setAttribute("aria-label", "关闭消息");
      close.textContent = "×";
      const id = ++nextID;
      close.addEventListener("click", () => dismiss(id));
      element.append(body, close);
      container.prepend(element);
      const timer = schedule(() => dismiss(id), isError ? 8000 : 5000);
      active.unshift({id, key, element, timer});
      recent.set(key, current);
      if (active.length > maxVisible) dismiss(active[active.length - 1].id);
      return id;
    }

    return Object.freeze({enqueue, dismiss});
  }

  function hasLocalCatalog() {
    return Boolean(window.webkit?.messageHandlers?.factorTesterLocalCatalog?.postMessage);
  }

  window.FTAppRuntime = Object.freeze({create, hasLocalCatalog, createNoticeQueue});
})();
