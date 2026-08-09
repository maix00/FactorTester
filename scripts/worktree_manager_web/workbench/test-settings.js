(() => {
  const sharedModules = new Set([
    "factor", "factor_execution", "product_selection", "category_grouping",
    "run_window", "market_data_source", "market_data_frequency",
  ]);
  const externallyMountedKinds = new Set([
    "factor_owner_selection", "factor_revision_selection",
    "factor_family_selection", "factor_parameter_values",
    "factor_candidate_list", "factor_selection_list",
    "product_path_candidate_list", "product_path_selection_list",
    "category_candidate_list", "category_selection",
    "setting_template",
  ]);

  function initialValues(manifest, saved = {}) {
    return FTSettingRules.initialValues(manifest, saved);
  }

  function render(manifest, values, context, options = {}) {
    const root = document.createElement("div");
    root.className = "test-settings-columns";
    const tabs = manifest.tab_lists?.["local-settings"] || [];
    root.append(
      column(
        context.t("本地设置"), tabs.filter(tab => isSharedTab(tab, manifest)),
        manifest, values, context, options,
      ),
      column(
        context.t("专项设置"), tabs.filter(tab => !isSharedTab(tab, manifest)),
        manifest, values, context, options,
      ),
    );
    return root;
  }

  function isSharedTab(tab, manifest) {
    const fields = fieldsForTab(tab.key, manifest);
    return fields.length > 0 && fields.every(([, field]) => sharedModules.has(field.module));
  }

  function column(title, tabs, manifest, values, context, options) {
    const root = document.createElement("section");
    root.className = "test-settings-column";
    const heading = document.createElement("h2");
    heading.textContent = title;
    root.append(heading);
    for (const tab of tabs) {
      const fields = fieldsForTab(tab.key, manifest).filter(([, field]) => {
        const kind = field.serialization?.kind || "";
        return !externallyMountedKinds.has(kind) && FTSettingRules.isVisible(field, values);
      });
      if (!fields.length) continue;
      const details = document.createElement("details");
      details.className = "test-setting-group";
      details.open = Boolean(tab.default_mount_points?.includes("local-settings"));
      const summary = document.createElement("summary");
      summary.textContent = tab.label;
      const body = document.createElement("div");
      body.className = "test-setting-rows";
      for (const [key, field] of fields) {
        body.append(settingRow(key, field, manifest, values, context, options));
      }
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

  function settingRow(key, field, manifest, values, context, options) {
    const row = document.createElement("div");
    row.className = "test-setting-row";
    const copy = document.createElement("span");
    const label = document.createElement("b");
    label.textContent = field.label || key;
    const help = document.createElement("small");
    help.textContent = field.help_text || context.t("由测试配置保存并冻结");
    copy.append(label, help);
    const editable = FTSettingRules.isEditable(field, values);
    if (!editable && Object.keys(field.editable_when || {}).length) {
      const mode = document.createElement("small");
      mode.className = "test-setting-mode-note";
      mode.textContent = context.t("当前模式使用自动值");
      copy.append(mode);
    }
    row.append(copy, inputFor(key, field, manifest, values, context, options, !editable));
    return row;
  }

  function commit(key, field, manifest, values, value, options) {
    FTSettingRules.setValue(manifest, values, key, field, value);
    options.refresh?.();
  }

  function inputFor(key, field, manifest, values, context, options, disabled) {
    const value = FTSettingRules.valueFor(key, field, values);
    if (field.control_template === "factor_role_bindings") {
      return FTTestFactorRoles.render({
        field, values, context, disabled, value,
        onChange: next => commit(key, field, manifest, values, next, options),
      });
    }
    if (field.control_template === "custom_product_overrides") {
      return FTCustomProductOverrides.render({
        key, field, manifest, values, context, disabled,
        onPatch: patch => {
          FTSettingRules.patchValues(manifest, values, patch);
          options.refresh?.();
        },
      });
    }
    let control;
    if (field.control_template === "boolean") {
      control = document.createElement("input");
      control.type = "checkbox";
      control.checked = Boolean(value);
      control.disabled = disabled;
      control.addEventListener("change", () => {
        commit(key, field, manifest, values, control.checked, options);
      });
      return control;
    }
    if (field.control_template === "select" && field.options?.length) {
      control = document.createElement("select");
      const disabledValues = FTSettingRules.disabledValues(field, values);
      for (const option of field.options) {
        const item = document.createElement("option");
        item.value = String(option.value ?? "");
        item.textContent = option.label || item.value;
        item.disabled = disabledValues.has(item.value);
        control.append(item);
      }
      control.value = String(value ?? "");
    } else if (field.control_template === "custom") {
      control = document.createElement("textarea");
      control.rows = 3;
      control.value = JSON.stringify(value ?? null, null, 2);
      control.disabled = disabled;
      control.addEventListener("change", () => {
        try {
          const next = JSON.parse(control.value);
          control.setCustomValidity("");
          commit(key, field, manifest, values, next, options);
        } catch (_) {
          control.setCustomValidity(context.t("JSON 格式无效"));
          control.reportValidity?.();
        }
      });
      return control;
    } else {
      control = document.createElement("input");
      control.type = ["date", "time", "number"].includes(field.control_template)
        ? field.control_template : "text";
      control.value = value ?? "";
      if (field.minimum != null) control.min = field.minimum;
      if (field.maximum != null) control.max = field.maximum;
      if (field.step != null) control.step = field.step;
    }
    control.disabled = disabled;
    control.addEventListener("change", () => {
      const next = control.type === "number" && control.value !== ""
        ? Number(control.value) : control.value;
      commit(key, field, manifest, values, next, options);
    });
    return control;
  }

  window.FTTestSettings = {initialValues, render};
})();
