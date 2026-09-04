// factor-parameter-section.js — the shared factor parameter section/table
// component family used by factor/family detail pages, their editors and the
// test-page overlays (view, edit and create modes, plus nested read-only
// blocks).
//
// A factor family defines parameters (and their defaults) but never concrete
// parameter values, so family-context tables render without a Value column;
// factor-instance tables always include it.  The tree header always carries
// the family template formula (参数 mode) — there is no 参数/值 toggle.
//
// Data normalization (parameterRows/parameterValues) and the nested-factor
// viewer chain stay in factor-detail-shared.js; this module reaches them
// through the FTFactorDetailShared export at render time, so it must load
// after factor-detail-shared.
(() => {
  const shared = () => window.FTFactorDetailShared;

  function templateFormula(value) {
    const source = shared()?.expression?.(value) || "";
    const mount = document.createElement("div");
    mount.className = "factor-detail-parameter-formula display-math";
    renderFormula(mount, source);
    return mount;
  }

  function renderFormula(mount, source) {
    mount.replaceChildren?.();
    if (window.katex) window.katex.render(source, mount, {
      displayMode: true, throwOnError: false,
    });
    else {
      mount.textContent = source;
      mount.classList?.add?.("factor-family-formula-raw");
    }
  }

  function parameterTable(context, value, options = {}) {
    const rows = shared()?.parameterRows?.(value, options) || [];
    if (!rows.length) return null;
    return parameterTree(context, value, rows, 0, options);
  }

  function createParameterList(context, parameters = [], initial = {}, options = {}) {
    const values = {...initial};
    // A factor family defines parameters (and their defaults) but never
    // concrete parameter values: family-context tables carry no Value
    // column.  Factor-instance tables always do (the instance value).
    const showValue = options.showValue !== false;
    const root = document.createElement("section");
    root.className = [
      "factor-detail-parameter-editor",
      options.readOnly ? "is-read-only" : "",
      showValue ? "" : "no-value-column",
    ].filter(Boolean).join(" ");
    const header = document.createElement("div");
    header.className = "factor-detail-parameter-header";
    const labels = ["参数名", "参数类型", "默认值"];
    if (showValue) labels.push("参数值");
    labels.forEach((label, index) => {
      const cell = document.createElement("b");
      cell.textContent = context.t(label);
      header.append(cell);
      // Nested/reference tables may hang an action (e.g. 编辑) next to the
      // value-column heading.
      if (showValue && index === labels.length - 1
        && options.valueHeaderExtra) {
        cell.append(" ", options.valueHeaderExtra);
      }
    });
    root.append(header);
    for (const parameter of parameters) {
      const alias = String(parameter?.alias || parameter?.name || "").trim();
      if (!alias) continue;
      const row = document.createElement("div");
      row.className = "factor-detail-parameter-row";
      const key = document.createElement("b"); key.className = "factor-detail-parameter-key"; key.textContent = alias;
      const type = shared()?.parameterType?.(context, parameter)
        || document.createElement("span");
      const defaultValue = document.createElement("code"); defaultValue.className = "factor-detail-parameter-default";
      defaultValue.textContent = String(parameter.default_value ?? "");
      row.append(key, type, defaultValue);
      root.append(row);
      if (!showValue) continue;
      const value = document.createElement("div"); value.className = "factor-detail-parameter-value";
      const initialValue = values[alias] ?? parameter.default_value ?? "";
      values[alias] = initialValue;
      const result = options.renderValue?.(value, parameter, initialValue, values, row) || {};
      if (!result.control && !value.childElementCount) {
        value.textContent = String(
          shared()?.parameterDisplayValue?.(parameter) ?? "",
        );
      }
      if (result.nested) row.classList?.add?.("factor-detail-parameter-row-factor");
      row.append(value);
      if (result.nested) root.append(result.nested);
    }
    return {root, values};
  }

  function parameterTree(
    context, value, rows = (shared()?.parameterRows?.(value) || []), depth = 0, options = {},
  ) {
    return parameterSection(context, value, rows, depth, options).root;
  }

  function parameterSection(
    context, value, rows = (shared()?.parameterRows?.(value) || []), depth = 0, options = {},
  ) {
    const root = document.createElement("details");
    root.className = depth
      ? "factor-detail-parameter-tree factor-detail-parameter-tree-nested"
      : "factor-detail-parameter-tree";
    root.open = true;
    root.style?.setProperty?.("--factor-parameter-depth", String(depth));
    const header = document.createElement("summary");
    header.className = "factor-detail-parameter-tree-header";
    const title = document.createElement("b");
    title.textContent = String(
      value?.factor_family_alias || value?.factor_family_name
      || value?.factor_alias || context.t("因子参数"),
    );
    const heading = document.createElement("span");
    heading.className = "factor-detail-parameter-tree-heading";
    heading.append(title, " ");
    const familyHelp = shared()?.familySourceHelp?.(context, value);
    if (familyHelp) heading.append(familyHelp);
    header.append(heading);
    const values = options.values || Object.fromEntries(
      rows.map(row => [row.alias, row.value]),
    );
    // Parameter-tree headers keep the shared local-formula component (the
    // original header layout, untouched).  Factor pages keep the 参数/值
    // mode toggle; family pages (showValue=false) hide the toggle controls
    // and stay on the 参数 (template) rendering.
    const showValue = options.showValue !== false;
    const local = shared()?.localFormula?.(context, value, values);
    let formula;
    let updateFormula;
    if (local) {
      if (!showValue) {
        local.root.classList.add("factor-detail-local-formula-parameter-only");
      }
      formula = local.root;
      updateFormula = next => local.update(next || {});
    } else {
      formula = templateFormula(value);
      updateFormula = () => renderFormula(formula, shared()?.expression?.(value) || "");
    }
    header.append(formula);
    const body = document.createElement("div");
    body.className = "factor-detail-parameter-tree-body";
    if (options.content) {
      body.append(options.content);
    } else {
      const list = createParameterList(context, rows, values, {
        readOnly: true,
        showValue: options.showValue !== false,
        valueHeaderExtra: options.valueHeaderExtra,
        renderValue: (valueCell, parameter) => {
          const displayed = parameter.redacted
            ? context.t("已隐藏")
            : shared()?.parameterValueCell?.(context, parameter);
          if (displayed && typeof displayed === "object"
            && typeof displayed.append === "function") {
            valueCell.append(displayed);
          } else {
            valueCell.textContent = String(displayed ?? "");
          }
          if (!parameter.nested_factor) return {control: true};
          const nestedRows = shared()?.parameterRows?.(parameter.nested_factor, options) || [];
          if (!nestedRows.length) return {control: true};
          const nested = parameterTree(
            context, parameter.nested_factor, nestedRows, depth + 1, options,
          );
          nested.dataset.parameterAlias = parameter.alias;
          nested.className = `${nested.className || ""} factor-detail-nested-parameter-row`.trim();
          return {control: true, nested};
        },
      });
      body.append(list.root);
    }
    root.append(header, body);
    return {root, update: updateFormula};
  }

  window.FTFactorParameterSection = Object.freeze({
    createParameterList, parameterSection, parameterTree, parameterTable,
  });
})();
