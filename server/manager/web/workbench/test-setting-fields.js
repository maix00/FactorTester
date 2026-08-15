(() => {
  const supportedControlTemplates = Object.freeze([
    "boolean", "custom", "custom_product_overrides", "date",
    "factor_role_bindings", "ic_decay_grid", "ic_delay_grid",
    "ic_horizon_grid", "number", "select", "text", "time",
  ]);
  const supportedControlSet = new Set(supportedControlTemplates);

  function fieldsForTab(tabKey, manifest) {
    return Object.entries(manifest.defaults || {})
      .filter(([, field]) => field.tab_key === tabKey)
      .sort((left, right) => Number(left[1].order || 0) - Number(right[1].order || 0));
  }

  function visibleFields(tab, manifest, values) {
    return fieldsForTab(tab.key, manifest).filter(([, field]) => (
      !field.adapter_managed && FTSettingRules.isVisible(field, values)
    ));
  }

  function commit(key, field, manifest, values, value, options) {
    if (typeof options.onCommit === "function") options.onCommit({key, field, value});
    else FTSettingRules.setValue(manifest, values, key, field, value);
    options.refresh?.();
  }

  function commitPatch(manifest, values, patch, options) {
    if (typeof options.onPatch === "function") options.onPatch(patch);
    else FTSettingRules.patchValues(manifest, values, patch);
    options.refresh?.();
  }

  function settingRow(key, field, manifest, values, context, options) {
    const row = document.createElement("div");
    row.className = "test-setting-row";
    const copy = document.createElement("span");
    const label = document.createElement("b");
    label.textContent = field.label || key;
    copy.append(label);
    const editable = FTSettingRules.isEditable(field, values);
    const hints = [field.help_text];
    if (!editable && Object.keys(field.editable_when || {}).length) {
      hints.push(context.t("当前模式使用自动值"));
    }
    const hint = hints.filter(Boolean).join("\n");
    if (hint) {
      row.title = hint;
      row.setAttribute("aria-label", `${label.textContent}: ${hint}`);
    }
    row.append(copy, inputFor(key, field, manifest, values, context, options, !editable));
    return row;
  }

  function inputFor(key, field, manifest, values, context, options, disabled) {
    const descriptor = field.value_descriptor || null;
    // New manifests identify the value contract independently from the legacy
    // control template.  Keep the template check only for old manifests and
    // domain adapters that still need a named renderer.
    if (!supportedControlSet.has(field.control_template) && !descriptor) {
      throw new Error(`未实现的测试设置控件: ${field.control_template}`);
    }
    const loaderDescriptor = window.FTStaticLoader?.controlDescriptor?.(field.control_template);
    if (loaderDescriptor?.group && loaderDescriptor.global && !window[loaderDescriptor.global]) {
      options.ensureControl?.(field);
      const deferred = document.createElement("span");
      deferred.className = "test-control-deferred";
      deferred.textContent = context.t("正在读取此设置控件…");
      return deferred;
    }
    const value = FTSettingRules.valueFor(key, field, values);
    if (field.control_template === "ic_horizon_grid") {
      return FTICHorizonSettings.renderHorizon({
        value, context, disabled,
        onChange: next => commit(key, field, manifest, values, next, options),
      });
    }
    if (field.control_template === "ic_delay_grid") {
      return FTICHorizonSettings.renderDelays({
        value, context, disabled,
        onChange: next => commit(key, field, manifest, values, next, options),
      });
    }
    if (field.control_template === "ic_decay_grid") {
      return FTICHorizonSettings.renderDecayLags({
        value, context, disabled,
        onChange: next => commit(key, field, manifest, values, next, options),
      });
    }
    if (field.control_template === "factor_role_bindings") {
      return FTTestFactorRoles.render({
        field, values, context, disabled, value,
        onChange: next => commit(key, field, manifest, values, next, options),
      });
    }
    if (field.control_template === "custom_product_overrides") {
      return FTCustomProductOverrides.render({
        key, field, manifest, values, context, disabled,
        onPatch: patch => commitPatch(manifest, values, patch, options),
      });
    }
    let control;
    if (descriptor?.value_type === "boolean" || field.control_template === "boolean") {
      control = document.createElement("input");
      control.type = "checkbox";
      control.checked = Boolean(value);
      control.disabled = disabled;
      control.addEventListener("change", () => {
        commit(key, field, manifest, values, control.checked, options);
      });
      return control;
    }
    if ((descriptor?.value_type === "enum" || field.control_template === "select")
      && field.options?.length) {
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
    } else if (
      descriptor?.editor === "json"
      || descriptor?.value_type === "object"
      || descriptor?.value_type === "array"
      || field.control_template === "custom"
    ) {
      control = document.createElement("textarea");
      control.className = "json-code json-editor";
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
      const valueType = descriptor?.value_type || field.control_template;
      control.type = ["date", "time", "number"].includes(valueType)
        ? valueType : (valueType === "integer" ? "number" : "text");
      control.value = value ?? "";
      if (descriptor?.minimum != null || field.minimum != null) {
        control.min = descriptor?.minimum ?? field.minimum;
      }
      if (descriptor?.maximum != null || field.maximum != null) {
        control.max = descriptor?.maximum ?? field.maximum;
      }
      if (descriptor?.step != null || field.step != null) {
        control.step = descriptor?.step ?? field.step;
      }
    }
    control.disabled = disabled;
    control.addEventListener("change", () => {
      const next = control.type === "number" && control.value !== ""
        ? Number(control.value) : control.value;
      commit(key, field, manifest, values, next, options);
    });
    return control;
  }

  window.FTTestSettingFields = Object.freeze({
    fieldsForTab, inputFor, settingRow, supportedControlTemplates, visibleFields,
    supportsControl: control => supportedControlSet.has(control),
  });
})();
