(() => {
  function stateFrom(value = {}) {
    const revision = value.current_revision || value.revision || {};
    return {
      name: String(value.name || ""),
      description: String(value.description || ""),
      entrypoint: String(revision.entrypoint || value.entrypoint || "Strategy"),
      visibility: String(value.visibility || "private"),
      source_code: String(revision.source_code || value.source_code || ""),
      requirements: structuredClone(revision.requirements || value.requirements || {}),
    };
  }

  function create(context, value, options = {}) {
    const mode = options.mode || "edit";
    const state = stateFrom(value);
    const form = document.createElement("form");
    form.className = `strategy-editor strategy-editor-${mode}`;
    const overview = document.createElement("div");
    overview.className = "strategy-editor-overview";
    const controls = {};
    controls.name = input(context, "策略名称", state.name, "text", true);
    controls.description = input(context, "说明", state.description, "textarea", false);
    controls.entrypoint = input(context, "入口类", state.entrypoint, "text", true);
    overview.append(row(context, "策略名称", controls.name));
    overview.append(row(context, "说明", controls.description));
    overview.append(row(context, "入口类", controls.entrypoint));
    if (options.storageMode !== "configuration-inline") {
      controls.visibility = select(context, "可见性", state.visibility, [
        ["private", "仅自己"], ["shared", "指定共享"], ["public", "公开"],
      ]);
      overview.append(row(context, "可见性", controls.visibility));
    }
    const source = FTUI.codeEditor(state.source_code, {
      language: "python", required: true,
      placeholder: context.t("填写继承 Strategy 的 Python 源码"),
      ariaLabel: context.t("Python 策略源码"),
      className: "strategy-source-editor",
    });
    const sourcePanel = document.createElement("div");
    sourcePanel.className = "strategy-editor-source-panel";
    sourcePanel.append(FTUI.sourcePanel(context, source.element));
    const tabs = FTObjectDetailTabs.create(context, {
      objectKind: "strategy", mode,
      stateKey: `strategy-editor-tabs:${value.strategy_ref || "new"}`,
      tabs: [
        {key: "overview", label: "详情", editable: true},
        {key: "source", label: "源码", editable: true, save_mode: "auto"},
      ],
      panels: {overview, source: sourcePanel},
    });
    form.append(tabs.root);
    const status = document.createElement("small");
    status.className = "strategy-editor-status";
    form.append(status);
    const sync = () => {
      controls.name.value = state.name;
      controls.description.value = state.description;
      controls.entrypoint.value = state.entrypoint;
      if (controls.visibility) controls.visibility.value = state.visibility;
      source.setValue(state.source_code);
    };
    const mark = event => {
      if (event.target === controls.name) state.name = controls.name.value;
      if (event.target === controls.description) state.description = controls.description.value;
      if (event.target === controls.entrypoint) state.entrypoint = controls.entrypoint.value;
      if (event.target === controls.visibility) state.visibility = controls.visibility.value;
      if (event.target === source.textarea) state.source_code = source.value();
      const panel = event.target.closest?.(".object-detail-tab-panel");
      if (panel) tabs.setDirty(panel.dataset.tabKey, true);
      options.onChange?.(state);
    };
    form.addEventListener("input", mark);
    form.addEventListener("change", mark);
    form.addEventListener("submit", event => {
      event.preventDefault();
      options.onSubmit?.(state, status);
    });
    return Object.freeze({form, state, status, tabs, controls, source, sync});
  }

  function input(context, label, value, type, required) {
    const control = type === "textarea" ? document.createElement("textarea") : document.createElement("input");
    if (type !== "textarea") control.type = type;
    control.value = value;
    control.required = required;
    control.placeholder = context.t(label);
    control.setAttribute("aria-label", context.t(label));
    if (type === "textarea") control.rows = 3;
    return control;
  }

  function select(context, label, value, values) {
    const control = document.createElement("select");
    control.setAttribute("aria-label", context.t(label));
    values.forEach(([key, title]) => {
      const option = document.createElement("option");
      option.value = key; option.textContent = context.t(title); control.append(option);
    });
    control.value = value;
    return control;
  }

  function row(context, label, control) {
    const root = document.createElement("label");
    root.className = "strategy-editor-row";
    const title = document.createElement("span");
    title.textContent = context.t(label);
    root.append(title, control);
    return root;
  }

  window.FTStrategyLibraryEditor = Object.freeze({create, stateFrom});
})();
