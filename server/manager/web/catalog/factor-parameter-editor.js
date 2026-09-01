(() => {
  "use strict";

  function create(context, parameters = [], initial = {}, options = {}) {
    const values = {...initial};
    const root = document.createElement("section");
    root.className = "factor-detail-parameter-editor";
    for (const parameter of parameters) {
      const alias = String(parameter?.alias || parameter?.name || "").trim();
      if (!alias) continue;
      const row = document.createElement("label");
      row.className = "test-object-field";
      const title = document.createElement("b");
      title.textContent = alias;
      const initialValue = values[alias] ?? parameter.default_value ?? "";
      values[alias] = initialValue;
      if (parameter.type === "FactorParam") {
        renderReference(context, row, title, parameter, initialValue, values, options);
      } else {
        const input = document.createElement("input");
        input.type = "text";
        input.value = initialValue;
        input.addEventListener("input", () => { values[alias] = input.value; });
        row.append(title, input);
      }
      if (parameter.desc || parameter.value_space_desc) {
        const help = document.createElement("small");
        help.textContent = parameter.desc || parameter.value_space_desc;
        row.append(help);
      }
      root.append(row);
    }
    return {root, values};
  }

  function renderReference(context, row, title, parameter, initialValue, values, options) {
    const alias = String(parameter.alias || parameter.name).trim();
    const columns = [...(parameter.options || [])];
    const factors = [...(options.factorItems || [])];
    const control = document.createElement("div");
    control.className = "factor-param-reference-control";
    const input = document.createElement("input");
    const display = value => String(value?.alias || value?.factor_alias || value || "").trim();
    let columnPicker;
    let factorPicker;
    const setValue = (value, source) => {
      values[alias] = value || "";
      input.value = ["column", "manual"].includes(source) ? display(values[alias]) : "";
      input.setCustomValidity("");
      const shown = display(values[alias]);
      columnPicker?.setValues?.(source === "column" && shown ? [shown] : []);
      factorPicker?.setValues?.(source === "factor" && shown ? [shown] : []);
    };
    columnPicker = picker(context, `factor-param-column-${alias}`, context.t("DataColumn"),
      columns, columns.some(item => item.value === initialValue) ? [initialValue] : [],
      selected => setValue(selected[0] || "", "column"));
    factorPicker = picker(context, `factor-param-factor-${alias}`, context.t("因子库"),
      factors, factors.some(item => item.value === initialValue) ? [initialValue] : [],
      selected => setValue(selected[0] || "", "factor"), options.onCreateFactor
        ? () => options.onCreateFactor(value => {
          const ref = String(value?.factor_alias || value?.alias || value?.factor_ref || "").trim();
          if (!ref) return;
          setValue(ref, "factor");
          options.onFactorCreated?.(value, alias);
        }) : null);
    input.type = "text";
    const initialText = display(initialValue);
    input.value = columns.some(item => item.value === initialValue)
      || numericConstant(initialText) !== null ? initialText : "";
    input.placeholder = context.t("手工输入数值、ColumnRef 或因子 alias");
    input.addEventListener("input", () => {
      const raw = input.value.trim().toUpperCase();
      const matched = columns.find(item => String(item.value || "").toUpperCase() === raw);
      input.setCustomValidity("");
      if (matched) setValue(String(matched.value), "column");
      else if (!raw) setValue("", "column");
    });
    input.addEventListener("change", async () => {
      const raw = input.value.trim();
      if (!raw || columns.some(item => String(item.value || "").toUpperCase() === raw.toUpperCase())) return;
      const constant = numericConstant(raw);
      if (constant !== null) {
        setValue(constant, "manual");
        return;
      }
      try {
        const resolved = await options.onValidateFactorAlias?.(raw);
        if (!resolved?.valid || !resolved.factor_alias) throw new Error(
          resolved?.error || context.t("因子 alias 无法解析"),
        );
        setValue(resolved.factor || String(resolved.factor_alias), "manual");
      } catch (error) {
        input.setCustomValidity(error?.message || context.t("请输入有效的 ColumnRef 或因子 alias"));
        input.reportValidity();
      }
    });
    control.append(group(context.t("数值 / DataColumn / ColumnRef / 因子 alias"),
      columnPicker.element || columnPicker, input),
    group(context.t("因子库因子"), factorPicker.element || factorPicker));
    row.append(title, control);
  }

  function numericConstant(value) {
    const text = String(value || "").trim();
    if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(text)) {
      return null;
    }
    const parsed = Number(text);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function picker(context, name, title, items, selected, onChange, onCreate = null) {
    return (window.FTTestObjectPicker || window.FTMultiSelectFilter).create(context, {
      compact: true, multi: false, name, title, items, selected, onChange, onCreate,
      createLabel: context.t("新建因子"),
    });
  }

  function group(label, ...children) {
    const root = document.createElement("div");
    root.className = "factor-param-choice-group";
    const title = document.createElement("small");
    title.textContent = label;
    root.append(title, ...children);
    return root;
  }

  window.FTFactorParameterEditor = Object.freeze({create});
})();
