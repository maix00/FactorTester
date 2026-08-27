(() => {
  function expression(value) {
    const modelValue = window.FTFactorModel?.factorExpression?.(value) || "";
    if (modelValue) return modelValue;
    for (const key of ["math_expr", "resolved_math_expr", "formula", "latex", "factor_expr", "expression"]) {
      const candidate = value?.[key];
      if (typeof candidate === "string" && candidate.trim()) return candidate.trim();
    }
    return "";
  }

  function summary(context, value) {
    const expressionValue = expression(value);
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

  function contextHelpText(help) {
    if (typeof help === "string") return help;
    return String(help?.title || help?.text || help?.description || "查看说明");
  }

  function parameterEditor(context, parameters = [], initial = {}) {
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
      const input = document.createElement("input");
      input.type = "text";
      input.value = values[alias] ?? parameter.default_value ?? "";
      values[alias] = input.value;
      input.addEventListener("input", () => { values[alias] = input.value; });
      row.append(title, input);
      if (parameter.desc || parameter.value_space_desc) {
        const help = document.createElement("small");
        help.textContent = parameter.desc || parameter.value_space_desc;
        row.append(help);
      }
      root.append(row);
    }
    return {root, values};
  }

  function parameterRows(value) {
    const item = value || {};
    const candidates = [
      item.params,
      item.factor_params,
      item.parameter_definitions,
    ];
    const raw = candidates.find(candidate => (
      Array.isArray(candidate) && candidate.length
    )) ?? candidates.find(candidate => (
      candidate && typeof candidate === "object"
        && !Array.isArray(candidate) && Object.keys(candidate).length
    ));
    if (Array.isArray(raw)) {
      return raw.flatMap(parameter => {
        const alias = String(
          parameter?.alias || parameter?.name || "",
        ).trim();
        if (!alias) return [];
        return [{
          alias,
          value: parameter.value ?? parameter.default_value ?? "",
          redacted: parameter.redacted === true,
          description: parameter.desc || parameter.value_space_desc || "",
        }];
      });
    }
    if (raw && typeof raw === "object") {
      return Object.entries(raw).map(([alias, parameter]) => ({
        alias,
        value: parameter && typeof parameter === "object"
          ? parameter.value ?? parameter.default_value ?? "" : parameter,
        redacted: parameter?.redacted === true,
        description: parameter?.desc || parameter?.value_space_desc || "",
      }));
    }
    return [];
  }

  function parameterTable(context, value) {
    const rows = parameterRows(value);
    if (!rows.length) return null;
    return FTUI.table(
      [context.t("参数"), context.t("值")],
      rows.map(parameter => [
        parameter.alias,
        parameter.redacted ? context.t("已隐藏") : parameter.value,
      ]),
    ).shell;
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
    return `/api/catalog/factor-sources/${kind}/${family}/versions${versionQuery(options)}`;
  }

  function versionEndpoint(options = {}, version = "current") {
    const kind = encodeURIComponent(options.sourceKind || "public");
    const family = encodeURIComponent(options.familyID || "");
    const selected = encodeURIComponent(version || "current");
    return `/api/catalog/factor-sources/${kind}/${family}/versions/${selected}${versionQuery(options)}`;
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
    return {
      sourceKind,
      familyID: String(familyID || "").trim(),
      ownerUsername: overrides.ownerUsername || item.owner_username || "",
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
    root.append(textNode, helpIcon({
      mode: "overlay",
      title: title || context.t("引用详情"),
      content: referenceOverlay(context, value, key),
    }, {ariaLabel: context.t("查看引用的真实身份")}));
    return root;
  }

  function provenance(context, value) {
    const item = value || {};
    const owner = item.factor_owner_ref || "";
    const family = item.factor_family_alias || item.factor_family_name || "";
    const familyFingerprint = item.family_formula_fingerprint || "";
    const selfFingerprint = item.self_formula_fingerprint || "";
    const factorRef = item.factor_ref || item.target_ref || "";
    const params = item.factor_params ?? item.params;
    if (!owner && !family && !familyFingerprint && !selfFingerprint
      && !factorRef && params == null) return null;
    const rows = [];
    if (factorRef) rows.push([
      context.t("因子引用"), referenceValue(
        context, {...item, factor_ref: factorRef}, "factor_ref", context.t("因子引用详情"),
      ),
    ]);
    if (owner) rows.push([
      context.t("factor_owner_ref"), referenceValue(
        context, {...item, factor_owner_ref: owner}, "factor_owner_ref",
        context.t("因子所有者详情"),
      ),
    ]);
    const familyIdentityValue = familyIdentity(item);
    if (familyIdentityValue.alias) {
      const familyValue = document.createElement("span");
      familyValue.className = "factor-reference-value";
      const familyText = document.createElement("span");
      familyText.textContent = familyIdentityValue.alias;
      familyValue.append(familyText);
      rows.push([context.t("冻结因子家族"), familyValue]);
    }
    if (familyFingerprint) rows.push([
      context.t("family_formula_fingerprint"), familyFingerprint,
    ]);
    if (selfFingerprint) rows.push([
      context.t("self_formula_fingerprint"), selfFingerprint,
    ]);
    if (params != null) {
      const valueNode = document.createElement("span");
      valueNode.className = "factor-reference-value";
      const count = Array.isArray(params) ? params.length : Object.keys(params || {}).length;
      const countNode = document.createElement("span");
      countNode.textContent = `${count}${context.t("个参数")}`;
      valueNode.append(
        countNode,
        helpIcon({
          mode: "overlay",
          title: context.t("因子参数详情"),
          content: referenceOverlay(context, item, context.t("因子参数详情")),
        }, {ariaLabel: context.t("查看因子参数")} ),
      );
      rows.push([context.t("factor_params"), valueNode]);
    }
    return FTUI.table(
      [context.t("RunSpec 字段"), context.t("值")], rows,
    ).shell;
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
    expression, loadSourceVersions, loadSourceVersion, parameterEditor,
    parameterRows,
    familyIdentity, fieldRow, helpIcon, parameterTable, pageClass, provenance, source,
    sourceOptions, sourceVersionHelp,
    sourceUnavailableText, sourceVersionHistory, versionItems, versionPicker,
    summary,
    sourceVersionsEndpoint, versionEndpoint,
  });
})();
