(() => {
  const embeddedPresentation = new URLSearchParams(location.search).get("presentation") === "embedded";
  document.documentElement.classList.toggle("embedded-presentation", embeddedPresentation);
  const runtime = FTAppRuntime.create();
  const {
    state, content, title, eyebrow, toolbar, notice,
    savedToken, api, raw, showNotice, setHeading, button,
  } = runtime;
  let refreshSidebarToggle = () => {};

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

  async function loadLanguage() {
    const requested = new URLSearchParams(location.search).get("lang");
    let remote = "";
    if (state.session) {
      try {
        const value = await api("/api/client/preferences");
        remote = value.preferences?.language || "";
      } catch (_) {}
    }
    const preference = FTI18n.choosePreference(
      requested, remote, FTI18n.storedPreference()
    );
    state.languagePreference = preference;
    FTI18n.rememberPreference(preference);
    await FTI18n.load(preference);
    localizeShell();
    refreshSidebarToggle();
  }

  function t(key, fallback = key) { return FTI18n.t(key, fallback); }

  function localizeShell() {
    document.querySelectorAll("[data-i18n]").forEach(item => {
      item.textContent = t(item.dataset.i18n);
    });
    document.querySelectorAll("[data-i18n-aria]").forEach(item => {
      item.setAttribute("aria-label", t(item.dataset.i18nAria));
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach(item => {
      item.placeholder = t(item.dataset.i18nPlaceholder);
    });
    document.querySelector("#account-title").textContent = state.session?.username || t("设置");
  }

  function hydrateIcons() {
    document.querySelectorAll("[data-symbol]").forEach(host => {
      const symbol = host.dataset.symbol;
      if (!symbol || host.querySelector(".ft-icon")) return;
      host.replaceChildren(FTIcons.node(symbol));
    });
  }

  function initializeSidebarLayout() {
    const root = document.documentElement;
    const body = document.body;
    const toggle = document.querySelector("#sidebar-toggle");
    const handle = document.querySelector("#sidebar-resize-handle");
    const storedWidth = Number(localStorage.getItem("ft-sidebar-width"));
    if (Number.isFinite(storedWidth) && storedWidth >= 180 && storedWidth <= 360) {
      root.style.setProperty("--sidebar-width", `${storedWidth}px`);
    }
    if (localStorage.getItem("ft-sidebar-collapsed") === "1") body.classList.add("sidebar-collapsed");
    const updateToggle = () => {
      const collapsed = body.classList.contains("sidebar-collapsed");
      const label = t(collapsed ? "展开侧栏" : "收起侧栏");
      if (!toggle) return;
      toggle.title = label;
      toggle.setAttribute("aria-label", label);
      toggle.dataset.i18nTitle = collapsed ? "展开侧栏" : "收起侧栏";
    };
    refreshSidebarToggle = updateToggle;
    toggle?.addEventListener("click", () => {
      body.classList.toggle("sidebar-collapsed");
      localStorage.setItem("ft-sidebar-collapsed", body.classList.contains("sidebar-collapsed") ? "1" : "0");
      updateToggle();
      tabs.renderOpenedTabs();
    });
    let resizing = false;
    const startResize = event => {
      if (event.button !== 0 || body.classList.contains("sidebar-collapsed")) return;
      resizing = true;
      handle?.classList.add("dragging");
      handle?.setPointerCapture?.(event.pointerId);
      document.body.style.userSelect = "none";
      event.preventDefault();
    };
    const resize = event => {
      if (!resizing) return;
      const width = Math.max(180, Math.min(360, event.clientX));
      root.style.setProperty("--sidebar-width", `${width}px`);
      localStorage.setItem("ft-sidebar-width", String(width));
    };
    const stopResize = () => {
      if (!resizing) return;
      resizing = false;
      handle?.classList.remove("dragging");
      document.body.style.removeProperty("user-select");
    };
    handle?.addEventListener("pointerdown", startResize);
    handle?.addEventListener("mousedown", startResize);
    document.addEventListener("pointermove", resize);
    document.addEventListener("mousemove", resize);
    handle?.addEventListener("pointerup", stopResize);
    handle?.addEventListener("pointercancel", stopResize);
    document.addEventListener("pointerup", stopResize);
    document.addEventListener("mouseup", stopResize);
    updateToggle();
  }

  async function loadModules() {
    hydrateIcons();
    state.modules = (await api("/api/modules")).modules;
    const nav = document.querySelector("#module-nav");
    // IC and backtest remain available as homepage launchers and deep-link
    // tabs, but are intentionally not primary navigation entries.
    // Documentation, database and server management are homepage-only
    // launchers.  Keeping them out of the feature-entry rail avoids a second
    // navigation surface and makes every click start a fresh dedicated tab.
    const railModules = state.modules.filter(item => !item.homeOnly && ![
      "settings", "ic-test", "backtest", "docs", "sqlite_web",
      "manager", "server_operations",
    ].includes(item.id));
    nav.replaceChildren(...railModules.map(item => {
      const row = document.createElement("button");
      row.className = "nav-button";
      row.dataset.route = item.id;
      row.innerHTML = '<span class="symbol"></span><span class="nav-label"></span>';
      row.querySelector(".symbol").append(FTIcons.node(FTIcons.module(item)));
      row.querySelector(".nav-label").textContent = t(item.title_key || item.title);
      row.addEventListener("click", () => tabs.openModule(item));
      return row;
    }));
    document.querySelector("#account-title").textContent = state.session?.username || t("设置");
    tabs.renderOpenedTabs();
  }

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

  const jobsContext = () => ({
    api, raw, navigate, activeNav, setHeading, button, content, toolbar, t, openLogin,
    loginRequiredView, updateActiveTab, session: state.session, ...currentTabContext(),
  });

  function servicePath(path) {
    const port = localStorage.getItem("ft-service-port") || "";
    if (!port) return path;
    const separator = path.includes("?") ? "&" : "?";
    return `${path}${separator}port=${encodeURIComponent(port)}`;
  }

  const appContext = () => ({
    api, raw, navigate, activeNav, setHeading, button, content, toolbar,
    servicePath, showNotice, openLogin, logout, updateActiveTab, session: state.session, t, ...currentTabContext(),
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

  async function research() {
    return FTResearch.list(appContext());
  }

  function reportContext() {
    return {
      state, api, t, content, toolbar, button,
      tabSession, activeNav, setHeading, updateActiveTab,
      openReportSettings, saveActiveTabSession, openTab, navigate, showNotice,
      captureScrollPosition,
    };
  }

  async function report(publicationID) {
    return FTReportEntry.render(publicationID, reportContext());
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
    showNotice("");
    document.querySelector(".report-mount")?.__ftLazyCleanup?.();
    document.querySelector(".chapter-rail")?.__ftChapterRailCleanup?.();
    document.querySelectorAll(".chapter-rail-tooltip").forEach(item => item.remove());
    const parts = location.pathname.split("/").filter(Boolean);
    try {
      if (!parts.length) return home();
      if (parts[0] === "reference" && parts[1]) return publicReference(decodeURIComponent(parts.slice(1).join("/")));
      if (parts[0] === "research" && parts[1]) return await report(parts.slice(1).join("/"));
      if (parts[0] === "research") return await research();
      if (parts[0] === "jobs" && parts.length >= 3) return await FTJobs.detail(jobsContext(), Number(parts[1]), decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "jobs" && parts[1]) return await FTJobs.detail(jobsContext(), 0, decodeURIComponent(parts.slice(1).join("/")));
      if (parts[0] === "jobs") return await FTJobs.list(jobsContext());
      if (parts[0] === "docs") return remoteModule(location.pathname, moduleForPath(location.pathname));
      if (parts[0] === "sqlite-web" && requireLogin()) return;
      if (parts[0] === "sqlite-web") return remoteModule(location.pathname, moduleForPath(location.pathname));
      if (parts[0] !== "settings" && requireLogin()) return;
      if (parts[0] === "ic-test") return await FTTests.show(appContext(), "ic");
      if (parts[0] === "backtest") return await FTTests.show(appContext(), "backtest");
      if (parts[0] === "test-templates" && parts[1]) return await FTTestTemplates.detail(appContext(), decodeURIComponent(parts.slice(1).join("/")));
      if (parts[0] === "factors" && parts[1] === "families") return await FTFactors.list(appContext(), "families");
      if (parts[0] === "factors" && parts[1] === "family" && parts[2]) return await FTFactors.familyDetail(appContext(), decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "factors" && parts[1] === "factor" && parts[2]) return await FTFactors.factorDetail(appContext(), decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "factors" && parts[1] === "set" && parts[2]) return await FTFactors.setDetail(appContext(), decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "factors") return await FTFactors.list(appContext(), "factors");
      if (parts[0] === "products" && parts[1] === "group" && parts[2]) return await FTProducts.groupDetail(appContext(), decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "products" && parts[1] === "product" && parts[2]) return await FTProducts.productDetail(appContext(), decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "products" && ["contract", "continuous-contract"].includes(parts[1]) && parts[2]) return await FTProducts.referenceDetail(appContext(), parts[1], decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "products" && parts[1] === "sources") return await FTProducts.sourceList(appContext());
      if (parts[0] === "products" && parts[1] === "groups") return await FTProducts.list(appContext(), "groups");
      if (parts[0] === "products") return await FTProducts.list(appContext(), "products");
      if (parts[0] === "profiles" && parts[1]) return await FTProfiles.detail(appContext(), decodeURIComponent(parts.slice(1).join("/")));
      if (parts[0] === "profiles") return await FTProfiles.list(appContext());
      if (parts[0] === "settings") return await FTSettings.show(appContext(), parts[1] || "account");
      if (parts[0] === "manager") return await FTManager.show(appContext());
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
