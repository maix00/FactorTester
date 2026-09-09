(() => {
  function create({state, api, t, tabs}) {
    let refreshSidebarToggle = () => {};

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
      document.querySelector("#account-title").textContent =
        state.session?.alias || state.session?.username || t("设置");
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
      document.querySelector("#home-brand")?.addEventListener(
        "click", () => tabs.navigate("/"),
      );
      const handle = document.querySelector("#sidebar-resize-handle");
      const storedWidth = Number(localStorage.getItem("ft-sidebar-width"));
      if (Number.isFinite(storedWidth) && storedWidth >= 180 && storedWidth <= 360) {
        root.style.setProperty("--sidebar-width", `${storedWidth}px`);
      }
      if (localStorage.getItem("ft-sidebar-collapsed") === "1") {
        body.classList.add("sidebar-collapsed");
      }
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
        localStorage.setItem(
          "ft-sidebar-collapsed",
          body.classList.contains("sidebar-collapsed") ? "1" : "0",
        );
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
        requested, remote, FTI18n.storedPreference(),
      );
      state.languagePreference = preference;
      FTI18n.rememberPreference(preference);
      await FTI18n.load(preference);
      localizeShell();
      refreshSidebarToggle();
    }

    function moduleTitle(module) {
      return t(module.title_key || module.title || module.id);
    }

    function moduleButton(module) {
      const row = document.createElement("button");
      row.className = "nav-button";
      row.type = "button";
      row.dataset.route = module.id;
      row.innerHTML = '<span class="symbol"></span><span class="nav-label"></span>';
      row.querySelector(".symbol").append(FTIcons.node(FTIcons.module(module)));
      row.querySelector(".nav-label").textContent = moduleTitle(module);
      row.title = moduleTitle(module);
      row.addEventListener("click", () => tabs.openModule(module));
      if (module.tab_behavior === "singleton") {
        const wrapper = document.createElement("div");
        wrapper.className = "nav-singleton";
        wrapper.dataset.mountedModule = module.id;
        wrapper.hidden = !state.tabs.some(tab => tab.id === module.id);
        const close = document.createElement("button");
        close.type = "button";
        close.className = "nav-singleton-close tab-close icon-action-button";
        close.dataset.moduleClose = module.id;
        close.setAttribute("aria-label", `${t("关闭")} ${moduleTitle(module)}`);
        close.append(FTIcons.node("xmark"));
        close.hidden = !state.tabs.some(tab => tab.id === module.id);
        close.addEventListener("click", () => tabs.closeTab(module.id));
        wrapper.append(row, close);
        return wrapper;
      }
      return row;
    }

    function renderModuleNode(module) {
      // The sidebar lists feature entries only. Children describe pages
      // inside that feature and are rendered by the feature's own tabs.
      return moduleButton(module);
    }

    async function loadModules() {
      hydrateIcons();
      try {
        const response = await api("/api/modules");
        if (!Array.isArray(response.modules)) throw new Error("模块目录格式无效");
        state.modules = response.modules;
        state.modulesError = null;
      } catch (error) {
        state.modules = FTNavigation.fallbackModulesForSession(state.session);
        state.modulesError = error;
      }
      const moduleByID = new Map(state.modules.map(item => [item.id, item]));
      state.tabs.forEach(tab => {
        const module = moduleByID.get(tab.id);
        if (module) tab.title = t(module.title_key || module.title);
        else if (tab.id === "settings") tab.title = t("设置");
      });
      const nav = document.querySelector("#module-nav");
      const railModules = state.modules.filter(item => item.sidebarVisible);
      nav.replaceChildren(...railModules.map(item => renderModuleNode(item)));
      document.querySelector("#account-title").textContent =
        state.session?.alias || state.session?.username || t("设置");
      tabs.renderOpenedTabs();
    }

    return Object.freeze({
      loadLanguage,
      loadModules,
      localizeShell,
      initializeSidebarLayout,
    });
  }

  window.FTAppShell = Object.freeze({create});
})();
