(() => {
  function create(context, options = {}) {
    const header = document.createElement("div");
    header.className = ["job-result-tabs-header", options.className || ""]
      .filter(Boolean).join(" ");
    const tabs = document.createElement("div");
    tabs.className = "job-result-tabs";
    (options.tabs || []).forEach(tab => {
      const item = document.createElement("span");
      item.className = "job-result-tab-item";
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = context.t(tab.label || tab.key);
      button.classList.toggle("active", options.active === tab.key);
      button.setAttribute("aria-selected", String(options.active === tab.key));
      button.addEventListener("click", () => options.onChange?.(tab.key));
      item.append(button);
      if (tab.renamable && tab.onRename) {
        const rename = document.createElement("button");
        rename.type = "button";
        rename.className = "job-result-tab-edit";
        rename.textContent = "✎";
        rename.title = context.t("重命名");
        rename.setAttribute("aria-label", context.t("重命名"));
        rename.addEventListener("click", event => {
          event.preventDefault(); event.stopPropagation();
          const input = document.createElement("input");
          input.className = "job-result-tab-rename";
          input.value = String(tab.label || "");
          item.replaceChildren(input); input.focus(); input.select();
          let finished = false;
          const finish = async save => {
            if (finished) return;
            finished = true;
            const next = input.value.trim();
            try { if (save && next) await tab.onRename(next); }
            finally {
              button.textContent = save && next
                ? next : context.t(tab.label || tab.key);
              item.replaceChildren(button, rename);
            }
          };
          input.addEventListener("keydown", keyEvent => {
            if (keyEvent.key === "Enter") void finish(true);
            if (keyEvent.key === "Escape") void finish(false);
          });
          input.addEventListener("blur", () => void finish(true));
        });
        item.append(rename);
      }
      if (tab.closable && tab.onClose) {
        const close = document.createElement("button");
        close.type = "button";
        close.className = "job-result-tab-close";
        close.textContent = "×";
        close.title = context.t("删除此分析 Tab");
        close.setAttribute("aria-label", context.t("删除此分析 Tab"));
        close.addEventListener("click", event => {
          event.preventDefault(); event.stopPropagation();
          void tab.onClose();
        });
        item.append(close);
      }
      tabs.append(item);
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
