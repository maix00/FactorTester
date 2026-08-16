(() => {
  // The list shell is deliberately domain-neutral.  A backend surface supplies
  // the tab descriptors, rows, and actions; this module only owns their common
  // disclosure/tab/chip layout.
  function create(options = {}) {
    const items = (options.items || []).filter(item => item?.key);
    const root = document.createElement("details");
    root.className = options.className || "tab-list-chip";
    root.open = options.open !== false;
    root.addEventListener("toggle", () => options.onToggle?.(root.open));

    const summary = document.createElement("summary");
    summary.className = options.summaryClass || "tab-list-chip-summary";
    const copy = document.createElement("span");
    copy.className = options.summaryCopyClass || "tab-list-chip-summary-copy";
    const title = document.createElement("b");
    title.textContent = options.title || "";
    copy.append(title);
    if (options.description) {
      const description = document.createElement("small");
      description.textContent = options.description;
      copy.append(description);
    }
    summary.append(copy);
    if (options.count != null) {
      const count = document.createElement("span");
      count.className = options.countClass || "tab-list-chip-count";
      count.textContent = String(options.count);
      summary.append(count);
    }

    const shell = document.createElement("div");
    shell.className = options.shellClass || "tab-list-chip-shell";
    const activeKey = options.activeKey === null
      ? null
      : (items.some(item => item.key === options.activeKey)
        ? options.activeKey : items[0]?.key);
    const tabset = FTTabChipContent.create({
      items,
      activeKey,
      barClass: options.barClass || "tab-list-chip-tab-bar",
      hostClass: options.hostClass || "tab-list-chip-host",
      actions: typeof options.actionsFor === "function"
        ? (options.actionsFor(activeKey || items[0]?.key) || []) : (options.actions || []),
      onActivate: key => options.onActivate?.(key),
    });
    shell.append(tabset.bar, tabset.host);
    const trailing = typeof options.trailing === "function"
      ? options.trailing(activeKey || items[0]?.key) : options.trailing;
    if (trailing) shell.append(trailing);
    root.append(summary, shell);
    return Object.freeze({root, shell, summary, tabset});
  }

  window.FTTabListChip = Object.freeze({create});
})();
