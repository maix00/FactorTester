(() => {
  function create(context, options = {}) {
    const header = document.createElement("div");
    header.className = ["job-result-tabs-header", options.className || ""]
      .filter(Boolean).join(" ");
    const tabs = document.createElement("div");
    tabs.className = "job-result-tabs";
    (options.tabs || []).forEach(tab => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = context.t(tab.label || tab.key);
      button.classList.toggle("active", options.active === tab.key);
      button.setAttribute("aria-selected", String(options.active === tab.key));
      button.addEventListener("click", () => options.onChange?.(tab.key));
      tabs.append(button);
    });
    header.append(tabs);
    const controls = document.createElement("div");
    controls.className = "job-result-tabs-controls";
    for (const control of options.controls || []) {
      if (control) controls.append(control);
    }
    if (controls.childElementCount) header.append(controls);
    return Object.freeze({header, tabs, controls});
  }

  window.FTJobResultTabs = Object.freeze({create});
})();
