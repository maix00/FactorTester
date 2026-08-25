(() => {
  function textControl(spec, state) {
    const control = document.createElement(spec.multiline ? "textarea" : "input");
    if (spec.multiline) control.rows = Number(spec.rows || 4);
    else control.type = spec.type || "text";
    control.value = state[spec.key] ?? spec.value ?? "";
    control.required = spec.required === true;
    control.readOnly = spec.readOnly === true;
    control.placeholder = spec.placeholder || "";
    control.addEventListener("input", () => { state[spec.key] = control.value; });
    return control;
  }

  function readonlyControl(spec, state) {
    const control = document.createElement("span");
    control.className = "factor-editor-readonly-value";
    control.textContent = state[spec.key] ?? spec.value ?? "";
    return control;
  }

  function pickerControl(context, spec, state) {
    const factory = window.FTTestObjectPicker?.create
      ? window.FTTestObjectPicker : window.FTMultiSelectFilter;
    if (!factory?.create) throw new Error("shared object picker is unavailable");
    const selected = Array.isArray(state[spec.key])
      ? state[spec.key] : spec.multi ? [] : [state[spec.key]].filter(Boolean);
    const picker = factory.create(context, {
      compact: spec.compact !== false,
      multi: spec.multi === true,
      name: spec.name || spec.key,
      title: spec.title || spec.label,
      items: spec.items || [],
      selected,
      searchPlaceholder: spec.searchPlaceholder || "",
      onChange: values => {
        state[spec.key] = spec.multi ? [...values] : values[0] || "";
        spec.onChange?.(state[spec.key], state);
      },
    });
    return picker.element || picker;
  }

  function control(context, spec, state) {
    if (spec.kind === "readonly") return readonlyControl(spec, state);
    if (spec.kind === "picker") return pickerControl(context, spec, state);
    if (spec.kind === "slot") return spec.content;
    return textControl(spec, state);
  }

  function render(context, definition) {
    const state = definition.state || {};
    const form = document.createElement("form");
    form.className = window.FTFactorDetailShared.pageClass(
      definition.mode,
      `factor-object-page factor-${definition.objectKind}-page ${definition.className || ""}`,
    );
    for (const spec of definition.fields || []) {
      const value = control(context, spec, state);
      const row = window.FTFactorDetailShared.fieldRow(
        context, context.t(spec.label), value,
      );
      if (spec.help) row.append(window.FTFactorDetailShared.helpIcon(spec.help));
      form.append(row);
    }
    for (const section of definition.sections || []) {
      if (section) form.append(section);
    }
    const status = document.createElement("small");
    status.className = "form-error";
    const actions = document.createElement("div");
    actions.className = "detail-actions";
    const cancel = context.button(context.t("取消"), () => definition.onCancel?.(state));
    cancel.type = "button";
    const save = context.button(context.t("保存"), () => form.requestSubmit());
    save.type = "button";
    save.className = "primary";
    actions.append(cancel, save);
    form.append(status, actions);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      save.disabled = true;
      status.textContent = "";
      try {
        await definition.onSubmit(state);
      } catch (error) {
        status.textContent = error.message || context.t("保存失败");
        save.disabled = false;
      }
    });
    context.setHeading(definition.title, definition.subtitle || "");
    context.updateActiveTab?.({title: definition.title});
    context.content.replaceChildren(form);
    return {form, state, status};
  }

  window.FTFactorObjectForm = Object.freeze({render});
})();
