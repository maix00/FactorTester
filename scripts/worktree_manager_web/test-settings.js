(() => {
  const sharedModules = new Set([
    "factor", "factor_execution", "product_selection", "category_grouping",
    "run_window", "market_data_source", "market_data_frequency",
  ]);
  // Dedicated components mount these manifest fields for both test types.
  const externallyMountedKinds = new Set([
    "factor_owner_selection", "factor_revision_selection",
    "factor_family_selection", "factor_parameter_values",
    "factor_candidate_list", "factor_selection_list",
    "product_path_candidate_list", "product_path_selection_list",
    "setting_template",
  ]);

  function initialValues(manifest, saved = {}) {
    const values = {};
    for (const [key, field] of Object.entries(manifest.defaults || {})) {
      values[key] = saved[key] ?? structuredClone(field.value);
    }
    return values;
  }

  function render(manifest, values, context) {
    const root = document.createElement("div");
    root.className = "test-settings-columns";
    const tabs = manifest.tab_lists?.["local-settings"] || [];
    root.append(
      column(context.t("本地设置"), tabs.filter(tab => isSharedTab(tab, manifest)), manifest, values, context),
      column(context.t("专项设置"), tabs.filter(tab => !isSharedTab(tab, manifest)), manifest, values, context),
    );
    return root;
  }

  function isSharedTab(tab, manifest) {
    const fields = fieldsForTab(tab.key, manifest);
    return fields.length > 0 && fields.every(([, field]) => sharedModules.has(field.module));
  }

  function column(title, tabs, manifest, values, context) {
    const root = document.createElement("section");
    root.className = "test-settings-column";
    const heading = document.createElement("h2");
    heading.textContent = title;
    root.append(heading);
    for (const tab of tabs) {
      const fields = fieldsForTab(tab.key, manifest).filter(([, field]) => {
        const kind = field.serialization?.kind || "";
        return !externallyMountedKinds.has(kind);
      });
      if (!fields.length) continue;
      const details = document.createElement("details");
      details.className = "test-setting-group";
      details.open = Boolean(tab.default_mount_points?.includes("local-settings"));
      const summary = document.createElement("summary");
      summary.textContent = tab.label;
      const body = document.createElement("div");
      body.className = "test-setting-rows";
      for (const [key, field] of fields) body.append(settingRow(key, field, values, context));
      details.append(summary, body);
      root.append(details);
    }
    return root;
  }

  function fieldsForTab(tabKey, manifest) {
    return Object.entries(manifest.defaults || {})
      .filter(([, field]) => field.tab_key === tabKey)
      .sort((left, right) => Number(left[1].order || 0) - Number(right[1].order || 0));
  }

  function settingRow(key, field, values, context) {
    const row = document.createElement("label");
    row.className = "test-setting-row";
    const copy = document.createElement("span");
    const label = document.createElement("b");
    label.textContent = field.label || key;
    const help = document.createElement("small");
    help.textContent = field.help_text || context.t("由测试配置保存并冻结");
    copy.append(label, help);
    const control = inputFor(key, field, values);
    row.append(copy, control);
    return row;
  }

  function inputFor(key, field, values) {
    let control;
    if (field.control_template === "boolean") {
      control = document.createElement("input");
      control.type = "checkbox";
      control.checked = Boolean(values[key]);
      control.addEventListener("change", () => { values[key] = control.checked; });
      return control;
    }
    if (field.control_template === "select" && field.options?.length) {
      control = document.createElement("select");
      for (const option of field.options) {
        const item = document.createElement("option");
        item.value = String(option.value ?? "");
        item.textContent = option.label || item.value;
        control.append(item);
      }
      control.value = String(values[key] ?? "");
    } else if (field.control_template === "custom") {
      control = document.createElement("textarea");
      control.rows = 3;
      control.value = JSON.stringify(values[key] ?? null, null, 2);
      control.addEventListener("change", () => {
        try { values[key] = JSON.parse(control.value); control.setCustomValidity(""); }
        catch (_) { control.setCustomValidity("JSON 格式无效"); }
      });
      return control;
    } else {
      control = document.createElement("input");
      control.type = ["date", "time", "number"].includes(field.control_template)
        ? field.control_template : "text";
      control.value = values[key] ?? "";
      if (field.minimum != null) control.min = field.minimum;
      if (field.maximum != null) control.max = field.maximum;
      if (field.step != null) control.step = field.step;
    }
    control.addEventListener("change", () => {
      values[key] = control.type === "number" && control.value !== ""
        ? Number(control.value) : control.value;
    });
    return control;
  }

  window.FTTestSettings = {initialValues, render};
})();
