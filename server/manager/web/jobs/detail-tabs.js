(() => {
  const definitions = [
    ["overview", "概览"],
    ["results", "结果"],
    ["configuration", "运行配置"],
    ["inputs", "提交物"],
    ["artifacts", "生成物"],
  ];

  function create(context, storageKey = "") {
    const root = document.createElement("div");
    root.className = "job-detail-tabs-shell";
    const tabs = document.createElement("nav");
    tabs.className = "research-section-tabs job-detail-tabs";
    tabs.setAttribute("role", "tablist");
    tabs.setAttribute("aria-label", context.t("测试任务详情分区"));
    const panels = Object.create(null);
    const buttons = Object.create(null);
    let selected = savedSelection(storageKey);

    definitions.forEach(([id, title]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "research-section-tab job-detail-tab";
      button.id = `job-detail-tab-${id}`;
      button.setAttribute("role", "tab");
      button.setAttribute("aria-controls", `job-detail-panel-${id}`);
      button.textContent = context.t(title);
      button.addEventListener("click", () => select(id, true));
      buttons[id] = button;
      tabs.append(button);

      const panel = document.createElement("section");
      panel.className = "job-detail-panel";
      panel.id = `job-detail-panel-${id}`;
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", button.id);
      panels[id] = panel;
    });

    root.append(tabs, ...definitions.map(([id]) => panels[id]));
    select(selected, false);
    return {root, panels, select, current: () => selected};

    function select(id, persist) {
      selected = panels[id] ? id : "overview";
      definitions.forEach(([candidate]) => {
        const active = candidate === selected;
        buttons[candidate].classList.toggle("active", active);
        buttons[candidate].setAttribute("aria-selected", String(active));
        buttons[candidate].tabIndex = active ? 0 : -1;
        panels[candidate].hidden = !active;
      });
      if (persist && storageKey) {
        try { sessionStorage.setItem(storageKey, selected); } catch (_) { /* no-op */ }
      }
      if (persist) root.dispatchEvent(new CustomEvent(
        "job-detail-tab-change", {detail: {id: selected}},
      ));
    }
  }

  function savedSelection(storageKey) {
    if (!storageKey) return "overview";
    try { return sessionStorage.getItem(storageKey) || "overview"; } catch (_) {
      return "overview";
    }
  }

  window.FTJobDetailTabs = Object.freeze({create});
})();
