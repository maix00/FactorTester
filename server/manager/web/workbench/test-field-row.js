(() => {
  function create(label, control, help = "", options = {}) {
    const row = document.createElement("div");
    row.className = ["test-setting-row", "test-field-row", options.className || ""]
      .filter(Boolean).join(" ");
    const copy = document.createElement("span");
    const title = document.createElement("b");
    title.textContent = label || "";
    copy.append(title);
    if (help) {
      const hint = document.createElement("small");
      hint.textContent = help;
      copy.append(hint);
    }
    const value = document.createElement("div");
    value.className = "test-field-row-control";
    if (options.title) value.title = options.title;
    value.append(control);
    row.append(copy, value);
    return row;
  }

  window.FTTestFieldRow = Object.freeze({create});
})();
