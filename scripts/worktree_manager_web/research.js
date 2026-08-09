(() => {
  const embeddedPresentation = new URLSearchParams(location.search).get("presentation") === "embedded";
  document.documentElement.classList.toggle("embedded-presentation", embeddedPresentation);
  const runtime = FTAppRuntime.create();
  const {
    state, content, title, eyebrow, toolbar, notice,
    savedToken, api, raw, showNotice, setHeading, button,
  } = runtime;

  async function restoreSession() {
    state.token = savedToken();
    if (!state.token) return;
    try { state.session = await api("/api/session"); }
    catch (_) {
      state.token = "";
      localStorage.removeItem("ft-session");
      sessionStorage.removeItem("ft-session");
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
    api, raw, navigate, activeNav, setHeading, button, content, toolbar, t, openLogin,
    loginRequiredView, updateActiveTab, session: state.session,
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
    servicePath, showNotice, openLogin, logout, updateActiveTab, session: state.session, t, ...currentTabContext(),
    isRouteCurrent: () => routeToken === activeRouteToken,
    languagePreference: state.languagePreference,
    setLanguagePreference,
  });

  async function setLanguagePreference(language) {
    if (!state.session) throw new Error(t("请先登录"));
    const value = await api("/api/client/preferences", {
      method: "POST",
      body: JSON.stringify({language}),
    });
    state.languagePreference = value.preferences?.language || "system";
    FTI18n.rememberPreference(state.languagePreference);
    await FTI18n.load(state.languagePreference);
    localizeShell();
    await loadModules();
    await renderRoute();
  }

  function activeNav(route) {
    document.querySelectorAll(".nav-button").forEach(item => {
      item.classList.toggle("active", item.dataset.route === route);
    });
  }

  function home() {
    activeNav("home"); setHeading(t("主页"));
    content.innerHTML = '<div class="hero"><h2>FactorTester</h2><p></p></div><div class="card-grid" id="home-cards"></div>';
    content.querySelector(".hero p").textContent = t("选择研究模块；每个工作现场会在左侧保持");
    const cards = document.querySelector("#home-cards");
    for (const module of state.modules.filter(item => !["home", "settings"].includes(item.id))) {
      const card = document.createElement("button");
      card.className = "card";
      card.innerHTML = '<span class="symbol"></span><b></b><small></small>';
      card.querySelector(".symbol").append(FTIcons.node(FTIcons.module(module)));
      card.querySelector("b").textContent = t(module.title_key || module.title);
      card.querySelector("small").textContent = moduleDescription(module.id);
      card.addEventListener("click", () => navigate(modulePath(module)));
      cards.append(card);
    }
  }
  function moduleDescription(id) {
    const key = {research: "查看各 Profile 的实时步骤、义务与报告", "ic-test": "配置并运行因子 IC 测试", backtest: "配置并运行分组回测", jobs: "跨端口查看配置、进度、结果与生成物", factors: "浏览 canonical 与自定义因子", products: "查询产品、合约与市场资料", profiles: "查看研究身份、工作区与初始化来源", manager: "查看端口状态并控制本机服务", docs: "阅读 FactorTester 技术文档", sqlite_web: "浏览统一 SQLite 数据库"}[id] || "";
    return t(key);
  }

  async function research(routeToken = activeRouteToken) {
    return FTResearch.list(appContext(routeToken));
  }

  function reportContext(routeToken = activeRouteToken) {
    return {
      state, api, t, content, toolbar, button,
      tabSession, activeNav, setHeading, updateActiveTab,
      openReportSettings, saveActiveTabSession, openTab, navigate, showNotice,
      captureScrollPosition,
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

  async function renderRoute() {
    const routeToken = ++activeRouteToken;
    showNotice("");
    document.querySelector(".report-mount")?.__ftLazyCleanup?.();
    document.querySelector(".chapter-rail")?.__ftChapterRailCleanup?.();
    document.querySelectorAll(".chapter-rail-tooltip").forEach(item => item.remove());
    const parts = location.pathname.split("/").filter(Boolean);
    try {
      if (!parts.length) return home();
      if (parts[0] === "reference" && parts[1]) return publicReference(decodeURIComponent(parts.slice(1).join("/")));
      if (parts[0] === "reference") {
        const params = new URLSearchParams(location.search);
        return await FTReferencePage.render(appContext(routeToken), {
          kind: params.get("kind") || "reference",
          target: params.get("target") || "",
          label: params.get("label") || "",
        });
      }
      if (parts[0] === "research" && parts[1]) return await report(parts.slice(1).join("/"), routeToken);
      if (parts[0] === "research") return await research(routeToken);
      if (parts[0] === "jobs" && parts.length >= 3) return await FTJobs.detail(jobsContext(routeToken), Number(parts[1]), decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "jobs" && parts[1]) return await FTJobs.detail(jobsContext(routeToken), 0, decodeURIComponent(parts.slice(1).join("/")));
      if (parts[0] === "jobs") return await FTJobs.list(jobsContext(routeToken));
      if (parts[0] === "docs") return remoteModule(location.pathname, moduleForPath(location.pathname));
      if (parts[0] === "sqlite-web" && requireLogin()) return;
      if (parts[0] === "sqlite-web") return remoteModule(location.pathname, moduleForPath(location.pathname));
      if (parts[0] !== "settings" && requireLogin()) return;
      if (parts[0] === "ic-test") return await FTTests.show(appContext(routeToken), "ic");
      if (parts[0] === "backtest") return await FTTests.show(appContext(routeToken), "backtest");
      if (parts[0] === "test-templates" && parts[1]) return await FTTestTemplates.detail(appContext(routeToken), decodeURIComponent(parts.slice(1).join("/")));
      if (parts[0] === "factors" && parts[1] === "families") return await FTFactors.list(appContext(routeToken), "families");
      if (parts[0] === "factors" && parts[1] === "family" && parts[2]) return await FTFactors.familyDetail(appContext(routeToken), decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "factors" && parts[1] === "factor" && parts[2]) return await FTFactors.factorDetail(appContext(routeToken), decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "factors" && parts[1] === "set" && parts[2]) return await FTFactors.setDetail(appContext(routeToken), decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "factors") return await FTFactors.list(appContext(routeToken), "factors");
      if (parts[0] === "products" && parts[1] === "group" && parts[2]) return await FTProducts.groupDetail(appContext(routeToken), decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "products" && parts[1] === "product" && parts[2]) return await FTProducts.productDetail(appContext(routeToken), decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "products" && ["contract", "continuous-contract"].includes(parts[1]) && parts[2]) return await FTProducts.referenceDetail(appContext(routeToken), parts[1], decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "products" && parts[1] === "sources") return await FTProducts.sourceList(appContext(routeToken));
      if (parts[0] === "products" && parts[1] === "groups") return await FTProducts.list(appContext(routeToken), "groups");
      if (parts[0] === "products") return await FTProducts.list(appContext(routeToken), "products");
      if (parts[0] === "profiles" && parts[1]) return await FTProfiles.detail(appContext(routeToken), decodeURIComponent(parts.slice(1).join("/")));
      if (parts[0] === "profiles") return await FTProfiles.list(appContext(routeToken));
      if (parts[0] === "settings") return await FTSettings.show(appContext(routeToken), parts[1] || "account");
      if (parts[0] === "manager") return await FTManager.show(appContext(routeToken));
      throw new Error(t("该模块尚未注册"));
    } catch (error) {
      content.innerHTML = '<div class="empty"><h2></h2><p></p></div>';
      content.querySelector("h2").textContent = t("无法读取");
      content.querySelector("p").textContent = error.message;
    }
  }

  const modulePath = FTNavigation.modulePath;
  const moduleForPath = path => FTNavigation.moduleForPath(path, state.modules);
  const isPinnedPath = FTNavigation.isPinnedPath;
  const titleForPath = path => FTNavigation.titleForPath(path, state.modules, t);
  const tabIcon = path => FTNavigation.tabIcon(path, state.modules);
  const tabs = FTTabs.create({
    state, embeddedPresentation, t, renderRoute,
    modulePath, isPinnedPath, titleForPath, tabIcon,
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
  const shell = FTAppShell.create({state, api, t, tabs});
  const {
    loadLanguage, loadModules, localizeShell, initializeSidebarLayout,
  } = shell;

  const auth = FTAuth.bind({
    state, api, t, loadLanguage, loadModules, renderRoute, appContext,
    renderReport: publicationID => report(publicationID),
  });
  const openLogin = auth.openLogin;
  const logout = auth.logout;
  const openReportSettings = auth.openReportSettings;

  window.addEventListener("popstate", renderRoute);

  (async () => {
    await restoreSession();
    await loadLanguage();
    await loadModules();
    initializeSidebarLayout();
    initializeTabs();
    const initial = `${location.pathname}${location.search}`;
    if (initial !== "/" && initial !== "") {
      // Module routes, including /research?section=..., belong to the
      // existing feature-entry tab.  Only detail routes (for example
      // /research/<report>) get an independently closable tab.
      const pinned = state.tabs.find(tab =>
        !tab.closable && tab.path.split("?", 1)[0] === location.pathname
      );
      if (pinned) {
        pinned.path = initial;
        state.activeTabID = pinned.id;
      } else if (!isPinnedPath(initial)) {
        const id = `${initial}:${crypto.randomUUID ? crypto.randomUUID() : Date.now()}`;
        state.tabs.push({id, path: initial, title: titleForPath(initial), icon: tabIcon(initial), closable: true});
        state.activeTabID = id;
      }
      renderOpenedTabs();
    }
    await renderRoute();
  })();
})();
