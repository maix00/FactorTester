(() => {
  const state = {
    session: null, token: "", modules: [], report: null,
    languagePreference: "system",
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
    let preference = requested || "system";
    if (state.session) {
      try {
        const value = await api("/api/client/preferences");
        preference = value.preferences?.language || preference;
      } catch (_) {}
    }
    state.languagePreference = preference;
    await FTI18n.load(preference);
    localizeShell();
  }

  function t(key, fallback = key) { return FTI18n.t(key, fallback); }

  function localizeShell() {
    document.querySelector(".sidebar-caption").textContent = t("功能入口");
    document.querySelector("#account-title").textContent = state.session?.username || t("设置");
    document.querySelector("#login-dialog h2").textContent = t("登录 FactorTester");
  }

  async function loadModules() {
    state.modules = (await api("/api/modules")).modules;
    const nav = document.querySelector("#module-nav");
    nav.replaceChildren(...state.modules.filter(item => item.id !== "settings").map(item => {
      const row = document.createElement("button");
      row.className = "nav-button";
      row.dataset.route = item.id;
      row.innerHTML = `<span class="symbol">${icon(item.icon)}</span><span class="nav-label"></span>`;
      row.querySelector(".nav-label").textContent = t(item.title_key || item.title);
      row.addEventListener("click", () => navigate(`/${item.id === "home" ? "" : item.id}`));
      return row;
    }));
    document.querySelector("#account-title").textContent = state.session?.username || t("设置");
  }

  function icon(value) {
    return {grid: "⌘", chart: "⌁", checklist: "☷", function: "ƒ", box: "◇", profiles: "▣", server: "▤"}[value] || "•";
  }

  function navigate(path) {
    history.pushState({}, "", path);
    renderRoute();
  }

  const jobsContext = () => ({
    api, raw, navigate, activeNav, setHeading, button, content, toolbar, t,
  });

  function servicePath(path) {
    const port = localStorage.getItem("ft-service-port") || "";
    if (!port) return path;
    const separator = path.includes("?") ? "&" : "?";
    return `${path}${separator}port=${encodeURIComponent(port)}`;
  }

  const appContext = () => ({
    api, raw, navigate, activeNav, setHeading, button, content, toolbar,
    servicePath, showNotice, openLogin, logout, session: state.session, t,
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
    const key = {research: "查看各 Profile 的实时步骤、义务与报告", jobs: "跨端口查看配置、进度、结果与生成物", factors: "浏览 canonical 与自定义因子", products: "查询产品、合约与市场资料", profiles: "查看研究身份、工作区与初始化来源", manager: "查看端口状态并控制本机服务"}[id] || "";
    return t(key);
  }

  async function research() {
    return FTResearch.list(appContext());
  }

  async function report(publicationID) {
    activeNav("research"); content.innerHTML = '<div class="empty"><p>正在读取研究报告…</p></div>';
    const value = await api(`/api/public-research/${publicationID}`);
    state.report = value;
    setHeading(value.title, "研究报告");
    const picker = document.createElement("select");
    toolbar.append(picker, button("↻", () => report(publicationID), "刷新"));
    if (value.access?.can_manage) toolbar.append(button("⚙", openReportSettings, "研究报告设置"));
    const header = document.createElement("div"); header.className = "report-header";
    header.textContent = `Generation ${value.generation}`;
    const mount = document.createElement("div");
    content.replaceChildren(header, mount);
    FTReportRenderer.render(value, mount, {
      chapterPicker: picker,
      openLocalResource: (resourceID, label) => openLocal(publicationID, resourceID, label, value.access),
      openReference: openReference,
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
    if (!state.session) return openLogin(`登录并获授权后才能读取“${label}”`);
    if (!access?.local_file_relay) return showNotice("报告所有者未启用本地文件中继", true);
    if (!access?.owner_client_online) return showNotice("报告所有者的 FTClient 当前离线", true);
    showNotice("本地文件中继协议正在等待所有者 FTClient 响应");
  }

  function requireLogin() {
    if (state.session) return false;
    content.innerHTML = '<div class="empty"><h2>登录后继续</h2><p>此模块读取账户、工作区或服务端任务</p><button class="primary" id="inline-login">登录</button></div>';
    document.querySelector("#inline-login").onclick = () => openLogin();
    return true;
  }

  async function renderRoute() {
    showNotice("");
    const parts = location.pathname.split("/").filter(Boolean);
    try {
      if (!parts.length) return home();
      if (parts[0] === "research" && parts[1] === "work" && parts[3] === "branch" && parts[4]) {
        return await FTResearch.branch(appContext(), decodeURIComponent(parts[2]), decodeURIComponent(parts[4]));
      }
      if (parts[0] === "research" && parts[1] === "work" && parts[2]) {
        return await FTResearch.workPackage(appContext(), decodeURIComponent(parts[2]));
      }
      if (parts[0] === "research" && parts[1]) return await report(parts[1]);
      if (parts[0] === "research") return await research();
      if (parts[0] === "research-graphs") return await FTResearch.graph(appContext(), decodeURIComponent(parts[1] || "factor-research"));
      if (parts[0] === "jobs" && parts.length >= 3) return await FTJobs.detail(jobsContext(), Number(parts[1]), decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "jobs" && parts[1]) return await FTJobs.detail(jobsContext(), 0, decodeURIComponent(parts.slice(1).join("/")));
      if (parts[0] !== "settings" && requireLogin()) return;
      if (parts[0] === "jobs") return await FTJobs.list(jobsContext());
      if (parts[0] === "factors" && parts[1] === "families") return await FTFactors.list(appContext(), "families");
      if (parts[0] === "factors" && parts[1] === "family" && parts[2]) return await FTFactors.familyDetail(appContext(), decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "factors" && parts[1] === "factor" && parts[2]) return await FTFactors.factorDetail(appContext(), decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "factors" && parts[1] === "set" && parts[2]) return await FTFactors.setDetail(appContext(), decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "factors") return await FTFactors.list(appContext(), "factors");
      if (parts[0] === "products" && parts[1] === "group" && parts[2]) return await FTProducts.groupDetail(appContext(), decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "products" && parts[1] === "product" && parts[2]) return await FTProducts.productDetail(appContext(), decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "products" && ["contract", "continuous-contract"].includes(parts[1]) && parts[2]) return await FTProducts.referenceDetail(appContext(), parts[1], decodeURIComponent(parts.slice(2).join("/")));
      if (parts[0] === "products") return await FTProducts.list(appContext());
      if (parts[0] === "profiles" && parts[1]) return await FTProfiles.detail(appContext(), decodeURIComponent(parts.slice(1).join("/")));
      if (parts[0] === "profiles") return await FTProfiles.list(appContext());
      if (parts[0] === "settings") return await FTSettings.show(appContext(), parts[1] || "account");
      if (parts[0] === "manager") return await FTManager.show(appContext());
      throw new Error("该模块尚未注册");
    } catch (error) {
      content.innerHTML = `<div class="empty"><h2>无法读取</h2><p></p></div>`;
      content.querySelector("p").textContent = error.message;
    }
  }

  function openLogin(message = "") {
    const dialog = document.querySelector("#login-dialog");
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
    return {private: "仅自己", authorized: "授权用户", public: "公开"}[value] || value;
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
    row.innerHTML = '<input placeholder="完整用户名"><button type="button">移除</button>';
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
    await renderRoute();
  })();
})();
