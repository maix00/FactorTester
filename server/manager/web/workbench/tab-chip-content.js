(() => {
  function create(options) {
    const items = (options.items || []).filter(item => item?.key);
    const staticActions = (options.actions || []).filter(action => action?.label);
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

    const actionHost = typeof options.actionsFor === "function" || staticActions.length
      ? document.createElement("div") : null;
    if (actionHost) {
      actionHost.className = options.actionsClass || "backend-settings-actions";
      actionHost.hidden = true;
      bar.append(actionHost);
    }

    function renderActions(key) {
      if (!actionHost) return;
      const actions = (typeof options.actionsFor === "function"
        ? options.actionsFor(key) : staticActions || []).filter(action => action?.label);
      actionHost.replaceChildren();
      actionHost.hidden = actions.length === 0;
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
      renderActions(key);
      const entry = entries.get(key);
      if (entry && !entry.loaded) {
        let content = typeof entry.item.render === "function"
          ? entry.item.render() : entry.item.content;
        if (content && typeof options.wrapContent === "function") {
          content = options.wrapContent(content, entry.item) || content;
        }
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

  function createSettings(options = {}) {
    const root = options.root || document.createElement(options.rootTag || "div");
    root.className = options.rootClass
      || "backend-settings-shell test-settings-shell";
    const tabset = create({
      ...options,
      barClass: options.barClass || "backend-settings-tab-bar",
      hostClass: options.hostClass || "backend-settings-host",
      wrapContent: options.wrapContent || ((content, item) => (
        item?.fieldTable === false || !window.FTTestFieldRow?.table
          ? content : FTTestFieldRow.table(content)
      )),
    });
    let current = null;

    function itemChips(content) {
      if (options.autoChips === false) return content;
      const isChipRow = content?.className?.split?.(/\s+/)
        .includes("backend-settings-chip-row");
      if (content && !isChipRow) return content;
      const row = content || document.createElement("div");
      if (!content) row.className = "backend-settings-chip-row";
      const mountedItems = (options.items || []).filter(item => (
        item?.key && item.key !== "__manage__" && item.showChip !== false
      ));
      if (!mountedItems.length) return content;
      const groups = new Map();
      const extras = [];
      for (const child of [...(row.children || [])]) {
        if (child?.tabChipKey) groups.set(child.tabChipKey, child);
        else extras.push(child);
      }
      const ordered = mountedItems.map(item => {
        if (groups.has(item.key)) return groups.get(item.key);
        const group = document.createElement("div");
        group.className = "backend-settings-chip-group";
        group.tabChipKey = item.key;
        const heading = document.createElement("small");
        heading.className = "backend-settings-chip-group-label";
        heading.textContent = item.label || item.key;
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "backend-setting-chip setting-default";
        chip.title = options.context?.t?.("打开设置") || "打开设置";
        const label = document.createElement("span");
        label.className = "backend-setting-chip-label";
        label.textContent = options.context?.t?.("默认") || "默认";
        const value = document.createElement("span");
        value.className = "backend-setting-chip-value";
        value.textContent = options.context?.t?.("未设置（默认）") || "未设置（默认）";
        chip.append(label, value);
        chip.addEventListener("click", () => tabset.toggle(item.key));
        group.append(heading, chip);
        return group;
      });
      if (typeof row.replaceChildren === "function") row.replaceChildren(...ordered, ...extras);
      else {
        row.children = [];
        row.append(...ordered, ...extras);
      }
      return row;
    }

    function sync() {
      const children = [
        tabset.bar,
        ...(current ? [current] : []),
        tabset.host,
      ];
      if (typeof root.replaceChildren === "function") root.replaceChildren(...children);
      else {
        root.children = [];
        root.append(...children);
      }
    }

    function setCurrent(content, title = "") {
      current = null;
      const resolved = itemChips(content);
      if (resolved) {
        current = document.createElement("section");
        current.className = "test-settings-current";
        const currentTitle = title || options.currentTitle
          || options.context?.t?.("当前选择") || "当前选择";
        if (currentTitle) {
          const heading = document.createElement("strong");
          heading.textContent = currentTitle;
          current.append(heading);
        }
        current.append(resolved);
      }
      sync();
      return current;
    }

    setCurrent(null);
    return Object.freeze({root, tabset, setCurrent});
  }

  function createSettingsManager({context, sections = []}) {
    const root = document.createElement("div");
    root.className = "test-settings-manager";
    const list = document.createElement("div");
    list.className = "test-settings-manager-list";
    for (const section of sections) {
      if (!section?.items?.length) continue;
      const header = document.createElement("header");
      header.className = "test-settings-manager-section-heading";
      const title = document.createElement("b");
      title.textContent = context.t(section.label || "设置");
      header.append(title);
      if (section.description) header.title = context.t(section.description);
      list.append(header);
      for (const item of section.items) {
        const row = document.createElement("label");
        row.className = "test-settings-manager-row";
        if (item.description) row.title = context.t(item.description);
        const toggle = document.createElement("input");
        toggle.type = "checkbox";
        toggle.checked = Boolean(item.mounted);
        toggle.disabled = Boolean(item.locked);
        toggle.addEventListener("change", () => item.onToggle?.(toggle.checked));
        const body = document.createElement("span");
        body.className = "test-settings-manager-row-body";
        const copy = document.createElement("span");
        const label = document.createElement("b");
        label.textContent = context.t(item.label || item.key);
        copy.append(label); body.append(copy);
        const preview = item.preview?.();
        if (preview) {
          preview.className = `${preview.className || ""} test-settings-manager-defaults`.trim();
          body.append(preview);
        }
        row.append(toggle, body); list.append(row);
      }
    }
    root.append(list);
    return root;
  }

  window.FTTabChipContent = Object.freeze({
    create, createSettings, createSettingsManager,
    multiSelect(context, options = {}) {
      if (!window.FTMultiSelectFilter?.create) {
        throw new Error("共享多选筛选器尚未加载");
      }
      return window.FTMultiSelectFilter.create(context, options);
    },
  });
})();
