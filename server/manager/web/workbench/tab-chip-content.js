(() => {
  function create(options) {
    const items = (options.items || []).filter(item => item?.key);
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
      button.textContent = item.label || item.key;
      if (item.buttonClass) button.classList.add(item.buttonClass);

      const panel = document.createElement("div");
      panel.className = ["tab-chip-content-panel", item.panelClass || ""]
        .filter(Boolean).join(" ");
      panel.hidden = true;
      const content = typeof item.render === "function" ? item.render() : item.content;
      if (content) panel.append(content);
      button.addEventListener("click", () => activate(item.key));
      bar.append(button); host.append(panel);
      entries.set(item.key, {button, panel});
    }

    function activate(requestedKey, notify = true) {
      const key = entries.has(requestedKey) ? requestedKey : items[0]?.key;
      if (!key) return "";
      for (const [entryKey, entry] of entries) {
        const active = entryKey === key;
        entry.button.classList.toggle("active", active);
        entry.panel.hidden = !active;
      }
      if (notify) options.onActivate?.(key);
      return key;
    }

    const activeKey = activate(options.activeKey, false);
    return Object.freeze({bar, host, activate, activeKey, entries});
  }

  window.FTTabChipContent = Object.freeze({create});
})();
