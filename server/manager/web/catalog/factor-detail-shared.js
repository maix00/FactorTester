(() => {
  function expression(value, options = {}) {
    const modelValue = window.FTFactorModel?.factorExpression?.(value, options) || "";
    if (modelValue) return modelValue;
    const keys = options.instance === true
      ? ["resolved_math_expr", "math_expr", "formula", "latex", "factor_expr", "expression"]
      : ["math_expr", "formula", "latex", "factor_expr", "expression", "resolved_math_expr"];
    for (const key of keys) {
      const candidate = value?.[key];
      if (typeof candidate === "string" && candidate.trim()) return candidate.trim();
    }
    return "";
  }

  function localFormula(context, value, values = {}) {
    const root = document.createElement("div");
    root.className = "factor-detail-local-formula";
    const controls = document.createElement("div");
    controls.className = "factor-detail-local-formula-controls";
    const formulaMount = document.createElement("div");
    formulaMount.className = "factor-detail-parameter-formula display-math";
    let mode = "parameters";
    const render = () => {
      const source = mode === "parameters" ? expression(value) : valueFormula(value, values);
      formulaMount.replaceChildren?.();
      if (window.katex) window.katex.render(source || "", formulaMount, {
        displayMode: true, throwOnError: false,
      });
      else formulaMount.textContent = source;
    };
    [["parameters", context.t("参数")], ["values", context.t("值")]].forEach(([modeName, label]) => {
      const button = document.createElement("button");
      button.type = "button"; button.className = "factor-detail-local-formula-toggle";
      button.textContent = label;
      button.addEventListener("click", () => { mode = modeName; render(); });
      controls.append(button);
    });
    root.append(controls, formulaMount); render();
    return {root, update: next => { values = next || {}; render(); }};
  }

  function valueFormula(value, values) {
    let result = expression(value);
    for (const parameter of parameterRows(value)) {
      const alias = String(parameter.alias || "").trim();
      if (!alias) continue;
      const raw = Object.prototype.hasOwnProperty.call(values, alias)
        ? values[alias] : parameter.value ?? parameter.default_value;
      const nested = nestedPreviewValue(raw, parameter);
      const shown = nested ? familySymbol(nested.value) : latexValue(previewScalarValue(raw ?? alias));
      const token = new RegExp("\\\\textcolor\\{red\\}\\{" + escapeRegExp(alias) + "\\}", "g");
      result = result.replace(token, "\\textcolor{red}{" + shown + "}");
    }
    return result;
  }

  function previewExpression(value, parameterValues = {}) {
    const state = {active: new Set(), emitted: new Set()};
    const root = unwrapFamilyDraft(value);
    const rootKey = previewNodeKey(root, parameterValues);
    if (rootKey) state.active.add(rootKey);
    const rendered = renderPreviewNode(root, parameterValues, state);
    if (rootKey) state.active.delete(rootKey);
    if (!rendered.body) return "";
    if (!rendered.lines.length) return rendered.body;
    const separator = " " + "\\" + "\\";
    return [
      "\\begin{aligned}",
      [...rendered.lines, stripFormulaEnvironment(rendered.body)]
        .join(separator),
      "\\end{aligned}",
    ].join("\n");
  }

  // Nested factors are displayed as intermediate definitions. We recurse only
  // through the dependency graph to collect those definitions; the parent
  // expression keeps the child family as a named intermediate value.
  function renderPreviewNode(value, parameterValues = {}, state) {
    const item = unwrapFamilyDraft(value);
    const resultValue = expression(item);
    if (!resultValue) return {body: "", lines: []};
    let result = resultValue;
    const lines = [];
    for (const parameter of parameterRows(item)) {
      const alias = String(parameter.alias || "").trim();
      if (!alias) continue;
      const raw = Object.prototype.hasOwnProperty.call(parameterValues || {}, alias)
        ? parameterValues[alias] : parameter.value;
      const nested = nestedPreviewValue(raw, parameter);
      let shown;
      if (nested) {
        shown = blue(familySymbol(nested.value));
        appendPreviewDefinition(lines, nested, state);
      } else {
        shown = latexValue(raw === "" || raw == null ? alias : previewScalarValue(raw));
      }
      const token = new RegExp(
        "\\\\textcolor\\{red\\}\\{" + escapeRegExp(alias) + "\\}", "g",
      );
      result = result.replace(token, nested ? shown : "\\textcolor{red}{" + shown + "}");
    }
    return {body: result, lines};
  }

  function appendPreviewDefinition(lines, nested, state) {
    const key = previewNodeKey(nested.value, nested.values);
    if (key && (state.active.has(key) || state.emitted.has(key))) return;
    if (key) {
      state.active.add(key);
      state.emitted.add(key);
    }
    const rendered = renderPreviewNode(nested.value, nested.values, state);
    if (key) state.active.delete(key);
    lines.push(...rendered.lines);
    const body = stripFormulaEnvironment(rendered.body);
    if (body) {
      const bodyLines = body.split(/\s*\\\\\s*/).map(line => line.trim())
        .filter(Boolean);
      if (bodyLines.length > 1) {
        bodyLines[bodyLines.length - 1] = childDefinition(
          blue(familySymbol(nested.value)), bodyLines[bodyLines.length - 1], false, ";",
        );
        lines.push(...bodyLines);
      } else {
        lines.push(childDefinition(
          blue(familySymbol(nested.value)), body, true, ";",
        ));
      }
    }
  }

  function nestedPreviewValue(raw, parameter) {
    if (raw?.__factor_family_draft === true && raw.__factor_family) {
      return {
        value: raw.__factor_family,
        values: raw.parameter_values || {},
      };
    }
    if (isNestedPreviewValue(raw)) {
      return {value: raw, values: nestedParameterValues(raw)};
    }
    if (isNestedPreviewValue(raw?.nested_factor)) {
      return {
        value: raw.nested_factor,
        values: nestedParameterValues(raw.nested_factor),
      };
    }
    if (isNestedPreviewValue(parameter?.nested_factor)) {
      return {
        value: parameter.nested_factor,
        values: nestedParameterValues(parameter.nested_factor),
      };
    }
    return null;
  }

  function isNestedPreviewValue(value) {
    return Boolean(value && typeof value === "object" && (
      Number(value.schema_version) === 2
      || value.ref || value.factor_ref
      || value.factor_family_alias || value.family_alias
      || value.math_expr || value.resolved_math_expr
    ));
  }

  function nestedParameterValues(value) {
    if (value?.__factor_family_draft === true) {
      return value.parameter_values || {};
    }
    const identityValues = value?.identity?.params || {};
    return Object.fromEntries(parameterRows(value).map(parameter => {
      const alias = parameter.alias;
      const valueFromRow = parameter.value;
      return [alias, valueFromRow !== undefined && valueFromRow !== ""
        ? valueFromRow : identityValues[alias] ?? ""];
    }).filter(([alias]) => alias));
  }

  function previewScalarValue(value) {
    if (!value || typeof value !== "object") return value;
    for (const key of ["alias", "factor_alias", "value"]) {
      if (value[key] !== undefined && value[key] !== null) return value[key];
    }
    return value;
  }

  function previewNodeKey(value, parameterValues = {}) {
    const item = unwrapFamilyDraft(value);
    const identity = item?.ref || item?.factor_ref || item?.factor_alias
      || item?.alias || item?.family_ref || item?.factor_family_alias
      || item?.family_alias || "";
    if (!identity) return "";
    let values = "";
    try {
      values = JSON.stringify(parameterValues || {});
    } catch (_) {
      values = "";
    }
    return String(identity) + "|" + values;
  }

  function unwrapFamilyDraft(value) {
    return value?.__factor_family_draft === true && value.__factor_family
      ? value.__factor_family : value;
  }

  function stripFormulaEnvironment(value) {
    let result = String(value || "").trim();
    for (const [opening, closing] of [
      ["\\begin{aligned}", "\\end{aligned}"],
      ["\\begin{align*}", "\\end{align*}"],
    ]) {
      if (result.startsWith(opening) && result.endsWith(closing)) {
        result = result.slice(opening.length, -closing.length).trim();
        break;
      }
    }
    return result;
  }

  function escapeRegExp(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function familySymbol(value) {
    const item = unwrapFamilyDraft(value);
    const alias = String(
      item?.factor_family_alias || item?.family_alias
      || item?.identity?.family_alias || item?.name || "Factor",
    );
    const safe = alias.replace(/[^\p{L}\p{N}]+/gu, "_").replace(/^_+|_+$/g, "");
    return String.raw`\mathrm{${safe || "Factor"}}`;
  }

  function blue(value) {
    return `\\textcolor{blue}{${value}}`;
  }

  function latexValue(value) {
    const text = String(value ?? "");
    const duration = /^([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(ns|us|ms|s|min|m|h|d|w)$/i
      .exec(text);
    if (duration) return String.raw`${duration[1]}\,\mathrm{${duration[2]}}`;
    return String.raw`\mathrm{${text.replace(/([_{}%&#])/g, "\\$1")}}`;
  }

  function summary(context, value, options = {}) {
    const expressionValue = options.descriptionOnly ? "" : expression(value, options);
    const description = String(
      value?.description || value?.chinese_name || value?.desc || "",
    ).trim();
    if (!description && !expressionValue) return document.createDocumentFragment();
    const root = document.createElement("section");
    root.className = "factor-family-summary";
    if (description) {
      const copy = document.createElement("p");
      copy.textContent = description;
      root.append(copy);
    }
    if (expressionValue) {
      const heading = document.createElement("h3");
      heading.textContent = context.t("FactorExpr 公式");
      const formula = document.createElement("div");
      formula.className = "factor-family-formula display-math";
      if (window.katex) {
        window.katex.render(expressionValue, formula, {
          displayMode: true, throwOnError: false,
        });
      } else {
        formula.textContent = expressionValue;
        formula.classList.add("factor-family-formula-raw");
      }
      root.append(heading, formula);
    }
    return root;
  }

  function pageClass(mode = "view", extra = "") {
    return [
      "detail-stack",
      "factor-detail-page",
      `factor-detail-page-${mode}`,
      extra,
    ].filter(Boolean).join(" ");
  }

  function familyIdentity(value, fallback = {}) {
    const item = value || {};
    const backup = fallback || {};
    const first = (...values) => values.find(value => (
      value !== undefined && value !== null && String(value).trim()
    ));
    const alias = String(first(
      item.factor_family_alias,
      item.factor_family_name,
      item.family_alias,
      item.family,
      backup.factor_family_alias,
      backup.factor_family_name,
      backup.family_alias,
      backup.family,
    ) || "").trim();
    const fingerprint = String(first(
      item.family_formula_fingerprint,
      backup.family_formula_fingerprint,
    ) || "").trim();
    return {alias, fingerprint};
  }

  function helpIcon(help, options = {}) {
    if (window.FTUI?.helpIcon) return window.FTUI.helpIcon(help, options);
    if (window.FTHelp?.create) return window.FTHelp.create(help, options);
    const icon = document.createElement("button");
    icon.type = "button";
    icon.className = "ft-help-icon";
    icon.textContent = "?";
    icon.setAttribute?.("aria-label", options.ariaLabel || contextHelpText(help));
    return icon;
  }

  function fieldHelp(help, options = {}) {
    return helpIcon(help, options);
  }

  function labeledField(label, help, context) {
    const root = document.createElement("span");
    root.className = "factor-reference-field";
    const text = document.createElement("span");
    text.textContent = String(label);
    root.append(text);
    if (help) {
      root.append(" ", fieldHelp(help, {
        ariaLabel: context.t("查看字段说明"),
      }));
    }
    return root;
  }

  function identityFieldRows(context, item, rows = []) {
    const append = (label, value, help = "") => {
      if (value === undefined || value === null || String(value).trim() === "") {
        return;
      }
      const cell = document.createElement("span");
      cell.className = "factor-reference-value";
      const text = document.createElement("span");
      text.textContent = String(value);
      cell.append(text);
      rows.push([labeledField(label, help, context), cell]);
    };
    append(
      context.t("因子引用"), item.factor_ref || item.ref || "",
      "冻结的因子实例身份：同一引用固定所有者、家族公式指纹、当前实例参数及嵌套依赖，运行和结果追溯都以它为准。",
    );
    append(
      context.t("factor_owner_ref"), item.factor_owner_ref || item.owner_ref
      || item.owner_username || "",
      "因子身份所在的所有者命名空间：不同所有者可以使用相同的因子家族 alias，但源码和公式版本可能不同。",
    );
    append(
      context.t("冻结因子家族"),
      item.factor_family_alias || item.factor_family_name
      || item.identity?.family_alias || "",
      "因子家族 alias 是公式模板的名称；它不代表源码版本，公式内容仍由 family_formula_fingerprint 固定。",
    );
    append(
      context.t("family_formula_fingerprint"),
      item.family_formula_fingerprint
      || item.identity?.family_formula_fingerprint || "",
      "家族公式源码的 SHA-256 指纹：只描述公式模板源码，不包含实例参数；相同 alias 但指纹不同说明家族源码已变化。",
    );
    append(
      context.t("self_formula_fingerprint"),
      item.self_formula_fingerprint
      || item.identity?.self_formula_fingerprint || "",
      "当前因子实例的公式指纹：由家族公式和具体参数共同决定；参数、嵌套因子或家族公式任一变化都会得到不同实例指纹。",
    );
    return rows;
  }

  function provenance(context, value, options = {}) {
    const item = value || {};
    const rows = identityFieldRows(context, item);
    const params = item.factor_params ?? item.params;
    if (!rows.length && params == null) return null;
    if (params != null) {
      const valueNode = document.createElement("span");
      valueNode.className = "factor-reference-value";
      const count = Array.isArray(params) ? params.length : Object.keys(params || {}).length;
      const countNode = document.createElement("span");
      countNode.textContent = `${count}${context.t("个参数")}`;
      valueNode.append(countNode);
      rows.push([labeledField(
        context.t("factor_params"),
        "当前实例冻结的参数集合。这里应显示每个参数的实际值；FactorParam 值必须继续递归显示其嵌套因子身份。",
        context,
      ), valueNode]);
    }
    return FTUI.table(
      [context.t("RunSpec 字段"), context.t("值")], rows,
    ).shell;
  }

  function contextHelpText(help) {
    if (typeof help === "string") return help;
    return String(help?.title || help?.text || help?.description || "查看说明");
  }

  function parameterRows(value, options = {}) {
    const item = value || {};
    const family = options.family || item.family || item.__factor_family || null;
    const candidates = [
      item.parameter_definitions,
      item.family_parameter_definitions,
      family?.parameter_definitions,
      family?.params,
      item.params,
      item.factor_params,
      item.parameters,
    ];
    const arrays = candidates.filter(candidate => (
      Array.isArray(candidate) && candidate.length
    ));
    const specific = arrays.find(candidate => candidate.some(parameter => (
      parameter && typeof parameter === "object"
      && specificParameterType(parameter)
    )));
    const withDefaults = arrays.find(candidate => candidate.some(parameter => (
      parameter && typeof parameter === "object"
      && parameter.default_value !== undefined
    )));
    const raw = specific || withDefaults || arrays[0] || candidates.find(candidate => (
      candidate && typeof candidate === "object"
        && !Array.isArray(candidate) && Object.keys(candidate).length
    ));
    const values = parameterValueMap(item);
    if (Array.isArray(raw)) {
      return raw.flatMap(parameter => normalizeParameterRow(parameter, values));
    }
    if (raw && typeof raw === "object") {
      return Object.entries(raw).flatMap(([alias, parameter]) => (
        normalizeParameterRow(
          parameter && typeof parameter === "object"
            ? {...parameter, alias: parameter.alias || alias}
            : {alias, value: parameter},
          values,
        )
      ));
    }
    return [];
  }

  function parameterValueMap(item) {
    const result = {};
    const collect = (source, allowEmpty = false) => {
      if (Array.isArray(source)) {
        for (const parameter of source) {
          const alias = String(parameter?.alias || parameter?.name || "").trim();
          if (!alias || !parameter || !Object.prototype.hasOwnProperty.call(parameter, "value")) {
            continue;
          }
          const value = parameter.value;
          if (allowEmpty || value !== undefined && value !== null && value !== "") {
            result[alias] = value;
          }
        }
        return;
      }
      if (!source || typeof source !== "object") return;
      for (const [rawAlias, parameter] of Object.entries(source)) {
        const alias = String(rawAlias || "").trim();
        if (!alias) continue;
        const value = parameter && typeof parameter === "object"
          && Object.prototype.hasOwnProperty.call(parameter, "value")
          ? parameter.value : parameter;
        if (allowEmpty || value !== undefined && value !== null && value !== "") {
          result[alias] = value;
        }
      }
    };
    // Compact params and identity params are fallbacks; empty values there are
    // normally the projection's missing-value marker. parameter_values is the
    // live editor state and intentionally wins, including an empty selection.
    collect(item.params);
    collect(item.factor_params);
    collect(item.identity?.params);
    collect(item.parameter_values, true);
    return result;
  }

  function parameterValues(value, options = {}) {
    return Object.fromEntries(parameterRows(value, options).map(parameter => [
      parameter.alias,
      parameter.value ?? parameter.default_value ?? "",
    ]).filter(([alias, current]) => alias && current !== ""));
  }

  function normalizeParameterRow(parameter, values = {}) {
    const alias = String(parameter?.alias || parameter?.name || "").trim();
    if (!alias) return [];
    const hasValue = Object.prototype.hasOwnProperty.call(values, alias);
    const fallback = parameter?.value ?? parameter?.default_value ?? "";
    return [{
      alias,
      value: hasValue ? values[alias] : fallback,
      default_value: parameter?.default_value,
      input_mode: parameter?.input_mode || "",
      options: parameter?.options || [],
      type: parameter?.type || parameter?.param_type || "Parameter",
      input_help: parameter?.input_help || parameter?.help_text || "",
      redacted: parameter?.redacted === true,
      description: parameter?.desc || parameter?.value_space_desc || "",
      nested_factor: parameter?.nested_factor
        || (parameter?.value?.nested_factor
          ? parameter.value.nested_factor : null)
        || (parameter?.value?.__factor_family_draft === true
          && parameter.value.__factor_family ? parameter.value : null)
        || (isNestedPreviewValue(parameter?.value) ? parameter.value : null)
        || (parameter?.value?.schema_version === 2
          && parameter.value.identity ? parameter.value : null),
    }];
  }

  function specificParameterType(parameter) {
    const type = String(parameter?.type || parameter?.param_type || "").trim();
    return Boolean(type && type !== "Parameter");
  }

  function parameterTable(context, value, options = {}) {
    const rows = parameterRows(value, options);
    if (!rows.length) return null;
    return parameterTree(context, value, rows, 0, options);
  }

  function createParameterList(context, parameters = [], initial = {}, options = {}) {
    const values = {...initial};
    const root = document.createElement("section");
    root.className = ["factor-detail-parameter-editor", options.readOnly ? "is-read-only" : ""]
      .filter(Boolean).join(" ");
    const header = document.createElement("div");
    header.className = "factor-detail-parameter-header";
    ["Key", "参数类型", "默认值", "Value"].forEach(label => {
      const cell = document.createElement("b"); cell.textContent = context.t(label); header.append(cell);
    });
    root.append(header);
    for (const parameter of parameters) {
      const alias = String(parameter?.alias || parameter?.name || "").trim();
      if (!alias) continue;
      const row = document.createElement("div");
      row.className = "factor-detail-parameter-row";
      const key = document.createElement("b"); key.className = "factor-detail-parameter-key"; key.textContent = alias;
      const type = parameterType(context, parameter);
      const defaultValue = document.createElement("code"); defaultValue.className = "factor-detail-parameter-default";
      defaultValue.textContent = String(parameter.default_value ?? "");
      const value = document.createElement("div"); value.className = "factor-detail-parameter-value";
      const initialValue = values[alias] ?? parameter.default_value ?? "";
      values[alias] = initialValue;
      const result = options.renderValue?.(value, parameter, initialValue, values, row) || {};
      if (!result.control && !value.childElementCount) value.textContent = parameterDisplayValue(parameter) ?? "";
      if (result.nested) row.classList?.add?.("factor-detail-parameter-row-factor");
      row.append(key, type, defaultValue, value);
      root.append(row);
      if (result.nested) root.append(result.nested);
    }
    return {root, values};
  }

  function parameterTree(
    context, value, rows = parameterRows(value), depth = 0, options = {},
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
    heading.append(title, " ", familySourceHelp(context, value));
    header.append(heading);
    // The tree header is the family formula.  The resolved/aggregated
    // instance formula belongs to the page-level formula box above it.
    const local = localFormula(context, value, Object.fromEntries(rows.map(row => [row.alias, row.value])));
    header.append(local.root);
    const body = document.createElement("div");
    body.className = "factor-detail-parameter-tree-body";
    const list = createParameterList(context, rows, Object.fromEntries(rows.map(row => [row.alias, row.value])), {
      readOnly: true,
      renderValue: (value, parameter) => {
        const displayed = parameter.redacted ? context.t("已隐藏") : parameterValueCell(context, parameter);
        if (displayed && typeof displayed === "object" && typeof displayed.append === "function") value.append(displayed);
        else value.textContent = String(displayed ?? "");
        if (!parameter.nested_factor) return {control: true};
        const nestedRows = parameterRows(parameter.nested_factor, options);
        if (!nestedRows.length) return {control: true};
        const nested = parameterTree(context, parameter.nested_factor, nestedRows, depth + 1, options);
        nested.dataset.parameterAlias = parameter.alias;
        nested.className = `${nested.className || ""} factor-detail-nested-parameter-row`.trim();
        return {control: true, nested};
      },
    });
    body.append(list.root);
    root.append(header, body);
    return root;
  }

  function parameterDisplayValue(parameter) {
    if (parameter?.nested_factor) {
      return String(
        parameter.nested_factor.factor_alias
        || parameter.nested_factor.alias
        || parameter.nested_factor.factor_family_alias
        || parameter.nested_factor.family_alias
        || "FactorExpr",
      );
    }
    return parameter?.value;
  }

  // View-mode nested FactorParam rows open the nested factor's own dedicated
  // page in the shared nested object overlay (FTObjectOverlay), the same
  // frame-stack infrastructure the workbench uses.  The opener button keeps the
  // established "?" affordance; the overlay renders the full factor page and
  // its heading comes from the nested page itself, so the parent page header
  // is never touched.
  function nestedFactorViewer(context, parameter) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ft-help-icon";
    button.textContent = "?";
    button.setAttribute("aria-label", context.t("查看内嵌因子"));
    button.addEventListener("click", event => {
      event.preventDefault?.();
      event.stopPropagation?.();
      openNestedFactorPage(context, parameter.nested_factor);
    });
    return button;
  }

  function openNestedFactorPage(context, nested) {
    if (!nested || typeof nested !== "object") return;
    const alias = String(
      nested?.factor_alias || nested?.alias || nested?.factor_family_alias || "",
    ).trim();
    const ref = String(
      nested?.factor_ref || nested?.ref || nested?.factor_alias || alias || "",
    ).trim();
    if (!ref) return;
    const family = nested.family || nested.__factor_family || {
      factor_family_alias: nested.factor_family_alias
        || nested.family_alias || "",
      parameter_definitions: nested.params || nested.parameter_definitions || [],
      math_expr: nested.math_expr || nested.formula || "",
    };
    const initialValue = {
      ...nested,
      ref,
      factor_ref: ref,
      factor_alias: alias,
      factor_family_alias: nested.factor_family_alias
        || nested.family_alias || family.factor_family_alias || "",
      family,
      __factor_family: family,
    };
    const options = {
      kind: "nested_factor", ref, mode: "view",
      initialValue, temporary: true,
    };
    const open = context.openObject || (window.FTObjectOverlay?.open
      ? childOptions => window.FTObjectOverlay.open(context, childOptions)
      : null);
    if (open) { open(options); return; }
    const loader = window.FTStaticLoader?.loadGroups;
    if (typeof loader !== "function") return;
    void Promise.resolve(loader(["object-overlay"])).then(() => {
      if (window.FTObjectOverlay?.open) {
        window.FTObjectOverlay.open(context, options);
      }
    }).catch(() => {});
  }

  function parameterValueCell(context, parameter) {
    if (!parameter?.nested_factor) return parameterDisplayValue(parameter);
    const root = document.createElement("span");
    root.className = "factor-detail-parameter-value";
    const alias = document.createElement("span");
    alias.textContent = parameterDisplayValue(parameter);
    root.append(alias, " ", nestedFactorViewer(context, parameter));
    return root;
  }

  function childDefinition(symbol, line, align, punctuation = "") {
    const clean = String(line).trim().replace(/[.;]\s*$/, "");
    const output = clean.match(/^(?:X|\\mathrm\{X\})_t\s*&?\s*:=\s*(.+)$/);
    return `${output ? "" : align ? "& " : ""}${symbol}_t := ${output ? output[1] : clean}${punctuation}`;
  }

  function formula(context, value) {
    const root = document.createElement("div");
    root.className = "factor-detail-parameter-formula display-math";
    if (window.katex) {
      window.katex.render(value, root, {displayMode: true, throwOnError: false});
    } else {
      root.textContent = value;
      root.classList?.add?.("factor-family-formula-raw");
    }
    return root;
  }

  function parameterType(context, parameter) {
    const root = document.createElement("span");
    root.className = "factor-detail-parameter-type";
    const name = document.createElement("span");
    name.textContent = String(parameter.type || parameter.param_type || "Parameter");
    const help = String(parameter.input_help || parameter.help_text
      || parameter.description || context.t("填写该参数类型允许的值。"));
    root.append(name, " ", (window.FTUI?.helpIcon || window.FTHelp?.create)(help, {
      ariaLabel: context.t("查看参数类型说明"),
    }));
    return root;
  }

  function fieldRow(context, labelText, control) {
    if (window.FTTestFieldRow?.create) {
      return window.FTTestFieldRow.create(labelText, control);
    }
    const row = document.createElement("div");
    row.className = "test-setting-row test-field-row";
    const label = document.createElement("span");
    label.className = "test-field-row-heading";
    const title = document.createElement("b");
    title.textContent = labelText;
    label.append(title);
    const value = document.createElement("div");
    value.className = "test-field-row-control";
    value.append(control);
    row.append(label, value);
    return row;
  }

  function sourceUnavailableText(context) {
    return context.t(
      "固定源码版本尚未同步到此服务器，无法恢复该版本；当前源码不会替代它。",
    );
  }

  function source(context, value) {
    const sourceCode = String(value?.source_code || "").trim();
    const unavailableReason = String(
      value?.source_unavailable_reason || context.t(
        "当前身份无权读取源码，或源码尚未同步到此服务器",
      ),
    ).trim();
    const root = document.createElement("section");
    root.className = "factor-detail-source";
    const heading = document.createElement("div");
    heading.className = "factor-detail-source-heading";
    const title = document.createElement("h3");
    title.textContent = context.t("Python 源码");
    heading.append(title);
    if (sourceCode) {
      const copy = context.button(context.t("复制"), async () => {
        await navigator.clipboard.writeText(sourceCode);
      }, context.t("复制源码"));
      copy.className = `${copy.className || ""} secondary`.trim();
      heading.append(copy);
    }
    const body = FTUI.code(
      sourceCode || unavailableReason || context.t(
        "当前身份无权读取源码，或源码尚未同步到此服务器",
      ),
      {
        language: sourceCode ? "python" : "",
        className: "factor-detail-source-code",
      },
    );
    root.append(heading, body);
    return root;
  }

  function versionQuery(options = {}) {
    const query = new URLSearchParams();
    if (options.ownerUsername) query.set("owner_username", options.ownerUsername);
    if (options.workspaceUsername) {
      query.set("workspace_username", options.workspaceUsername);
    }
    return query.toString() ? `?${query.toString()}` : "";
  }

  function sourceVersionsEndpoint(options = {}) {
    const kind = encodeURIComponent(options.sourceKind || "public");
    const family = encodeURIComponent(options.familyID || "");
    return `/api/factor-library/family-sources/${kind}/${family}/versions${versionQuery(options)}`;
  }

  function versionEndpoint(options = {}, version = "current") {
    const kind = encodeURIComponent(options.sourceKind || "public");
    const family = encodeURIComponent(options.familyID || "");
    const selected = encodeURIComponent(version || "current");
    return `/api/factor-library/family-sources/${kind}/${family}/versions/${selected}${versionQuery(options)}`;
  }

  function versionItems(context, payload) {
    const items = [{
      value: "__current__",
      label: context.t("当前最新版本"),
      description: context.t("使用因子家族当前公式版本"),
      exclusive: true,
    }];
    for (const version of payload?.versions || []) {
      const fingerprint = version?.family_formula_fingerprint;
      if (!fingerprint) continue;
      items.push({
        value: fingerprint,
        label: fingerprint.slice(0, 12),
        description: [
          version.subject || "",
          version.created_at ? FTUI.formatDate(version.created_at) : "",
        ].filter(Boolean).join(" · "),
      });
    }
    return items;
  }

  function sourceOptions(value, overrides = {}) {
    const item = value || {};
    const sourceKind = overrides.sourceKind || (
      item.factor_kind === "public" || item.source === "public"
        ? "public" : item.factor_kind === "local" ? "local" : "custom"
    );
    const familyID = overrides.familyID || item.factor_family_alias
      || item.factor_family_name || item.family_alias || item.family || "";
    const ownerRef = String(
      item.owner_username || item.factor_owner_ref || item.owner_ref || "",
    ).replace(/^principal:/, "");
    return {
      sourceKind,
      familyID: String(familyID || "").trim(),
      ownerUsername: overrides.ownerUsername || ownerRef,
      workspaceUsername: overrides.workspaceUsername || item.workspace_username || "",
    };
  }

  async function loadSourceVersions(context, value, options = {}) {
    const resolved = sourceOptions(value, options);
    if (!resolved.familyID || !["custom", "public"].includes(resolved.sourceKind)) {
      return {available: false, versions: [], current: null};
    }
    const payload = await context.api(sourceVersionsEndpoint(resolved));
    if (payload?.success === false) {
      throw new Error(payload.error || context.t("读取源码版本失败"));
    }
    return {...payload, sourceOptions: resolved};
  }

  async function loadSourceVersion(context, value, version = "current", options = {}) {
    const resolved = sourceOptions(value, options);
    if (!resolved.familyID || !["custom", "public"].includes(resolved.sourceKind)) {
      throw new Error(context.t("当前服务器没有可用的因子家族源码"));
    }
    const payload = await context.api(versionEndpoint(
      resolved, version || "current",
    ));
    if (payload?.success === false) {
      throw new Error(payload.error || context.t("读取源码版本失败"));
    }
    return {...payload, sourceOptions: resolved};
  }

  function versionPicker(context, value, options = {}) {
    const resolved = sourceOptions(value, options);
    let payload = options.payload || null;
    let loading = false;
    const pickerFactory = window.FTTestObjectPicker?.create
      || window.FTMultiSelectFilter?.create;
    if (!pickerFactory) throw new Error(context.t("下拉选择部件尚未加载"));
    const picker = pickerFactory(context, {
      compact: true,
      name: options.name || "factor-source-version",
      title: options.title || context.t("源码版本"),
      multi: false,
      items: versionItems(context, payload),
      selected: [options.selected || "__current__"],
      onChange: values => options.onChange?.(values[0] || "__current__"),
      onOpen: async () => {
        if (payload || loading) return;
        loading = true;
        try {
          payload = await loadSourceVersions(context, value, resolved);
          picker.setItems(versionItems(context, payload));
          options.onLoaded?.(payload);
        } catch (error) {
          options.onError?.(error);
        } finally {
          loading = false;
        }
      },
    });
    return {element: picker.element, picker, get payload() { return payload; }};
  }

  function sourceVersionHelp(context, options = {}) {
    const version = options.version || {};
    const fingerprint = version.family_formula_fingerprint || "current";
    const title = options.title || context.t("源码版本详情");
    return helpIcon({
      mode: "overlay",
      title,
      load: async () => {
        let payload;
        try {
          payload = await loadSourceVersion(context, options, fingerprint);
        } catch (_) {
          const unavailable = document.createElement("p");
          unavailable.className = "factor-source-version-unavailable";
          unavailable.textContent = sourceUnavailableText(context);
          return unavailable;
        }
        const root = document.createElement("div");
        root.className = "factor-source-version-overlay";
        const identity = document.createElement("dl");
        identity.className = "factor-source-version-overlay-meta";
        [
          [context.t("家族公式指纹"), payload.family_formula_fingerprint || "—"],
          [context.t("源码快照哈希"), payload.source_sha256 || "—"],
          [context.t("因子所有者引用"), payload.factor_owner_ref || "—"],
          [context.t("因子家族 alias"), payload.factor_family_alias || "—"],
        ].forEach(([label, value]) => {
          const term = document.createElement("dt"); term.textContent = label;
          const detail = document.createElement("dd"); detail.textContent = value;
          identity.append(term, detail);
        });
        root.append(identity, summary(context, payload));
        return root;
      },
    }, {ariaLabel: context.t("查看该源码版本的公式和身份")});
  }

  function familySourceHelp(context, value = {}) {
    const fingerprint = value.family_formula_fingerprint || "current";
    const icon = helpIcon({
      mode: "overlay",
      title: context.t("因子家族源码"),
      wide: true,
      load: async () => {
        if (String(value.source_code || "").trim()) {
          return source(context, value);
        }
        try {
          const payload = await loadSourceVersion(
            context, value, fingerprint, sourceOptions(value),
          );
          return source(context, payload);
        } catch (_) {
          const unavailable = document.createElement("p");
          unavailable.className = "factor-source-version-unavailable";
          unavailable.textContent = sourceUnavailableText(context);
          return unavailable;
        }
      },
    }, {ariaLabel: context.t("查看该因子家族冻结版本的源码")});
    icon.classList?.add?.("factor-detail-family-source-help");
    icon.addEventListener?.("click", event => event.stopPropagation());
    icon.addEventListener?.("keydown", event => event.stopPropagation());
    return icon;
  }

  function appendIdentityRow(rows, context, label, value) {
    const text = String(value ?? "").trim();
    if (!text || rows.some(row => row[0] === label)) return;
    rows.push([label, text]);
  }

  function referenceOverlay(context, value, kind) {
    const item = value || {};
    const raw = kind === "factor_ref"
      ? item.factor_ref || item.target_ref || ""
      : kind === "factor_owner_ref"
        ? item.factor_owner_ref || ""
        : "";
    const root = document.createElement("div");
    root.className = "factor-reference-overlay";
    const rows = [];
    appendIdentityRow(rows, context, context.t("引用值"), raw);
    appendIdentityRow(rows, context, context.t("具体因子 alias"),
      item.factor_alias || item.alias);
    appendIdentityRow(rows, context, context.t("因子所有者"),
      item.factor_owner_ref || item.owner_ref
        || item.owner_username);
    appendIdentityRow(rows, context, context.t("所有者名称"),
      item.owner_alias || item.owner_username);
    appendIdentityRow(rows, context, context.t("组织"),
      item.owner_organization_name || item.organization_name);
    appendIdentityRow(rows, context, context.t("因子家族 alias"),
      item.factor_family_alias || item.factor_family_name || item.family_alias
    );
    appendIdentityRow(rows, context, context.t("家族公式指纹"),
      item.family_formula_fingerprint);
    appendIdentityRow(rows, context, context.t("因子公式指纹"),
      item.self_formula_fingerprint);
    const table = FTUI.table(
      [context.t("字段"), context.t("值")], rows,
    );
    root.append(table.shell);
    const params = item.factor_params ?? item.params;
    if (params != null) {
      const serialized = typeof params === "string"
        ? params : JSON.stringify(params, null, 2);
      root.append(FTUI.code(serialized || "{}", {language: "json"}));
    }
    return root;
  }

  function referenceValue(context, value, key, title) {
    const root = document.createElement("span");
    root.className = "factor-reference-value";
    const raw = value?.[key] || "";
    const textNode = document.createElement("span");
    textNode.textContent = raw || context.t("未设置");
    root.append(textNode, " ", helpIcon({
      mode: "overlay",
      title: title || context.t("引用详情"),
      content: referenceOverlay(context, value, key),
    }, {ariaLabel: context.t("查看引用的真实身份")}));
    return root;
  }

  function sourceVersionHistory(context, value, options = {}) {
    const root = document.createElement("section");
    root.className = "factor-source-version-history";
    const status = document.createElement("small");
    status.className = "factor-source-version-status";
    const selected = options.selected || "__current__";
    const picker = versionPicker(context, value, {
      ...options,
      selected,
      onChange: options.onChange,
      onLoaded: payload => {
        status.textContent = payload?.available === false
          ? context.t("当前服务器没有可用的源码版本历史") : "";
        options.onLoaded?.(payload);
      },
      onError: error => {
        status.textContent = sourceUnavailableText(context);
        options.onError?.(error);
      },
    });
    root.append(
      fieldRow(context, context.t("源码版本"), picker.element),
      status,
    );
    return root;
  }

  window.FTFactorDetailShared = Object.freeze({
    expression, loadSourceVersions, loadSourceVersion,
    parameterRows, parameterValues, createParameterList, localFormula,
    familyIdentity, familySourceHelp, fieldRow, helpIcon, parameterTable,
    previewExpression,
    pageClass, provenance, source,
    sourceOptions, sourceVersionHelp,
    sourceUnavailableText, sourceVersionHistory, versionItems, versionPicker,
    summary,
    sourceVersionsEndpoint, versionEndpoint,
  });
})();
