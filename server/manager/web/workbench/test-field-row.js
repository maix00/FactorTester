(() => {
  function helpIcon(help) {
    if (window.FTUI?.helpIcon) return window.FTUI.helpIcon(help);
    if (window.FTHelp?.create) return window.FTHelp.create(help);
    const icon = document.createElement("button");
    icon.type = "button";
    icon.className = "ft-help-icon";
    icon.textContent = "?";
    icon.setAttribute("aria-label", helpText(help));
    return icon;
  }

  function helpText(help) {
    if (help && typeof help === "object") {
      return String(help.text || help.description || help.desc || help.body || "").trim();
    }
    return String(help || "").trim();
  }

  function create(label, control, help = "", options = {}) {
    const row = document.createElement("div");
    row.className = ["test-setting-row", "test-field-row", options.className || ""]
      .filter(Boolean).join(" ");
    row.setAttribute("role", "row");
    if (options.disabled) {
      row.classList.add("is-locked");
      row.setAttribute("aria-disabled", "true");
    }
    const copy = document.createElement("span");
    copy.setAttribute("role", "rowheader");
    const heading = document.createElement("span");
    heading.className = "test-field-row-heading";
    const title = document.createElement("b");
    title.textContent = label || "";
    heading.append(title);
    const helpValue = options.help || help;
    const tooltip = helpText(options.title || helpValue);
    if (helpValue && (tooltip || typeof helpValue === "object")) {
      heading.append(" ", helpIcon(helpValue));
    }
    copy.append(heading);
    if (options.disabledReason) {
      const lock = document.createElement("small");
      lock.className = "test-field-row-lock";
      lock.textContent = options.disabledReason;
      copy.append(lock);
    }
    const value = document.createElement("div");
    value.className = "test-field-row-control";
    value.setAttribute("role", "cell");
    if (tooltip) row.setAttribute("aria-label", `${label || ""}：${tooltip}`);
    value.append(control);
    row.append(copy, value);
    return row;
  }

  function table(content, options = {}) {
    const root = document.createElement("div");
    root.className = ["test-field-table", options.className || ""]
      .filter(Boolean).join(" ");
    root.setAttribute("role", "table");
    if (content) root.append(content);

    let frame = 0;
    const update = () => {
      frame = 0;
      const rows = [...(root.querySelectorAll?.(".test-setting-row") || [])];
      const available = Number(root.getBoundingClientRect?.().width || root.clientWidth || 0);
      if (!rows.length || available <= 0 || !root.style?.setProperty) return;
      const natural = rows.reduce((largest, row) => {
        const copy = row.children?.[0];
        const heading = copy?.querySelector?.(".test-field-row-heading");
        return Math.max(largest, Number(copy?.scrollWidth || 0), Number(heading?.scrollWidth || 0));
      }, 0);
      // Keep most of the tab available to editors even when a localized label
      // or nested indentation is unusually long. Labels wrap inside this cap.
      const valueReserve = Math.min(360, Math.max(200, available * 0.58));
      const labelCap = Math.max(104, Math.min(448, available - valueReserve - 12));
      const labelWidth = Math.max(104, Math.min(natural || 160, labelCap));
      root.style.setProperty("--test-field-label-width", `${Math.round(labelWidth)}px`);
    };
    const schedule = () => {
      if (frame) return;
      if (typeof requestAnimationFrame === "function") {
        frame = requestAnimationFrame(update);
      } else {
        update();
      }
    };
    const resizeObserver = typeof ResizeObserver === "function"
      ? new ResizeObserver(schedule) : null;
    resizeObserver?.observe(root);
    const mutationObserver = typeof MutationObserver === "function"
      ? new MutationObserver(schedule) : null;
    mutationObserver?.observe(root, {childList: true, subtree: true});
    root.refreshFieldColumns = schedule;
    root.disconnectFieldColumns = () => {
      resizeObserver?.disconnect();
      mutationObserver?.disconnect();
      if (frame && typeof cancelAnimationFrame === "function") cancelAnimationFrame(frame);
      frame = 0;
    };
    schedule();
    return root;
  }

  window.FTTestFieldRow = Object.freeze({create, table});
})();
