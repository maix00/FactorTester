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
    const copy = document.createElement("span");
    const heading = document.createElement("span");
    heading.className = "test-field-row-heading";
    const title = document.createElement("b");
    title.textContent = label || "";
    heading.append(title);
    const helpValue = options.help || help;
    const tooltip = helpText(options.title || helpValue);
    if (helpValue && (tooltip || typeof helpValue === "object")) {
      heading.append(helpIcon(helpValue));
    }
    copy.append(heading);
    const value = document.createElement("div");
    value.className = "test-field-row-control";
    if (tooltip) row.setAttribute("aria-label", `${label || ""}：${tooltip}`);
    value.append(control);
    row.append(copy, value);
    return row;
  }

  window.FTTestFieldRow = Object.freeze({create});
})();
