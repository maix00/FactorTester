(() => {
  "use strict";

  function create(context, parameters = [], initial = {}, options = {}) {
    const values = {...initial};
    const root = document.createElement("section");
    root.className = "factor-detail-parameter-editor";
    const header = document.createElement("div");
    header.className = "factor-detail-parameter-header";
    ["Key", "参数类型", "默认值", "Value"].forEach(label => {
      const cell = document.createElement("b");
      cell.textContent = context.t(label);
      header.append(cell);
    });
    root.append(header);
    for (const parameter of parameters) {
      const alias = String(parameter?.alias || parameter?.name || "").trim();
      if (!alias) continue;
      const row = document.createElement("div");
      row.className = "factor-detail-parameter-row";
      const key = document.createElement("b");
      key.className = "factor-detail-parameter-key";
      key.textContent = alias;
      const type = parameterType(context, parameter);
      const defaultValue = document.createElement("code");
      defaultValue.className = "factor-detail-parameter-default";
      defaultValue.textContent = displayValue(parameter.default_value);
      const value = document.createElement("div");
      value.className = "factor-detail-parameter-value";
      const initialValue = values[alias] ?? parameter.default_value ?? "";
      values[alias] = initialValue;
      if (parameter.type === "FactorParam") {
        renderReference(context, value, parameter, initialValue, values, options);
      } else {
        const input = document.createElement("input");
        input.type = "text";
        input.value = initialValue;
        input.addEventListener("input", () => { values[alias] = input.value; });
        value.append(input);
      }
      row.append(key, type, defaultValue, value);
      root.append(row);
    }
    return {root, values};
  }

  function renderReference(context, row, parameter, initialValue, values, options) {
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
    input.placeholder = context.t("填写");
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
    control.append(group(context.t("填写"), input),
      group(context.t("Column"), columnPicker.element || columnPicker),
      group(context.t("因子库"), factorPicker.element || factorPicker));
    row.append(control);
  }

  function parameterType(context, parameter) {
    const root = document.createElement("span");
    root.className = "factor-detail-parameter-type";
    const name = document.createElement("span");
    name.textContent = String(parameter.type || parameter.param_type || "Parameter");
    root.append(name);
    const description = String(parameter.desc || parameter.value_space_desc || "").trim();
    const fallback = parameter.type === "FactorParam"
      ? context.t("可填写能解析为 FactorExpr 的值，也可从 Column 或因子库选择。") : "";
    const help = description || fallback;
    if (help) root.append((window.FTUI?.helpIcon || window.FTHelp?.create)(help, {
      ariaLabel: context.t("查看参数类型说明"),
    }));
    return root;
  }

  function displayValue(value) {
    if (value === undefined || value === null || value === "") return "—";
    if (typeof value === "object") {
      return String(value.alias || value.factor_alias || value.value || JSON.stringify(value));
    }
    return String(value);
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
