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

    function showNotice(message, isError = false) {
      notice.hidden = !message;
      notice.textContent = message || "";
      notice.style.color = isError ? "var(--danger)" : "inherit";
    }

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

  function hasLocalCatalog() {
    return Boolean(window.webkit?.messageHandlers?.factorTesterLocalCatalog?.postMessage);
  }

  window.FTAppRuntime = Object.freeze({create, hasLocalCatalog});
})();
