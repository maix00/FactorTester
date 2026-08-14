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

    async function loadModules() {
      hydrateIcons();
      state.modules = (await api("/api/modules")).modules;
      const nav = document.querySelector("#module-nav");
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
