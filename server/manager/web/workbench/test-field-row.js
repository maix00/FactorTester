(() => {
  function helpIcon(help) {
    if (window.FTUI?.helpIcon) return window.FTUI.helpIcon(help);
    const icon = document.createElement("span");
    icon.className = "ft-help-icon";
    icon.textContent = "?";
    icon.title = help;
    icon.tabIndex = 0;
    icon.setAttribute("role", "img");
    icon.setAttribute("aria-label", help);
    return icon;
  }

  function create(label, control, help = "", options = {}) {
    const row = document.createElement("div");
    row.className = ["test-setting-row", "test-field-row", options.className || ""]
      .filter(Boolean).join(" ");
    const copy = document.createElement("span");
    const heading = document.createElement("span");
    heading.className = "test-field-row-heading";
    const title = document.createElement("b");
    title.textContent = label || "";
    heading.append(title);
    const tooltip = String(options.title || help || "").trim();
    if (tooltip) heading.append(helpIcon(tooltip));
    copy.append(heading);
    const value = document.createElement("div");
    value.className = "test-field-row-control";
    if (tooltip) {
      value.title = tooltip;
      row.setAttribute("aria-label", `${label || ""}：${tooltip}`);
    }
    value.append(control);
    row.append(copy, value);
    return row;
  }

  window.FTTestFieldRow = Object.freeze({create});
})();
