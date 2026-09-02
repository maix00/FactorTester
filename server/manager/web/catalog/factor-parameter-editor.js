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
    const families = [...(options.familyItems || [])];
    const control = document.createElement("div");
    control.className = "factor-param-reference-control";
    const input = document.createElement("input");
    const display = value => String(value?.alias || value?.factor_alias || value || "").trim();
    const reference = value => String(value?.ref || value?.factor_ref || value || "").trim();
    let columnPicker;
    let factorPicker;
    let familyPicker;
    let activeSource = familyDraft(initialValue) ? "family"
      : factors.some(item => item.value === reference(initialValue)) ? "factor"
        : columns.some(item => item.value === initialValue) ? "column"
          : display(initialValue) ? "manual" : "";
    const groups = {};
    const syncSources = () => {
      for (const [source, element] of Object.entries(groups)) {
        const disabled = Boolean(activeSource && activeSource !== source);
        element.classList?.toggle?.("factor-param-choice-disabled", disabled);
        (element.querySelectorAll?.("input,select,button,textarea") || []).forEach(control => {
          control.disabled = disabled;
        });
      }
    };
    const setValue = (value, source) => {
      values[alias] = value || "";
      activeSource = value === "" || value === null ? "" : source;
      input.value = ["column", "manual"].includes(source) ? display(values[alias]) : "";
      input.setCustomValidity("");
      const shown = display(values[alias]);
      columnPicker?.setValues?.(source === "column" && shown ? [shown] : []);
      const selectedRef = reference(values[alias]);
      factorPicker?.setValues?.(source === "factor" && selectedRef ? [selectedRef] : []);
      familyPicker?.setValues?.(source === "family" && familyDraft(value)
        ? [familyRef(value.__factor_family)] : []);
      syncSources();
    };
    columnPicker = picker(context, `factor-param-column-${alias}`, context.t("DataColumn"),
      columns, columns.some(item => item.value === initialValue) ? [initialValue] : [],
      selected => setValue(selected[0] || "", "column"));
    factorPicker = picker(context, `factor-param-factor-${alias}`, context.t("因子库"),
      factors, factors.some(item => item.value === reference(initialValue))
        ? [reference(initialValue)] : [],
      selected => {
        const item = factors.find(candidate => candidate.value === selected[0]);
        setValue(item?.factor || "", "factor");
      });
    familyPicker = picker(
      context, `factor-param-family-${alias}`, context.t("因子家族"),
      families, familyDraft(initialValue) ? [familyRef(initialValue.__factor_family)] : [],
      async selected => {
        const item = families.find(candidate => candidate.value === selected[0]);
        if (!item) { setValue("", "family"); renderNested(); return; }
        const selectedFamily = await options.onSelectFamily?.(item.family) || item.family;
        setValue(makeFamilyDraft(selectedFamily), "family");
        renderNested();
      },
    );
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
    groups.manual = group(context.t("填写"), input);
    groups.column = group(context.t("Column"), columnPicker.element || columnPicker);
    groups.factor = group(context.t("因子库"), factorPicker.element || factorPicker);
    const createFamily = actionButton(context, context.t("新增因子家族"), async () => {
      await options.onCreateFamily?.(family => {
        if (!family) return;
        if (!families.some(item => item.value === familyRef(family))) {
          families.push({
            value: familyRef(family), label: familyLabel(family), family,
            description: context.t("本次配置中当场新建"),
          });
          familyPicker.setItems?.(families);
        }
        setValue(makeFamilyDraft(family), "family");
        renderNested();
      });
    }, {variant: "secondary"});
    createFamily.classList?.add?.("factor-param-create-family");
    groups.family = group(
      context.t("因子家族"), familyPicker.element || familyPicker, createFamily,
    );
    const nestedMount = document.createElement("div");
    nestedMount.className = "factor-param-nested-family-mount";
    const renderNested = () => {
      if (nestedMount.replaceChildren) nestedMount.replaceChildren();
      else nestedMount.children = [];
      const draft = values[alias];
      if (!familyDraft(draft)) return;
      const family = draft.__factor_family;
      const details = document.createElement("details");
      details.open = true;
      details.className = "factor-param-nested-family";
      const heading = document.createElement("summary");
      heading.className = "factor-param-nested-family-header";
      const title = document.createElement("b");
      title.textContent = familyLabel(family);
      heading.append(title, window.FTFactorDetailShared.familySourceHelp(context, family));
      const formulaValue = window.FTFactorDetailShared.expression(family);
      if (formulaValue) {
        const formula = document.createElement("div");
        formula.className = "factor-detail-parameter-formula display-math";
        if (window.katex) window.katex.render(formulaValue, formula, {
          displayMode: true, throwOnError: false,
        });
        else formula.textContent = formulaValue;
        heading.append(formula);
      }
      const nested = create(
        context, family.params || family.parameter_definitions || [],
        draft.parameter_values || {}, {...options, depth: (options.depth || 0) + 1},
      );
      draft.parameter_values = nested.values;
      details.append(heading, nested.root);
      nestedMount.append(details);
    };
    const allowFamilyComposition = Number(options.depth || 0)
      < Number(options.maxFamilyDepth ?? 12);
    control.append(
      groups.manual, groups.column, groups.factor,
      ...(allowFamilyComposition ? [groups.family] : []), nestedMount,
    );
    row.append(control);
    renderNested();
    syncSources();
  }

  function parameterType(context, parameter) {
    const root = document.createElement("span");
    root.className = "factor-detail-parameter-type";
    const name = document.createElement("span");
    name.textContent = String(parameter.type || parameter.param_type || "Parameter");
    root.append(name);
    const help = String(parameter.input_help || parameter.desc
      || parameter.value_space_desc || context.t("填写该参数类型允许的值。"))
      .trim();
    root.append((window.FTUI?.helpIcon || window.FTHelp?.create)(help, {
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

  function picker(context, name, title, items, selected, onChange) {
    return (window.FTTestObjectPicker || window.FTMultiSelectFilter).create(context, {
      compact: true, multi: false, name, title, items, selected, onChange,
    });
  }

  function familyDraft(value) {
    return Boolean(value && typeof value === "object"
      && value.__factor_family_draft === true && value.__factor_family);
  }

  function makeFamilyDraft(family) {
    return {
      __factor_family_draft: true,
      __factor_family: family,
      parameter_values: Object.fromEntries(
        (family?.params || family?.parameter_definitions || []).map(parameter => [
          parameter.alias || parameter.name,
          parameter.value ?? parameter.default_value ?? "",
        ]).filter(([alias]) => alias),
      ),
    };
  }

  function familyRef(value) {
    return String(value?.family_ref || value?.factor_family_alias
      || value?.family_alias || value?.name || "").trim();
  }

  function familyLabel(value) {
    return String(value?.factor_family_alias || value?.family_alias
      || value?.family_class_name || value?.name || "因子家族").trim();
  }

  function actionButton(context, label, onClick) {
    if (FTUI.actionButton) {
      return FTUI.actionButton(label, onClick, {variant: "secondary"});
    }
    if (context.button) return context.button(label, onClick, label);
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", onClick);
    return button;
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
