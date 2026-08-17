(() => {
  function create(options) {
    const items = (options.items || []).filter(item => item?.key);
    const actions = (options.actions || []).filter(action => action?.label);
    const bar = document.createElement("div");
    bar.className = options.barClass || "backend-settings-tab-bar";
    if (options.title) {
      const title = document.createElement("strong");
      title.className = options.titleClass || "backend-settings-panel-title";
      title.textContent = options.title;
      bar.append(title);
    }

    const host = document.createElement("div");
    host.className = options.hostClass || "backend-settings-host";
    const entries = new Map();
    for (const item of items) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "tab-chip-button";
      const label = document.createElement("span");
      label.className = "tab-chip-label";
      label.textContent = item.label || item.key;
      button.append(label);
      // Keep the tab itself title-only.  The backend-provided explanation is
      // still available on hover/accessibility surfaces without making each
      // tab a two-line card in the compact settings bar.
      if (item.description) button.title = item.description;
      button.setAttribute("aria-label", label.textContent);
      if (item.buttonClass) button.classList.add(item.buttonClass);

      const panel = document.createElement("div");
      panel.className = ["tab-chip-content-panel", item.panelClass || ""]
        .filter(Boolean).join(" ");
      panel.hidden = true;
      button.addEventListener("click", () => toggle(item.key));
      bar.append(button); host.append(panel);
      entries.set(item.key, {button, panel, item, loaded: false});
    }

    if (actions.length) {
      const actionHost = document.createElement("div");
      actionHost.className = options.actionsClass || "backend-settings-actions";
      for (const action of actions) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = ["backend-settings-action", action.buttonClass || ""]
          .filter(Boolean).join(" ");
        button.textContent = action.label;
        button.disabled = typeof action.disabled === "function"
          ? Boolean(action.disabled()) : Boolean(action.disabled);
        if (action.title) button.title = action.title;
        button.addEventListener("click", event => action.onClick?.(event));
        actionHost.append(button);
      }
      bar.append(actionHost);
    }

    let activeKey = null;

    function activate(requestedKey, notify = true) {
      const key = entries.has(requestedKey) ? requestedKey : items[0]?.key;
      if (!key) return "";
      activeKey = key;
      for (const [entryKey, entry] of entries) {
        const active = entryKey === key;
        entry.button.classList.toggle("active", active);
        entry.panel.hidden = !active;
      }
      const entry = entries.get(key);
      if (entry && !entry.loaded) {
        const content = typeof entry.item.render === "function"
          ? entry.item.render() : entry.item.content;
        if (content) entry.panel.append(content);
        entry.loaded = true;
      }
      if (notify) options.onActivate?.(key);
      return key;
    }

    function close(requestedKey = activeKey, notify = true) {
      if (!requestedKey || activeKey !== requestedKey) return false;
      activeKey = null;
      for (const entry of entries.values()) {
        entry.button.classList.toggle("active", false);
        entry.panel.hidden = true;
      }
      if (notify) options.onActivate?.(null);
      return true;
    }

    function toggle(requestedKey, notify = true) {
      const key = entries.has(requestedKey) ? requestedKey : items[0]?.key;
      if (!key) return null;
      if (activeKey === key) {
        close(key, notify);
        return null;
      }
      return activate(key, notify);
  }

    function multiSelect(context, options = {}) {
      if (!window.FTMultiSelectFilter?.create) {
        throw new Error("共享多选筛选器尚未加载");
      }
      return window.FTMultiSelectFilter.create(context, options);
    }

    // `null` is an intentional closed state.  Other callers may omit the
    // initial key and still get the first tab as before.
    if (options.activeKey !== null) activate(options.activeKey, false);
    return Object.freeze({
      bar, host, activate, close, toggle,
      multiSelect,
      get activeKey() { return activeKey; },
      entries,
    });
  }

  window.FTTabChipContent = Object.freeze({
    create,
    multiSelect(context, options = {}) {
      if (!window.FTMultiSelectFilter?.create) {
        throw new Error("共享多选筛选器尚未加载");
      }
      return window.FTMultiSelectFilter.create(context, options);
    },
  });
})();
