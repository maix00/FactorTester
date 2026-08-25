(() => {
  const fallbackDefinitions = Object.freeze({
    family: [
      ["overview", "详情", true],
      ["source", "源码", true],
      ["parameters", "参数定义", false],
      ["members", "成员因子", false],
      ["identity", "身份与来源", false],
      ["jobs", "测试任务", false],
    ],
    factor: [
      ["overview", "详情", true],
      ["source", "源码", true],
      ["parameters", "参数", true],
      ["identity", "身份与来源", false],
      ["jobs", "测试任务", false],
    ],
    set: [
      ["overview", "详情", true],
      ["members", "成员因子", true],
      ["sources", "来源", false],
      ["identity", "身份与来源", false],
      ["jobs", "测试任务", false],
    ],
  });

  function definitions(kind, overrides = {}) {
    return (fallbackDefinitions[kind] || []).map(([key, label, editable]) => ({
      key,
      label,
      editable,
      ...(overrides[key] || {}),
    })).filter(item => item.hidden !== true);
  }

  function create(context, options = {}) {
    const mode = options.mode || "view";
    const items = options.tabs || definitions(options.objectKind, options.overrides);
    const root = document.createElement("section");
    root.className = [
      "object-detail-tabs-shell",
      `object-detail-tabs-${mode}`,
      options.className || "",
    ].filter(Boolean).join(" ");
    const tablist = document.createElement("nav");
    tablist.className = "research-section-tabs object-detail-tabs";
    tablist.setAttribute("role", "tablist");
    tablist.setAttribute("aria-label", context.t(options.label || "对象详情分区"));
    const panels = Object.create(null);
    const buttons = Object.create(null);
    const dirty = new Set(options.dirty || []);
    let selected = options.active || items[0]?.key || "";

    items.forEach((item, index) => {
      const button = document.createElement("button");
      const id = safeID(`${options.objectKind || "object"}-${item.key}-${index}`);
      button.type = "button";
      button.id = `object-detail-tab-${id}`;
      button.className = "research-section-tab object-detail-tab";
      button.dataset.tabKey = item.key;
      button.setAttribute("role", "tab");
      button.setAttribute("aria-controls", `object-detail-panel-${id}`);
      button.append(label(context, item, mode));
      button.addEventListener("click", () => select(item.key, true));
      button.addEventListener("keydown", event => navigate(event, item.key));
      buttons[item.key] = button;
      tablist.append(button);

      const panel = document.createElement("section");
      panel.id = `object-detail-panel-${id}`;
      panel.className = "object-detail-tab-panel";
      panel.dataset.tabKey = item.key;
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", button.id);
      if (mode !== "view") panel.append(modeNotice(context, item));
      const content = options.panels?.[item.key] || item.content;
      if (content) panel.append(content);
      panels[item.key] = panel;
    });

    root.append(tablist, ...items.map(item => panels[item.key]));
    select(selected, false);
    return Object.freeze({
      root, tablist, panels, buttons,
      current: () => selected,
      select,
      setDirty(key, value = true) {
        if (value) dirty.add(key); else dirty.delete(key);
        updateButtonState(key);
      },
    });

    function select(key, emit) {
      selected = panels[key] ? key : items[0]?.key || "";
      items.forEach(item => {
        const active = item.key === selected;
        buttons[item.key].classList.toggle("active", active);
        buttons[item.key].setAttribute("aria-selected", String(active));
        buttons[item.key].tabIndex = active ? 0 : -1;
        panels[item.key].hidden = !active;
      });
      items.find(item => item.key === selected)?.onActivate?.();
      if (emit) {
        root.dispatchEvent(new CustomEvent(
          "object-detail-tab-change", {detail: {key: selected}},
        ));
      }
    }

    function updateButtonState(key) {
      const button = buttons[key];
      if (!button) return;
      button.classList.toggle("is-dirty", dirty.has(key));
      const marker = button.querySelector(".object-detail-tab-state");
      if (marker) marker.textContent = stateText(context, items.find(
        item => item.key === key,
      ), mode, dirty.has(key));
    }

    function navigate(event, key) {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const index = items.findIndex(item => item.key === key);
      const next = event.key === "Home" ? 0
        : event.key === "End" ? items.length - 1
          : (index + (event.key === "ArrowRight" ? 1 : -1) + items.length)
            % items.length;
      select(items[next].key, true);
      buttons[items[next].key].focus();
    }
  }

  function label(context, item, mode) {
    const root = document.createElement("span");
    root.className = "object-detail-tab-label";
    const title = document.createElement("span");
    title.textContent = context.t(item.label || item.key);
    root.append(title);
    if (mode !== "view") {
      const state = document.createElement("small");
      state.className = "object-detail-tab-state";
      state.textContent = stateText(context, item, mode, false);
      root.append(state);
    }
    return root;
  }

  function stateText(context, item, mode, dirty) {
    if (dirty) return context.t("未保存");
    if (item?.editable === false) return context.t("只读");
    return context.t(mode === "create" ? "需填写" : "可修改");
  }

  function modeNotice(context, item) {
    const notice = document.createElement("p");
    notice.className = [
      "object-detail-tab-notice",
      item.editable === false ? "is-readonly" : "is-editable",
    ].join(" ");
    notice.textContent = item.editable === false
      ? context.t("此分区由对象身份或源码自动确定，当前模式下不可修改。")
      : context.t("此分区中的字段可以修改；保存前不会影响已登记对象。");
    return notice;
  }

  function safeID(value) {
    return String(value || "object").replace(/[^a-zA-Z0-9_-]+/g, "-");
  }

  window.FTObjectDetailTabs = Object.freeze({create, definitions});
})();
