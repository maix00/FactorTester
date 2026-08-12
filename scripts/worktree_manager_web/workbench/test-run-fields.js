(() => {
  function definitions(manifest) {
    return [...(manifest?.run_fields || [])]
      .sort((left, right) => Number(left.order || 0) - Number(right.order || 0));
  }

  function field(manifest, key) {
    return definitions(manifest).find(item => item.key === key) || null;
  }

  function forPlacement(manifest, placement) {
    return definitions(manifest).filter(item => item.placement === placement);
  }

  function initialValues(manifest) {
    const values = {};
    definitions(manifest).forEach(item => {
      if (item.placement === "outputs") return;
      values[item.key] = structuredClone(item.default);
    });
    return values;
  }

  function requestBody(state) {
    const result = {};
    definitions(state.manifest).forEach(item => {
      if (item.request_location !== "body") return;
      if (item.placement === "outputs") {
        result[item.key] = Array.isArray(state.outputRequests)
          ? [...state.outputRequests] : [];
        return;
      }
      const value = state.runValues?.[item.key];
      if (item.enabled_payload != null) {
        if (value) result[item.key] = structuredClone(item.enabled_payload);
        return;
      }
      if (value !== undefined) result[item.key] = structuredClone(value);
    });
    return result;
  }

  function controlField(item) {
    return {
      ...item, value: structuredClone(item.default), serialization: {},
      visible_when: {}, editable_when: {}, disabled_values_by_engine: {},
      engine_defaults: {}, default_when: {}, minimum: null, maximum: null, step: null,
    };
  }

  function row(context, state, item, refresh) {
    const root = document.createElement("div");
    root.className = "test-setting-row";
    const copy = document.createElement("span");
    const label = document.createElement("b"); label.textContent = context.t(item.label);
    const help = document.createElement("small"); help.textContent = context.t(item.help_text || "");
    copy.append(label, help);
    const fieldValue = controlField(item);
    const manifest = {defaults: {[item.key]: fieldValue}};
    const control = FTTestSettings.controlFor(
      item.key, fieldValue, manifest, state.runValues, context,
      {
        onCommit: ({key, value}) => { state.runValues[key] = value; },
        refresh,
      },
      false,
    );
    root.append(copy, control);
    return root;
  }

  function rows(context, state, items, refresh) {
    const root = document.createElement("div"); root.className = "test-setting-rows";
    items.forEach(item => root.append(row(context, state, item, refresh)));
    return root;
  }

  function render(context, state, refresh) {
    const regular = forPlacement(state.manifest, "run_options");
    const advanced = forPlacement(state.manifest, "advanced_run_options");
    if (!regular.length && !advanced.length) return null;
    const section = document.createElement("section"); section.className = "test-run-options";
    const heading = document.createElement("div"); heading.className = "section-heading";
    const copy = document.createElement("div");
    const title = document.createElement("h2"); title.textContent = context.t("运行选项");
    const note = document.createElement("p");
    note.textContent = context.t("这些选项只作用于本次运行，不写入可复用测试模板");
    copy.append(title, note); heading.append(copy); section.append(heading);
    if (regular.length) section.append(rows(context, state, regular, refresh));
    if (advanced.length) {
      const details = document.createElement("details"); details.className = "test-run-advanced";
      const summary = document.createElement("summary"); summary.textContent = context.t("诊断选项");
      details.append(summary, rows(context, state, advanced, refresh));
      section.append(details);
    }
    return section;
  }

  window.FTTestRunFields = Object.freeze({
    definitions, field, forPlacement, initialValues, render, requestBody,
  });
})();
