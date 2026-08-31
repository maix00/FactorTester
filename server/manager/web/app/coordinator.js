(() => {
  const embeddedPresentation = new URLSearchParams(location.search).get("presentation") === "embedded";
  document.documentElement.classList.toggle("embedded-presentation", embeddedPresentation);
  const runtime = FTAppRuntime.create();
  const {
    state, content, title, eyebrow, toolbar, notice,
    savedToken, api, raw, showNotice, setHeading, button,
  } = runtime;
  const initialAssetRevision = document.querySelector(
    'meta[name="ft-client-assets-revision"]',
  )?.content || "";
  let assetRevisionCheck = null;
  let lastAssetRevisionCheckAt = 0;

  async function clientAssetsChanged() {
    if (!initialAssetRevision) return false;
    const now = Date.now();
    if (!assetRevisionCheck && now - lastAssetRevisionCheckAt < 1000) return false;
    if (!assetRevisionCheck) {
      lastAssetRevisionCheckAt = now;
      assetRevisionCheck = api("/api/client-assets/revision")
        .then(value => Boolean(
          value.revision && value.revision !== initialAssetRevision
        ))
        .catch(() => false)
        .finally(() => { assetRevisionCheck = null; });
    }
    return assetRevisionCheck;
  }

  async function restoreSession() {
    state.token = savedToken();
    try { state.session = await api("/api/session"); }
    catch (_) {
      const hadSavedToken = Boolean(state.token);
      state.session = null;
      state.token = "";
      localStorage.removeItem("ft-session");
      sessionStorage.removeItem("ft-session");
      if (hadSavedToken) {
        try { state.session = await api("/api/session"); }
        catch (_) { state.session = null; }
      }
    }
  }

  function t(key, fallback = key) { return FTI18n.t(key, fallback); }

  // Async route work must not be allowed to paint after a newer tab or path
  // has become active.  Consumers use this small guard after awaited IO;
  // it avoids stale report/job responses replacing the current tab.
  let activeRouteToken = 0;

  function loginRequiredView() {
    const note = FTUI.empty(
      t("登录后继续"),
      t("此模块读取账户、工作区或服务端任务"),
    );
    const login = button(t("登录"), () => openLogin(), t("登录"));
    // Keep the single login CTA consistent with the original inline login
    // view.  Do not create a second button style for scope-specific pages.
    login.className = "primary";
    note.append(login);
    return note;
  }

  const jobsContext = (routeToken = activeRouteToken) => ({
    api, raw, navigate, openTab, activeNav, setHeading, button, content, toolbar, t,
    openLogin, showNotice, servicePath,
    loginRequiredView, updateActiveTab, session: state.session, modules: state.modules,
    isRouteCurrent: () => routeToken === activeRouteToken,
    ...currentTabContext(),
  });

  function servicePath(path) {
    const port = localStorage.getItem("ft-service-port") || "";
    if (!port) return path;
    const separator = path.includes("?") ? "&" : "?";
    return `${path}${separator}port=${encodeURIComponent(port)}`;
  }

  const appContext = (routeToken = activeRouteToken) => ({
    api, raw, navigate, activeNav, setHeading, button, content, toolbar,
    servicePath, showNotice, openLogin, logout, updateActiveTab,
    activateTab: tabs?.activateTab, closeTab: tabs?.closeTab,
    session: state.session, t, ...currentTabContext(),
    isRouteCurrent: () => routeToken === activeRouteToken,
    languagePreference: state.languagePreference,
    setLanguagePreference,
    checkpointTabSession: tabs?.scheduleActiveSessionCheckpoint,
  });

  async function setLanguagePreference(language) {
    const requested = ["system", "zh-Hans", "en"].includes(language)
      ? language : "system";
    if (state.session) {
      const value = await api("/api/client/preferences", {
        method: "POST",
        body: JSON.stringify({language: requested}),
      });
      state.languagePreference = value.preferences?.language || "system";
    } else {
      // Visitor language is deliberately browser-local.  It must not create
      // an account preference or make an unauthenticated write request.
      state.languagePreference = requested;
    }
    FTI18n.rememberPreference(state.languagePreference);
    await FTI18n.load(state.languagePreference);
    localizeShell();
    await loadModules();
    // Home is a cached tab without user-authored state.  Re-render it under
    // the new locale instead of restoring the old localized DOM when the
    // user returns from Settings.
    tabs?.discardView?.("home");
    await renderRoute();
  }

  function activeNav(route) {
    document.querySelectorAll(".nav-button").forEach(item => {
      item.classList.toggle("active", item.dataset.route === route);
    });
  }

  async function refreshAfterSessionChange() {
    // Invalidate any in-flight page work before replacing the session.  The
    // old request must not paint visitor/anonymous content after login.
    activeRouteToken += 1;
    tabs?.discardViews?.();
    await loadLanguage();
    await loadModules();
    restoreWorkspaceForSession();
    const active = state.tabs.find(tab => tab.id === state.activeTabID);
    if (active?.path) history.replaceState({}, "", active.path);
    await renderRoute();
  }

  function homeNetworkRow(label, value) {
    const row = document.createElement("div");
    row.className = "home-network-row";
    const key = document.createElement("span"); key.textContent = t(label);
    const content = document.createElement("strong");
    const values = Array.isArray(value) ? value : [value];
    values.filter(item => String(item || "").trim()).forEach(item => {
      const line = document.createElement("div");
      line.textContent = String(item);
      content.append(line);
    });
    if (!content.childElementCount) content.textContent = "—";
    row.append(key, content);
    return row;
  }

  function serverAddressWithPort(address, port) {
    const host = String(address || "").trim();
    const managerPort = Number(port || 0);
    if (!host || !Number.isInteger(managerPort) || managerPort <= 0) {
      return host;
    }
    const formattedHost = host.includes(":") && !host.startsWith("[")
      ? `[${host}]`
      : host;
    return `${formattedHost}:${managerPort}`;
  }

  async function loadHomeNetwork(root, routeToken) {
    try {
      const value = await api("/api/server/network-info");
      if (routeToken !== activeRouteToken) return;
      const internal = Array.isArray(value.internal_server_addresses)
        ? value.internal_server_addresses : [];
      const publicAddresses = Array.isArray(value.public_server_addresses)
        ? value.public_server_addresses : [];
      const managerPort = value.manager_port;
      root.replaceChildren(
        homeNetworkRow("当前 Manager", `${value.server_id || ""} · ${value.role || ""}`),
        homeNetworkRow(
          "内网服务器 IP 地址",
          internal.length
            ? internal.map(address => serverAddressWithPort(address, managerPort))
            : [t("无在线内网服务器")],
        ),
        homeNetworkRow(
          "公网服务器 IP 地址",
          publicAddresses.length
            ? publicAddresses.map(address => serverAddressWithPort(address, managerPort))
            : [t("无在线公网服务器")],
        ),
      );
    } catch (error) {
      if (routeToken !== activeRouteToken) return;
      root.replaceChildren(homeNetworkRow("服务器网络信息", error.message));
    }
  }

  function home() {
    activeNav("home"); setHeading(t("主页"));
    const routeToken = activeRouteToken;
    content.innerHTML = '<div class="hero"><h2>FactorTester</h2><p></p></div><section class="home-network"><h3></h3><div class="home-network-grid"></div></section><div class="card-grid" id="home-cards"></div>';
    content.querySelector(".hero p").textContent = t("选择研究模块；每个工作现场会在左侧保持");
    content.querySelector(".home-network h3").textContent = t("服务器网络信息");
    const network = content.querySelector(".home-network-grid");
    network.append(homeNetworkRow("服务器网络信息", t("正在读取")));
    void loadHomeNetwork(network, routeToken);
    const cards = document.querySelector("#home-cards");
    for (const module of state.modules.filter(item => item.homeVisible)) {
      const card = document.createElement("button");
      card.className = "card";
      card.innerHTML = '<span class="symbol"></span><b></b><small></small>';
      card.querySelector(".symbol").append(FTIcons.node(FTIcons.module(module)));
      card.querySelector("b").textContent = t(module.title_key || module.title);
      card.querySelector("small").textContent = t(module.description_key || "");
      card.addEventListener("click", () => navigate(modulePath(module)));
      cards.append(card);
    }
  }

  async function research(routeToken = activeRouteToken) {
    return FTResearch.list({
      ...appContext(routeToken),
      modules: state.modules,
    });
  }

  function reportContext(routeToken = activeRouteToken) {
    return {
      state, api, t, content, toolbar, button,
      ...currentTabContext(),
      tabID: state.activeTabID, tabSession, activeNav, setHeading, updateActiveTab,
      openReportSettings, saveActiveTabSession, openTab, navigate, showNotice,
      captureScrollPosition,
      checkpointTabSession: tabs?.scheduleActiveSessionCheckpoint,
      isRouteCurrent: () => routeToken === activeRouteToken,
    };
  }

  async function report(publicationID, routeToken = activeRouteToken) {
    return FTReportEntry.render(publicationID, reportContext(routeToken));
  }

  function openReference(target) {
    return FTReportEntry.openReference(target, reportContext());
  }

  function publicReference(id) {
    return FTReportEntry.publicReference(id, reportContext());
  }

  async function openLocal(publicationID, resourceID, label, access) {
    return FTReportEntry.openLocal(publicationID, resourceID, label, access, reportContext());
  }

  function requireLogin() {
    if (state.session) return false;
    content.replaceChildren(loginRequiredView());
    return true;
  }

  function remoteModule(path, module) {
    activeNav("");
    setHeading(t(module.title_key || module.title));
    const frame = document.createElement("iframe");
    frame.className = "module-frame";
    frame.title = t(module.title_key || module.title);
    const frameURL = new URL(path, location.origin);
    frameURL.searchParams.set("presentation", "embedded");
    frame.src = frameURL.pathname + frameURL.search;
    content.replaceChildren(frame);
  }

  let routeDispatch;
  let tabs = null;
  const pageAgentLifecycle = window.FTPageAgentLifecycle.create({
    start: profileID => api("/api/client/profile-agent/start", {
      method: "POST", body: JSON.stringify({profile_id: profileID}),
    }),
    stop: profileID => api("/api/client/profile-agent/stop", {
      method: "POST", body: JSON.stringify({profile_id: profileID}),
    }),
  });

  // Route protection is checked before loading the route's code group.  This
  // keeps an unauthenticated deep link on the small login view instead of
  // downloading the complete IC/backtest/catalog implementation just to
  // discover that the handler will return "登录后继续".
  const protectedRouteKinds = new Set([
    "factor-sets", "factor-set",
    "profile", "profiles", "manager", "mihomo",
  ]);

  async function renderRoute() {
    const routeToken = ++activeRouteToken;
    tabs?.markActiveViewLoading?.();
    if (await clientAssetsChanged()) {
      location.reload();
      return;
    }
    if (routeToken !== activeRouteToken) return;
    showNotice("");
    document.querySelector(".report-mount")?.__ftLazyCleanup?.();
    document.querySelectorAll(".chapter-rail-tooltip").forEach(item => item.remove());
    const route = FTNavigation.matchRoute(location.pathname, location.search);
    try {
      if (!state.session && protectedRouteKinds.has(route.kind)) {
        // routeDispatch applies the same existing auth guard and updates the
        // heading/content.  No feature module is needed for this branch.
        const result = await routeDispatch.render(route, routeToken);
        if (routeToken === activeRouteToken) tabs?.markActiveViewReady?.();
        return result;
      }
      if (window.FTStaticLoader?.ensureRoute) {
        content.replaceChildren(FTUI.loading(t("正在加载模块…")));
        await window.FTStaticLoader.ensureRoute(route.kind);
        if (routeToken !== activeRouteToken) return;
      }
      const result = await routeDispatch.render(route, routeToken);
      if (routeToken === activeRouteToken) tabs?.markActiveViewReady?.();
      return result;
    } catch (error) {
      if (routeToken !== activeRouteToken) return;
      content.innerHTML = '<div class="empty"><h2></h2><p></p></div>';
      content.querySelector("h2").textContent = t("无法读取");
      content.querySelector("p").textContent = error.message;
      tabs?.markActiveViewReady?.();
    }
  }

  const modulePath = FTNavigation.modulePath;
  const moduleForPath = path => FTNavigation.moduleForPath(path, state.modules);
  const isPinnedPath = FTNavigation.isPinnedPath;
  const titleForPath = path => FTNavigation.titleForPath(path, state.modules, t);
  const tabIcon = path => FTNavigation.tabIcon(path, state.modules);
  tabs = FTTabs.create({
    state, embeddedPresentation, t, renderRoute,
    content, title, eyebrow, toolbar, notice,
    beforeTabChange: () => { activeRouteToken += 1; },
    onTabEvicted: tabID => pageAgentLifecycle.evict(tabID),
    onTabClosed: (_tab, session) => {
      const drafts = session?.durable?.testDrafts;
      const workspaceIDs = new Set(Object.values(drafts || {}).map(
        draft => draft?.schemaVersion === 2 ? String(draft.workspaceID || "") : "",
      ).filter(Boolean));
      return Promise.all([...workspaceIDs].map(workspaceID => api(
        `/api/test-authoring/workspaces/${encodeURIComponent(workspaceID)}`,
        {method: "DELETE"},
      )));
    },
    modulePath, isPinnedPath, titleForPath, tabIcon,
    pageAgentLifecycle,
  });
  const tabSession = tabs.tabSession;
  const saveActiveTabSession = tabs.saveActiveTabSession;
  const captureScrollPosition = tabs.captureScrollPosition;
  const renderOpenedTabs = tabs.renderOpenedTabs;
  const openTab = tabs.openTab;
  const navigate = tabs.navigate;
  const updateActiveTab = tabs.updateActiveTab;
  const initializeTabs = tabs.initializeTabs;
  const currentTabContext = tabs.currentTabContext;
  const detailTabIDForPath = tabs.detailTabIDForPath;
  const webMCP = window.FTWebMCP?.bind?.({
    navigate,
    root: content,
    session: () => state.session,
  });
  document.documentElement.dataset.webmcp = webMCP?.supported ? "available" : "unavailable";
  let tabWorkspace = null;

  function restoreWorkspaceForSession() {
    tabWorkspace = FTTabWorkspace.create({
      managerKey: location.origin,
      principalKey: FTTabWorkspace.principalKey(state.session),
    });
    tabs.setWorkspace(tabWorkspace);
    initializeTabs(tabWorkspace.restore());
  }
  const shell = FTAppShell.create({state, api, t, tabs});
  const {
    loadLanguage, loadModules, localizeShell, initializeSidebarLayout,
  } = shell;

  const auth = FTAuth.bind({
    state, api, t, loadLanguage, loadModules, renderRoute, appContext, navigate,
    refreshAfterSessionChange,
    checkpointActiveSession: tabs.checkpointActiveSession,
    renderReport: publicationID => report(publicationID),
  });
  const openLogin = auth.openLogin;
  const logout = auth.logout;
  const openReportSettings = auth.openReportSettings;

  routeDispatch = FTAppRouteDispatch.create({
    content,
    t,
    context: routeToken => appContext(routeToken),
    jobsContext,
    requireLogin,
    handlers: {
      home,
      publicReference,
      reference: (pageContext, route) => FTReferencePage.render(pageContext, {
        kind: route.referenceKind, target: route.target, label: route.label,
        componentID: route.componentID, detailFields: route.detailFields,
      }),
      report,
      research,
      docs: (pageContext, slug) => FTDocs.render(pageContext, slug),
      researchGraph: (pageContext, id) => FTResearchGraphList.detail(pageContext, pageContext.content, id),
      remoteModule: route => remoteModule(location.pathname, moduleForPath(location.pathname)),
      jobs: (pageContext, section) => section === "types" ? FTTestTypes.render(pageContext) : FTJobs.list(pageContext),
      job: (pageContext, port, id, serverID) => FTJobs.detail(
        pageContext, port, id, serverID,
      ),
      jobConfiguration: (pageContext, port, id, serverID) => (
        FTJobs.configuration(pageContext, port, id, serverID)
      ),
      jobInput: (pageContext, port, id, inputName, serverID) => (
        FTJobInputDetail.show(pageContext, port, id, inputName, serverID)
      ),
      icTest: (pageContext, route) => FTTests.show(pageContext, "ic", route),
      backtest: (pageContext, route) => FTTests.show(pageContext, "backtest", route),
      factorSeries: (pageContext, factorRef, groupRef) => FTTests.show(
        pageContext, "factor_evaluation", {factorRef, groupRef},
      ),
      testTemplate: (pageContext, id) => FTTestTemplates.detail(pageContext, id),
      factorFamilies: (pageContext, route) => FTFactorCatalogList.list(
        pageContext, "families", route?.scope || "public",
      ),
      factorSets: (pageContext, route) => FTFactorCatalogList.list(
        pageContext, "sets", route?.scope || "mine",
      ),
      factorFamily: (pageContext, id, mode, options) => FTFactors.familyDetail(
        pageContext, id, mode, options,
      ),
      factor: (pageContext, id, mode, route) => FTFactors.factorDetail(
        pageContext, id, mode, {familyRef: route?.familyRef || ""},
      ),
      factorSet: (pageContext, id, mode, options) => (
        FTFactors.setDetail(pageContext, id, mode, options)
      ),
      factors: (pageContext, route) => FTFactorCatalogList.list(
        pageContext, "factors", route?.scope || "mine",
      ),
      productGroup: (pageContext, id) => FTProducts.groupDetail(pageContext, id),
      product: (pageContext, id) => FTProducts.productDetail(pageContext, id),
      productReference: (pageContext, kind, id) =>
        FTProducts.referenceDetail(pageContext, kind, id),
      productSources: pageContext => FTProducts.sourceList(pageContext),
      productSourceFamily: (pageContext, id) => FTProducts.sourceFamilyDetail(pageContext, id),
      productGroups: pageContext => FTProducts.list(pageContext, "groups"),
      productCategories: pageContext => FTProducts.list(pageContext, "categories"),
      productCategory: (pageContext, route) => FTProducts.categoryDetail(
        pageContext, route?.id || "", route?.mode || "view",
      ),
      products: pageContext => FTProducts.list(pageContext, "products"),
      profile: (pageContext, id) => FTProfiles.detail(pageContext, id),
      profiles: pageContext => FTProfiles.list(pageContext),
      settings: (pageContext, section) => FTSettings.show(pageContext, section),
      manager: (pageContext, route) => FTManager.show(
        pageContext, route?.section || "services",
      ),
      mihomo: pageContext => FTMihomo.show(pageContext),
    },
  });

  window.addEventListener("popstate", renderRoute);
  window.addEventListener("pagehide", () => tabs.checkpointActiveSession());
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") tabs.checkpointActiveSession();
  });

  (async () => {
    await restoreSession();
    await loadLanguage();
    await loadModules();
    initializeSidebarLayout();
    restoreWorkspaceForSession();
    const initial = `${location.pathname}${location.search}`;
    if ((initial === "/" || initial === "") && state.activeTabID !== "home") {
      const active = state.tabs.find(tab => tab.id === state.activeTabID);
      if (active?.path) history.replaceState({}, "", active.path);
    } else if (initial !== "/" && initial !== "") {
      // Module routes, including /research?section=..., belong to the
      // existing feature-entry tab.  Only detail routes (for example
      // /research/<report>) get an independently closable tab.
      const pinnedModule = isPinnedPath(initial) ? moduleForPath(initial) : null;
      const pinned = pinnedModule && state.tabs.find(tab =>
        !tab.closable && tab.id === pinnedModule.id
      );
      if (pinned) {
        pinned.path = initial;
        state.activeTabID = pinned.id;
      } else if (!isPinnedPath(initial)) {
        const id = detailTabIDForPath(initial)
          || `${initial}:${crypto.randomUUID ? crypto.randomUUID() : Date.now()}`;
        const restored = state.tabs.find(tab => (
          tab.id === id || (tab.closable && tab.path === initial)
        ));
        if (restored) {
          state.activeTabID = restored.id;
        } else {
          state.tabs.push({id, path: initial, title: titleForPath(initial), icon: tabIcon(initial), closable: true});
          state.activeTabID = id;
        }
      }
      renderOpenedTabs();
      tabs.checkpointWorkspace();
    }
    await renderRoute();
  })();
})();
