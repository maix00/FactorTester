(() => {
  function create(options) {
    const {
      state, embeddedPresentation, t, renderRoute,
      modulePath, isPinnedPath, titleForPath, tabIcon,
    } = options;

    function tabSession(tabID) {
      if (!state.tabSessions.has(tabID)) state.tabSessions.set(tabID, {});
      return state.tabSessions.get(tabID);
    }

    function saveActiveTabSession() {
      const reportMatch = /^\/research\/([^/]+)$/.exec(location.pathname);
      const currentPublicationID = reportMatch?.[1] || null;
      const pending = state.pendingScrollCapture?.tabID === state.activeTabID
        ? state.pendingScrollCapture : null;
      const snapshot = {
        scrollY: pending ? pending.scrollY : window.scrollY,
        path: location.pathname,
        publicationID: currentPublicationID,
      };
      Object.assign(tabSession(state.activeTabID), snapshot);
      if (currentPublicationID) {
        Object.assign(tabSession(`report:${currentPublicationID}`), snapshot);
      }
    }

    function captureScrollPosition() {
      state.pendingScrollCapture = {tabID: state.activeTabID, scrollY: window.scrollY};
      saveActiveTabSession();
    }

    function renderOpenedTabs() {
      const host = document.querySelector("#opened-tabs");
      const caption = document.querySelector("#opened-caption");
      if (!host || !caption) return;
      host.replaceChildren();
      const opened = state.tabs.filter(tab => tab.closable);
      caption.hidden = opened.length === 0;
      for (const tab of opened) {
        const row = document.createElement("div");
        row.className = `opened-tab${tab.id === state.activeTabID ? " active" : ""}`;
        const button = document.createElement("button");
        button.className = "tab-main"; button.type = "button";
        button.innerHTML = `<span class="symbol"></span><span class="tab-label"></span>`;
        button.querySelector(".symbol").append(FTIcons.node(tab.icon || tabIcon(tab.path)));
        button.querySelector(".tab-label").textContent = tab.title;
        button.title = document.body.classList.contains("sidebar-collapsed") ? "" : tab.title;
        button.setAttribute("aria-label", tab.title);
        button.addEventListener("click", () => activateTab(tab.id));
        const close = document.createElement("button");
        close.className = "tab-close"; close.type = "button"; close.textContent = "×";
        close.title = t("关闭");
        close.addEventListener("click", event => { event.stopPropagation(); closeTab(tab.id); });
        row.append(button, close); host.append(row);
      }
    }

    function activateTab(tabID) {
      const tab = state.tabs.find(item => item.id === tabID);
      if (!tab) return;
      saveActiveTabSession();
      state.activeTabID = tabID;
      history.pushState({}, "", tab.path);
      renderOpenedTabs(); renderRoute();
    }

    function closeTab(tabID) {
      const index = state.tabs.findIndex(tab => tab.id === tabID);
      if (index < 0) return;
      if (state.activeTabID === tabID) saveActiveTabSession();
      state.tabs.splice(index, 1); state.tabSessions.delete(tabID);
      if (state.activeTabID === tabID) {
        const fallback = state.tabs[Math.max(0, index - 1)] || state.tabs[0];
        state.activeTabID = fallback?.id || "home";
        history.pushState({}, "", fallback?.path || "/");
      }
      renderOpenedTabs(); renderRoute();
    }

    function openModule(module) {
      const path = modulePath(module);
      if (["ic-test", "backtest", "docs", "sqlite_web", "manager", "server_operations"].includes(module.id)) {
        return openTab(path, {forceNew: true, title: t(module.title_key || module.title)});
      }
      return openTab(path, {id: module.id, title: t(module.title_key || module.title), closable: false});
    }

    function openTab(path, options = {}) {
      saveActiveTabSession();
      if (!options.forceNew) {
        const existing = state.tabs.find(tab => tab.path === path);
        if (existing) {
          activateTab(existing.id);
          state.pendingScrollCapture = null;
          return;
        }
      }
      const pinned = options.closable === false || (isPinnedPath(path) && !options.forceNew);
      const id = options.id || `${path}:${crypto.randomUUID ? crypto.randomUUID() : Date.now()}`;
      state.tabs.push({
        id, path, title: options.title || titleForPath(path), icon: options.icon || tabIcon(path),
        closable: !pinned,
      });
      state.activeTabID = id; state.pendingScrollCapture = null; history.pushState({}, "", path);
      renderOpenedTabs(); renderRoute();
    }

    function navigate(path) {
      const nativeProductDetail = path.startsWith("/products/group/")
        || path.startsWith("/products/product/")
        || path.startsWith("/products/contract/")
        || path.startsWith("/products/continuous-contract/");
      if (embeddedPresentation
          && (path.startsWith("/research/") || path.startsWith("/jobs/") || nativeProductDetail)
          && window.webkit?.messageHandlers?.researchNavigation) {
        window.webkit.messageHandlers.researchNavigation.postMessage({path});
        return;
      }
      return openTab(path, {forceNew: path.startsWith("/ic-test")
        || path.startsWith("/backtest")
        || path.startsWith("/docs")
        || path.startsWith("/sqlite-web")
        || path.startsWith("/manager")
        || path.startsWith("/admin/server-operations")});
    }

    function updateActiveTab(fields) {
      const tab = state.tabs.find(item => item.id === state.activeTabID);
      if (tab) { Object.assign(tab, fields); renderOpenedTabs(); }
    }

    function initializeTabs() {
      state.tabs = state.modules
        .filter(item => ["home", "research", "jobs", "factors", "products", "profiles"].includes(item.id))
        .map(item => ({id: item.id, path: modulePath(item), title: t(item.title_key || item.title), icon: FTIcons.module(item), closable: false}));
      state.tabs.push({id: "settings", path: "/settings", title: t("设置"), icon: FTIcons.module("settings"), closable: false});
      state.activeTabID = "home"; renderOpenedTabs();
    }

    function currentTabContext() {
      return {tabID: state.activeTabID, tabSession: tabSession(state.activeTabID)};
    }

    return {
      tabSession, saveActiveTabSession, captureScrollPosition, renderOpenedTabs,
      activateTab, closeTab, openModule, openTab, navigate, updateActiveTab,
      initializeTabs, currentTabContext,
    };
  }

  window.FTTabs = Object.freeze({create});
})();
