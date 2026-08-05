(() => {
  const embeddedPresentation = new URLSearchParams(location.search).get("presentation") === "embedded";
  document.documentElement.classList.toggle("embedded-presentation", embeddedPresentation);
  const state = {
    session: null, token: "", modules: [], report: null,
    languagePreference: "system",
    tabs: [], activeTabID: "home", tabSessions: new Map(),
  };
  const content = document.querySelector("#content");
  const title = document.querySelector("#page-title");
  const eyebrow = document.querySelector("#page-eyebrow");
  const toolbar = document.querySelector("#page-toolbar");
  const notice = document.querySelector("#notice");

  function savedToken() {
    return localStorage.getItem("ft-session") || sessionStorage.getItem("ft-session") || "";
  }
  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
    if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    const response = await fetch(path, {...options, headers});
    const value = response.status === 204 ? {} : await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
    return value;
  }

  async function raw(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
    const response = await fetch(path, {...options, headers});
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try { message = (await response.json()).error || message; } catch (_) {}
      throw new Error(message);
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

  async function loadModules() {
    state.modules = (await api("/api/modules")).modules;
    const nav = document.querySelector("#module-nav");
    // IC and backtest remain available as homepage launchers and deep-link
    // tabs, but are intentionally not primary navigation entries.
    nav.replaceChildren(...state.modules.filter(item => !["settings", "ic-test", "backtest"].includes(item.id)).map(item => {
      const row = document.createElement("button");
      row.className = "nav-button";
      row.dataset.route = item.id;
      row.innerHTML = `<span class="symbol">${icon(item.icon)}</span><span class="nav-label"></span>`;
      row.querySelector(".nav-label").textContent = t(item.title_key || item.title);
      row.addEventListener("click", () => openModule(item));
      return row;
    }));
    document.querySelector("#account-title").textContent = state.session?.username || t("设置");
    renderOpenedTabs();
  }

  function icon(value) {
    return {grid: "⌘", chart: "⌁", correlation: "ρ", backtest: "↗", checklist: "☷", function: "ƒ", box: "◇", profiles: "▣", server: "▤"}[value] || "•";
  }

  function modulePath(module) { return `/${module.id === "home" ? "" : module.id}`; }

  function tabSession(tabID) {
    if (!state.tabSessions.has(tabID)) state.tabSessions.set(tabID, {});
    return state.tabSessions.get(tabID);
  }

  function moduleForPath(path) {
    const id = path.split("/").filter(Boolean)[0] || "home";
    return state.modules.find(item => item.id === id) || {id, title: id, icon: ""};
  }

  function isPinnedPath(path) {
    const parts = path.split("/").filter(Boolean);
    return parts.length <= 1 && !["ic-test", "backtest"].includes(parts[0]);
  }

  function titleForPath(path) {
    const parts = path.split("/").filter(Boolean);
    const module = moduleForPath(path);
    if (parts.length <= 1) return t(module.title_key || module.title);
    const labels = {research: "研究报告", jobs: "测试任务", factors: "因子详情", products: "产品详情", profiles: "Profile", "test-templates": "测试模板"};
    return t(labels[parts[0]] || module.title || parts[0]);
  }

  function tabIcon(path) { return icon(moduleForPath(path).icon); }

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
      button.querySelector(".symbol").textContent = tab.icon || tabIcon(tab.path);
      button.querySelector(".tab-label").textContent = tab.title;
      button.title = tab.title;
      button.addEventListener("click", () => activateTab(tab.id));
      const close = document.createElement("button");
      close.className = "tab-close"; close.type = "button"; close.textContent = "×";
      close.title = t("关闭");
      close.addEventListener("click", event => { event.stopPropagation(); closeTab(tab.id); });
      button.append(close); row.append(button); host.append(row);
    }
  }

  function activateTab(tabID) {
    const tab = state.tabs.find(item => item.id === tabID);
    if (!tab) return;
    state.activeTabID = tabID;
    history.pushState({}, "", tab.path);
    renderOpenedTabs(); renderRoute();
  }

  function closeTab(tabID) {
    const index = state.tabs.findIndex(tab => tab.id === tabID);
    if (index < 0) return;
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
    if (module.id === "ic-test" || module.id === "backtest") {
      return openTab(path, {forceNew: true, title: t(module.title_key || module.title)});
    }
    return openTab(path, {id: module.id, title: t(module.title_key || module.title), closable: false});
  }

  function openTab(path, options = {}) {
    if (!options.forceNew) {
      const existing = state.tabs.find(tab => tab.path === path);
      if (existing) return activateTab(existing.id);
    }
    const pinned = options.closable === false || (isPinnedPath(path) && !options.forceNew);
    const id = options.id || `${path}:${crypto.randomUUID ? crypto.randomUUID() : Date.now()}`;
    state.tabs.push({
      id, path, title: options.title || titleForPath(path), icon: options.icon || tabIcon(path),
      closable: !pinned,
    });
    state.activeTabID = id; history.pushState({}, "", path);
    renderOpenedTabs(); renderRoute();
  }

  function navigate(path) {
    return openTab(path, {forceNew: path.startsWith("/ic-test") || path.startsWith("/backtest")});
  }

  function updateActiveTab(fields) {
    const tab = state.tabs.find(item => item.id === state.activeTabID);
    if (tab) { Object.assign(tab, fields); renderOpenedTabs(); }
  }

  function initializeTabs() {
    state.tabs = state.modules
      .filter(item => ["home", "research", "jobs", "factors", "products", "profiles"].includes(item.id))
      .map(item => ({id: item.id, path: modulePath(item), title: t(item.title_key || item.title), icon: icon(item.icon), closable: false}));
    state.tabs.push({id: "settings", path: "/settings", title: t("设置"), icon: "⚙", closable: false});
    state.activeTabID = "home"; renderOpenedTabs();
  }

  const currentTabContext = () => ({tabID: state.activeTabID, tabSession: tabSession(state.activeTabID)});

  const jobsContext = () => ({
    api, raw, navigate, activeNav, setHeading, button, content, toolbar, t, openLogin, session: state.session, ...currentTabContext(),
  });

  function servicePath(path) {
    const port = localStorage.getItem("ft-service-port") || "";
    if (!port) return path;
    const separator = path.includes("?") ? "&" : "?";
    return `${path}${separator}port=${encodeURIComponent(port)}`;
  }

  const appContext = () => ({
    api, raw, navigate, activeNav, setHeading, button, content, toolbar,
    servicePath, showNotice, openLogin, logout, session: state.session, t, ...currentTabContext(),
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
      card.innerHTML = `<span class="symbol">${icon(module.icon)}</span><b></b><small></small>`;
      card.querySelector("b").textContent = t(module.title_key || module.title);
      card.querySelector("small").textContent = moduleDescription(module.id);
      card.addEventListener("click", () => navigate(`/${module.id}`));
      cards.append(card);
    }
  }
  function moduleDescription(id) {
    const key = {research: "查看各 Profile 的实时步骤、义务与报告", "ic-test": "配置并运行因子 IC 测试", backtest: "配置并运行分组回测", jobs: "跨端口查看配置、进度、结果与生成物", factors: "浏览 canonical 与自定义因子", products: "查询产品、合约与市场资料", profiles: "查看研究身份、工作区与初始化来源", manager: "查看端口状态并控制本机服务"}[id] || "";
    return t(key);
  }

  async function research() {
    return FTResearch.list(appContext());
  }

  async function report(publicationID) {
    activeNav("research"); content.innerHTML = '<div class="empty"><p></p></div>';
    content.querySelector("p").textContent = t("正在读取研究报告…");
    const value = await api(`/api/public-research/${publicationID}`);
    state.report = value;
    setHeading(value.title, t("研究报告"));
    updateActiveTab({title: value.title});
    const branches = Array.isArray(value.branches) ? value.branches : [];
    if (branches.length > 1) {
      const branchPicker = document.createElement("select");
      branchPicker.className = "branch-picker";
      branches.forEach(branch => {
        const option = document.createElement("option");
        option.value = branch.href || branch.branch_ref || "";
        option.textContent = branch.title || branch.branch_ref || t("研究路径");
        branchPicker.append(option);
      });
      toolbar.append(branchPicker);
    }
    toolbar.append(button("↻", () => report(publicationID), t("刷新")));
    if (value.access?.can_manage) toolbar.append(button("⚙", openReportSettings, t("研究报告设置")));
    const header = document.createElement("div"); header.className = "report-header";
    header.textContent = `Generation ${value.generation}`;
    const layout = document.createElement("div"); layout.className = "report-layout";
    const rail = document.createElement("nav"); rail.className = "chapter-rail";
    const mount = document.createElement("div"); mount.className = "report-mount";
    layout.append(rail, mount); content.replaceChildren(header, layout);
    FTReportRenderer.render(value, mount, {
      chapterRail: rail,
      openLocalResource: (resourceID, label) => openLocal(publicationID, resourceID, label, value.access),
      openReference: openReference,
      reportAssetPath: assetID => `/api/public-research/${encodeURIComponent(publicationID)}/assets/${encodeURIComponent(assetID)}`,
      t,
    });
  }

  function openReference(target) {
    try {
      const reference = new URL(target);
      const type = reference.hostname;
      const value = decodeURIComponent(reference.pathname.replace(/^\//, ""));
      if (type === "job" && value) return navigate(`/jobs/${encodeURIComponent(value)}`);
      if (type === "factor-set" && value) {
        return navigate(`/factors/set/${encodeURIComponent(value)}`);
      }
      if (type === "factor" && value) {
        const page = value.startsWith("factor-family:") ? "family" : "factor";
        return navigate(`/factors/${page}/${encodeURIComponent(value)}`);
      }
      if (type === "product-group" && value) {
        return navigate(`/products/group/${encodeURIComponent(value)}`);
      }
      if (["product", "contract", "continuous-contract"].includes(type) && value) {
        return navigate(`/products/${type}/${encodeURIComponent(value)}`);
      }
      if ((type === "profile" || type === "profile-revision") && value) {
        return navigate(`/profiles/${encodeURIComponent(value.split(":").pop())}`);
      }
    } catch (_) {}
    showNotice(t("该引用的 Web 详情页尚未接入统一路由"), true);
  }

  function openLocal(publicationID, resourceID, label, access) {
    if (!state.session) return openLogin(FTI18n.format("登录并获授权后才能读取“%@”", label));
    if (!access?.local_file_relay) return showNotice(t("报告所有者未启用本地文件中继"), true);
    if (!access?.owner_client_online) return showNotice(t("报告所有者的 FTClient 当前离线"), true);
    showNotice(t("本地文件中继协议正在等待所有者 FTClient 响应"));
  }

  function requireLogin() {
    if (state.session) return false;
    content.innerHTML = '<div class="empty"><h2></h2><p></p><button class="primary" id="inline-login"></button></div>';
    content.querySelector("h2").textContent = t("登录后继续");
    content.querySelector("p").textContent = t("此模块读取账户、工作区或服务端任务");
    document.querySelector("#inline-login").textContent = t("登录");
    document.querySelector("#inline-login").onclick = () => openLogin();
    return true;
  }

  async function renderRoute() {
    showNotice("");
    const parts = location.pathname.split("/").filter(Boolean);
    try {
      if (!parts.length) return home();
      if (parts[0] === "research" && parts[1]) return await report(parts[1]);
      if (parts[0] === "research") return await research();
      if (parts[0] === "jobs" && parts.length >= 3) return await FTJobs.detail(jobsContext(), Number(parts[1]), decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "jobs" && parts[1]) return await FTJobs.detail(jobsContext(), 0, decodeURIComponent(parts.slice(1).join("/")));
      if (parts[0] === "jobs") return await FTJobs.list(jobsContext());
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

  function openLogin(message = "") {
    const dialog = document.querySelector("#login-dialog");
    showAuthForm("login");
    document.querySelector("#login-error").hidden = !message;
    document.querySelector("#login-error").textContent = message;
    dialog.showModal();
  }

  async function logout() {
    try { await api("/auth/logout", {method: "POST"}); } catch (_) {}
    localStorage.removeItem("ft-session"); sessionStorage.removeItem("ft-session");
    state.token = ""; state.session = null; await loadModules(); await FTSettings.show(appContext(), "account");
  }

  function visibilityTitle(value) {
    const key = {private: "仅自己", authorized: "授权用户", public: "公开"}[value];
    return key ? t(key) : value;
  }
  function formatDate(value) {
    return value ? new Date(value * 1000).toLocaleString() : "";
  }

  async function openReportSettings() {
    const settings = (await api("/api/research-publications/settings")).reports.find(item => item.publication_id === state.report.publication_id);
    if (!settings) return;
    document.querySelector("#setting-auto-sync").checked = settings.auto_sync;
    document.querySelector("#setting-visibility").value = settings.visibility;
    document.querySelector("#setting-relay").checked = settings.relay_local_files;
    const list = document.querySelector("#authorized-user-list"); list.replaceChildren();
    (settings.authorized_users || []).forEach(addAuthorizedUser);
    document.querySelector("#report-settings-dialog").showModal();
  }

  function addAuthorizedUser(value = "") {
    const row = document.createElement("div"); row.className = "authorized-user";
    row.innerHTML = '<input><button type="button"></button>';
    row.querySelector("input").placeholder = t("完整用户名");
    row.querySelector("button").textContent = t("移除");
    row.querySelector("input").value = value;
    row.querySelector("button").onclick = () => row.remove();
    document.querySelector("#authorized-user-list").append(row);
  }

  document.querySelector("#login-form").addEventListener("submit", async event => {
    event.preventDefault();
    try {
      const result = await api("/auth/login", {method: "POST", body: JSON.stringify({username: document.querySelector("#username").value, password: document.querySelector("#password").value})});
      state.token = result.token; state.session = result;
      const storage = document.querySelector("#keep-login").checked ? localStorage : sessionStorage;
      storage.setItem("ft-session", result.token);
      document.querySelector("#login-dialog").close();
      await loadLanguage(); await loadModules(); await renderRoute();
    } catch (error) {
      const field = document.querySelector("#login-error"); field.hidden = false; field.textContent = error.message;
    }
  });
  function showAuthForm(kind) {
    document.querySelector("#login-form").hidden = kind !== "login";
    document.querySelector("#register-form").hidden = kind !== "register";
  }
  document.querySelector("#show-register").onclick = () => showAuthForm("register");
  document.querySelector("#show-login").onclick = () => showAuthForm("login");
  document.querySelector("#close-register").onclick = () => document.querySelector("#login-dialog").close();
  document.querySelector("#register-form").addEventListener("submit", async event => {
    event.preventDefault();
    try {
      const result = await api("/auth/register", {method: "POST", body: JSON.stringify({
        username: document.querySelector("#register-username").value,
        password: document.querySelector("#register-password").value,
        organization_id: document.querySelector("#register-organization").value,
      })});
      state.token = result.token; state.session = result;
      localStorage.setItem("ft-session", result.token);
      document.querySelector("#login-dialog").close();
      await loadLanguage(); await loadModules(); await renderRoute();
    } catch (error) {
      const field = document.querySelector("#register-error"); field.hidden = false; field.textContent = error.message;
    }
  });
  document.querySelector("#report-settings-form").addEventListener("submit", async event => {
    event.preventDefault();
    try {
      const users = [...document.querySelectorAll("#authorized-user-list input")].map(item => item.value.trim()).filter(Boolean);
      await api("/api/research-publications/settings", {method: "POST", body: JSON.stringify({report_id: state.report.report_id, auto_sync: document.querySelector("#setting-auto-sync").checked, visibility: document.querySelector("#setting-visibility").value, relay_local_files: document.querySelector("#setting-relay").checked, authorized_users: users})});
      document.querySelector("#report-settings-dialog").close();
      await report(state.report.publication_id);
    } catch (error) {
      const field = document.querySelector("#settings-error"); field.hidden = false; field.textContent = error.message;
    }
  });
  document.querySelector("#add-authorized-user").onclick = () => addAuthorizedUser();
  document.querySelector("#account-button").onclick = () => navigate("/settings");
  window.addEventListener("popstate", renderRoute);

  (async () => {
    await restoreSession();
    await loadLanguage();
    await loadModules();
    initializeTabs();
    const initial = `${location.pathname}${location.search}`;
    if (initial !== "/" && initial !== "") {
      const id = `${initial}:${crypto.randomUUID ? crypto.randomUUID() : Date.now()}`;
      state.tabs.push({id, path: initial, title: titleForPath(initial), icon: tabIcon(initial), closable: true});
      state.activeTabID = id;
      renderOpenedTabs();
    }
    await renderRoute();
  })();
})();
