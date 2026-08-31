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

    function folderKey(module) {
      return `ft-nav-folder-${encodeURIComponent(String(module.id || ""))}-collapsed`;
    }

    function isFolderExpanded(module) {
      return localStorage.getItem(folderKey(module)) !== "1";
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
      return row;
    }

    function renderModuleNode(module, depth = 0) {
      const children = Array.isArray(module.children) ? module.children : [];
      if (!children.length) return moduleButton(module);

      const folder = document.createElement("div");
      folder.className = `nav-folder nav-module-folder nav-depth-${Math.min(depth, 3)}`;
      folder.dataset.navFolder = module.id;
      const row = document.createElement("div");
      row.className = "nav-folder-row";
      const disclosure = document.createElement("button");
      disclosure.type = "button";
      disclosure.className = "nav-folder-toggle";
      disclosure.title = t(isFolderExpanded(module) ? "收起" : "展开");
      const childrenHost = document.createElement("div");
      childrenHost.className = "nav-folder-children nav-folder-static-children";
      childrenHost.id = `ft-nav-children-${encodeURIComponent(module.id)}`;
      const updateDisclosure = expanded => {
        disclosure.textContent = expanded ? "⌄" : "›";
        disclosure.setAttribute("aria-expanded", expanded ? "true" : "false");
        disclosure.title = t(expanded ? "收起" : "展开");
        childrenHost.hidden = !expanded;
      };
      let expanded = isFolderExpanded(module);
      updateDisclosure(expanded);
      disclosure.setAttribute("aria-controls", childrenHost.id);
      disclosure.addEventListener("click", event => {
        event.stopPropagation();
        expanded = !expanded;
        updateDisclosure(expanded);
        localStorage.setItem(folderKey(module), expanded ? "0" : "1");
      });
      row.append(disclosure, moduleButton(module));
      children.forEach(child => childrenHost.append(renderModuleNode(child, depth + 1)));
      // Research detail/report tabs are dynamic children of the Research
      // folder.  They are filled by FTTabs and deliberately have no module
      // registration of their own.
      if (module.id === "research") {
        const dynamic = document.createElement("div");
        dynamic.className = "nav-folder-dynamic";
        dynamic.dataset.navFolderDynamic = "research";
        childrenHost.append(dynamic);
      }
      folder.append(row, childrenHost);
      return folder;
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
