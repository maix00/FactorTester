(() => {
  function create(options) {
    const {
      state, embeddedPresentation, t, renderRoute,
      modulePath, isPinnedPath, titleForPath, tabIcon,
      content, title, eyebrow, toolbar, notice, beforeTabChange,
      liveViewLimit,
      onTabClosed,
      onTabEvicted,
      pageAgentLifecycle,
    } = options;
    let workspace = null;
    let checkpointTimer = null;
    const viewCache = window.FTTabViewCache.create({
      state, content, title, eyebrow, toolbar, notice,
      persistSession: (tabID, value) => workspace?.saveSession?.(tabID, value),
      restoreSession: tabID => workspace?.restoreSession?.(tabID),
      removeSession: tabID => workspace?.removeSession?.(tabID),
      liveViewLimit,
      onTabEvicted,
    });

    function checkpointWorkspace() {
      workspace?.save?.({tabs: state.tabs, activeTabID: state.activeTabID});
    }

    function checkpointActiveSession() {
      if (checkpointTimer) {
        clearTimeout(checkpointTimer);
        checkpointTimer = null;
      }
      viewCache.checkpointActiveSession();
      checkpointWorkspace();
    }

    function scheduleActiveSessionCheckpoint() {
      if (checkpointTimer) clearTimeout(checkpointTimer);
      checkpointTimer = setTimeout(checkpointActiveSession, 250);
    }

    function setWorkspace(value) {
      workspace = value || null;
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
        button.innerHTML = '<span class="symbol"></span><span class="tab-label"></span>';
        button.querySelector(".symbol").append(FTIcons.node(tab.icon || tabIcon(tab.path)));
        button.querySelector(".tab-label").textContent = tab.title;
        button.title = document.body.classList.contains("sidebar-collapsed") ? "" : tab.title;
        button.setAttribute("aria-label", tab.title);
        button.addEventListener("click", () => activateTab(tab.id));
        const close = document.createElement("button");
        close.className = "tab-close"; close.type = "button"; close.textContent = "×";
        close.title = t("关闭");
        close.addEventListener("click", event => {
          event.stopPropagation(); closeTab(tab.id);
        });
        row.append(button, close); host.append(row);
      }
    }

    function activateTab(tabID, options = {}) {
      const tab = state.tabs.find(item => item.id === tabID);
      if (!tab) return;
      viewCache.saveActiveTabSession();
      if (options.discardView) viewCache.discardView(tabID);
      if (tabID !== state.activeTabID || options.forceRender) {
        (options.beforeTabChange || beforeTabChange)?.();
      }
      state.activeTabID = tabID;
      history.pushState({}, "", tab.path);
      renderOpenedTabs();
      checkpointWorkspace();
      if (!options.forceRender) {
        const restored = viewCache.restoreView(tabID);
        if (restored === "live") return;
        if (restored === "cold") {
          renderRoute();
          return;
        }
      }
      renderRoute();
    }

    function closeTab(tabID) {
      const index = state.tabs.findIndex(tab => tab.id === tabID);
      if (index < 0) return;
      if (state.activeTabID === tabID) viewCache.saveActiveTabSession();
      else viewCache.discardView(tabID);
      const closingTab = state.tabs[index];
      const closingSession = state.tabSessions.get(tabID) || null;
      state.tabs.splice(index, 1); state.tabSessions.delete(tabID);
      workspace?.removeSession?.(tabID);
      Promise.resolve(onTabClosed?.(closingTab, closingSession)).catch(() => {});
      if (state.activeTabID !== tabID) {
        renderOpenedTabs();
        checkpointWorkspace();
        return;
      }
      beforeTabChange?.();
      // Pinned feature tabs stay in state.tabs but are not user-opened tabs.
      // When the last closable tab is closed, always return to the home tab
      // instead of accidentally selecting a pinned feature tab near it.
      const closableTabs = state.tabs.filter(tab => tab.closable);
      const previousClosable = state.tabs.slice(0, index)
        .filter(tab => tab.closable).at(-1);
      const nextClosable = state.tabs.slice(index)
        .find(tab => tab.closable);
      const fallback = closableTabs.length
        ? previousClosable || nextClosable || closableTabs[0]
        : state.tabs.find(tab => tab.id === "home") || state.tabs[0];
      state.activeTabID = fallback?.id || "home";
      history.pushState({}, "", fallback?.path || "/");
      renderOpenedTabs();
      checkpointWorkspace();
      const restored = viewCache.restoreView(state.activeTabID);
      if (restored === "live") return;
      renderRoute();
    }

    function openModule(module) {
      const path = modulePath(module);
      if (module.tab_behavior === "new") {
        return openTab(path, {forceNew: true, title: t(module.title_key || module.title)});
      }
      return openTab(path, {
        id: module.id, title: t(module.title_key || module.title), closable: false,
      });
    }

    function openTab(path, options = {}) {
      if (!options.forceNew && options.id) {
        const existingByID = state.tabs.find(tab => tab.id === options.id);
        if (existingByID) {
          const pathChanged = existingByID.path !== path;
          existingByID.path = path;
          if (options.title) existingByID.title = options.title;
          if (options.icon) existingByID.icon = options.icon;
          activateTab(existingByID.id, {
            forceRender: pathChanged,
            discardView: pathChanged,
            beforeTabChange: options.beforeTabChange,
          });
          state.pendingScrollCapture = null;
          return;
        }
      }
      if (!options.forceNew) {
        const existing = state.tabs.find(tab => tab.path === path);
        if (existing) {
          activateTab(existing.id, {beforeTabChange: options.beforeTabChange});
          state.pendingScrollCapture = null;
          return;
        }
      }
      const pinned = options.closable === false || (isPinnedPath(path) && !options.forceNew);
      const id = options.id || `${path}:${crypto.randomUUID ? crypto.randomUUID() : Date.now()}`;
      state.tabs.push({
        id, path, title: options.title || titleForPath(path),
        icon: options.icon || tabIcon(path), closable: !pinned,
      });
      activateTab(id, {forceRender: true, beforeTabChange: options.beforeTabChange});
      state.pendingScrollCapture = null;
    }

    function productDetailTabID(path) {
      const pathname = String(path || "").split(/[?#]/, 1)[0];
      const match = /^\/products\/(group|product|contract|continuous-contract)\/(.+)$/.exec(pathname);
      if (!match) return "";
      let target = match[2];
      try { target = decodeURIComponent(target); } catch (_) {}
      return `product-detail:${match[1]}:${target}`;
    }

    function factorDetailTabID(path) {
      const pathname = String(path || "").split(/[?#]/, 1)[0];
      const match = /^\/factors\/(family|factor|set)\/(.+)$/.exec(pathname);
      if (!match) return "";
      let target = match[2];
      try { target = decodeURIComponent(target); } catch (_) {}
      return `factor-detail:${match[1]}:${target}`;
    }

    function profileDetailTabID(path) {
      const pathname = String(path || "").split(/[?#]/, 1)[0];
      const match = /^\/profiles\/(.+)$/.exec(pathname);
      if (!match) return "";
      let target = match[1];
      try { target = decodeURIComponent(target); } catch (_) {}
      let profileKey = "local";
      try {
        profileKey = new URL(path, location.origin).searchParams.get("profile_key") || "local";
      } catch (_) {}
      return `profile-detail:${target}:${profileKey}`;
    }

    function productCategoryDetailTabID(path) {
      const pathname = String(path || "").split(/[?#]/, 1)[0];
      const match = /^\/products\/categories\/(.+)$/.exec(pathname);
      if (!match || match[1] === "new") return "";
      let target = match[1];
      try { target = decodeURIComponent(target); } catch (_) {}
      return `product-category-detail:${target}`;
    }

    function productSourceFamilyDetailTabID(path) {
      const pathname = String(path || "").split(/[?#]/, 1)[0];
      const match = /^\/products\/sources\/(.+)$/.exec(pathname);
      if (!match) return "";
      let target = match[1];
      try { target = decodeURIComponent(target); } catch (_) {}
      return `product-source-family-detail:${target}`;
    }

    function jobDetailTabID(path) {
      let route;
      try { route = new URL(String(path || ""), "http://factortester.invalid"); }
      catch (_) { return ""; }
      const parts = route.pathname.split("/").filter(Boolean);
      if (parts[0] !== "jobs" || parts.length < 2) return "";
      // Configuration and input pages are separate detail routes. They must
      // not share the base task tab, otherwise restoring the task tab can
      // bring back the test workbench DOM instead of the requested page.
      if ((parts.length === 3 && parts[2] === "configuration")
          || (parts.length >= 4 && parts[2] === "inputs")
          || parts.length >= 4) return "";
      const port = parts.length === 2 ? "0" : parts[1];
      const target = parts.length === 2 ? parts[1] : parts.slice(2).join("/");
      let jobID = target;
      try { jobID = decodeURIComponent(target); } catch (_) {}
      const serverID = route.searchParams.get("server_id") || "";
      return `job-detail:${port}:${encodeURIComponent(serverID)}:${encodeURIComponent(jobID)}`;
    }

    function runSpecTabID(path) {
      let route;
      try { route = new URL(String(path || ""), "http://factortester.invalid"); }
      catch (_) { return ""; }
      if (route.pathname !== "/reference") return "";
      const kind = String(route.searchParams.get("kind") || "")
        .trim().toLowerCase().replaceAll("_", "-");
      if (kind !== "run-spec") return "";
      const target = String(route.searchParams.get("target") || "");
      if (!target) return "";
      const match = /^(?:runspec|run-spec|run_spec):sha256:(.+)$/i.exec(target);
      return `reference-detail:run-spec:${match ? `sha256:${match[1].toLowerCase()}` : target}`;
    }

    function researchReportTabID(path) {
      const pathname = String(path || "").split(/[?#]/, 1)[0];
      const match = /^\/research\/(.+)$/.exec(pathname);
      if (!match) return "";
      let target = match[1];
      try { target = decodeURIComponent(target); } catch (_) {}
      return `research-report:${encodeURIComponent(target)}`;
    }

    function detailTabIDForPath(path) {
      return researchReportTabID(path)
        || jobDetailTabID(path)
        || productSourceFamilyDetailTabID(path)
        || productCategoryDetailTabID(path)
        || productDetailTabID(path) || factorDetailTabID(path)
        || profileDetailTabID(path) || runSpecTabID(path);
    }

    function navigate(path) {
      // A missing task URL must not create a new tab.  In particular, an
      // empty href otherwise leaves the browser pathname unchanged while
      // creating a new tab, so the new tab renders the current test
      // workbench again instead of an independent task page.
      path = String(path || "").trim();
      if (!path) return;
      const pathname = String(path || "").split(/[?#]/, 1)[0];
      // An overlay owns the source tab.  Any internal navigation initiated
      // from it gets a dedicated tab, including normally pinned feature routes.
      if (viewCache.activeTabHasOverlay()) {
        return openTab(path, {forceNew: true, title: titleForPath(path)});
      }
      if (pathname === "/jobs") {
        return openTab(path, {id: "jobs", title: t("测试"), closable: false});
      }
      if (pathname === "/settings" || pathname.startsWith("/settings/")) {
        return openTab(path, {id: "settings", title: t("设置"), closable: false});
      }
      if (pathname === "/docs" || pathname.startsWith("/docs/")) {
        return openTab(path, {id: "docs", title: t("技术文档"), closable: true});
      }
      if (["/products", "/products/sources", "/products/categories", "/products/groups"]
        .includes(pathname)) {
        return openTab(path, {id: "products", title: t("产品"), closable: false});
      }
      if (["/factors", "/factors/families", "/factors/sets"].includes(pathname)) {
        return openTab(path, {id: "factors", title: t("因子库"), closable: false});
      }
      const detailTabID = detailTabIDForPath(path);
      const nativeDetail = Boolean(detailTabID);
      const nativeReference = pathname === "/reference";
      const testConfiguration = pathname === "/ic-test" || pathname === "/backtest";
      if (embeddedPresentation
        && (path.startsWith("/research/") || path.startsWith("/jobs/")
            || path.startsWith("/factor-series") || nativeDetail || nativeReference)
        && !testConfiguration
        && window.webkit?.messageHandlers?.researchNavigation) {
        window.webkit.messageHandlers.researchNavigation.postMessage({path});
        return;
      }
      return openTab(path, {
        id: detailTabID || undefined,
        // Omit the option for ordinary routes. Passing false marks a tab as
        // pinned and hides it from the opened-tab rail, which broke test
        // configuration tabs even though forceNew created distinct entries.
        closable: nativeDetail ? true : undefined,
        forceNew: testConfiguration || path.startsWith("/factor-series")
          || path.startsWith("/docs")
          || path.startsWith("/sqlite-web") || path.startsWith("/manager"),
      });
    }

    function updateActiveTab(fields) {
      const tab = state.tabs.find(item => item.id === state.activeTabID);
      if (tab) {
        Object.assign(tab, fields); renderOpenedTabs(); checkpointWorkspace();
      }
    }

    function discardViews() {
      // Authentication and language changes alter both page data and the
      // module list.  Cached DOM from the previous session must not be
      // restored after that boundary.
      const tabIDs = new Set([
        "home",
        ...state.tabs.map(tab => tab.id),
        ...state.tabSessions.keys(),
      ]);
      tabIDs.forEach(tabID => viewCache.discardView(tabID));
    }

    function initializeTabs(snapshot = null) {
      const defaults = state.modules
        .filter(item => item.pinned && item.id !== "settings")
        .map(item => ({
          id: item.id, path: modulePath(item), title: t(item.title_key || item.title),
          icon: FTIcons.module(item), closable: false,
        }));
      defaults.push({
        id: "settings", path: "/settings", title: t("设置"),
        icon: FTIcons.module("settings"), closable: false,
      });
      const restored = Array.isArray(snapshot?.tabs) ? snapshot.tabs : [];
      const restoredByID = new Map(restored.map(tab => [tab.id, tab]));
      state.tabs = defaults.map(tab => {
        const saved = restoredByID.get(tab.id);
        return saved ? {...tab, path: saved.path || tab.path} : tab;
      });
      const fixedIDs = new Set(state.tabs.map(tab => tab.id));
      restored.filter(tab => tab.closable && !fixedIDs.has(tab.id))
        .forEach(tab => state.tabs.push({...tab, closable: true}));
      state.tabs.forEach(tab => viewCache.hydrateSession(tab.id));
      state.activeTabID = state.tabs.some(tab => tab.id === snapshot?.activeTabID)
        ? snapshot.activeTabID : "home";
      renderOpenedTabs();
      checkpointWorkspace();
      return Boolean(snapshot);
    }

    function currentTabContext() {
      return {
        tabID: state.activeTabID,
        tabSession: viewCache.tabSession(state.activeTabID),
        pageState: viewCache.pageState(state.activeTabID),
        pageAgentLifecycle,
      };
    }

    return {
      ...viewCache,
      renderOpenedTabs, activateTab, closeTab, openModule, openTab, navigate,
      updateActiveTab, discardViews, initializeTabs, currentTabContext,
      detailTabIDForPath, checkpointWorkspace, setWorkspace,
      checkpointActiveSession, scheduleActiveSessionCheckpoint,
    };
  }

  window.FTTabs = Object.freeze({create});
})();
