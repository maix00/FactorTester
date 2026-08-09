(() => {
  const roleLabels = {
    ranking: "排序", screen: "筛选", entry: "入场",
    exit: "退出", sizing: "目标权重",
  };

  function factorAlias(value) {
    if (typeof value === "string") return value.trim();
    if (!value || typeof value !== "object") return "";
    return String(
      value.factor_alias || value.factorAlias || value.alias || value.name || "",
    ).trim();
  }

  function normalize(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(Object.entries(value)
      .map(([role, factor]) => [role, factorAlias(factor)])
      .filter(([, alias]) => alias));
  }

  function visibleRoles(field, values) {
    const serialization = field?.serialization || {};
    const strategyKind = String(values?.strategy_intent_mode || "group");
    return [...(serialization.roles_by_strategy_kind?.[strategyKind]
      || serialization.allowed_roles || [])];
  }

  function display(value, context = null) {
    const bindings = normalize(value);
    const items = Object.entries(bindings);
    if (!items.length) return context?.t?.("全部使用主因子") || "全部使用主因子";
    return items.map(([role, alias]) => (
      `${context?.t?.(roleLabels[role] || role) || roleLabels[role] || role}=${alias}`
    )).join(" · ");
  }

  function render(options) {
    const {field, values, context, disabled, onChange} = options;
    const root = document.createElement("div");
    root.className = "factor-role-bindings";
    const candidates = (values?.[field?.serialization?.candidate_field || "factor_candidates"] || [])
      .map(item => ({alias: factorAlias(item), label: factorAlias(item)}))
      .filter(item => item.alias);
    const bindings = normalize(options.value);
    for (const role of visibleRoles(field, values)) {
      const row = document.createElement("label");
      const label = document.createElement("span");
      label.textContent = context.t(roleLabels[role] || role);
      const select = document.createElement("select");
      const primary = document.createElement("option");
      primary.value = "";
      primary.textContent = context.t("使用主因子");
      select.append(primary);
      for (const candidate of candidates) {
        const option = document.createElement("option");
        option.value = candidate.alias;
        option.textContent = candidate.label;
        select.append(option);
      }
      select.value = bindings[role] || "";
      select.disabled = Boolean(disabled);
      select.addEventListener("change", () => {
        const next = {...bindings};
        if (select.value) next[role] = select.value;
        else delete next[role];
        onChange(next);
      });
      row.append(label, select);
      root.append(row);
    }
    if (!root.childElementCount) {
      root.append(FTUI.empty(context.t("当前策略没有可绑定角色"), ""));
    }
    return root;
  }

  window.FTTestFactorRoles = Object.freeze({
    factorAlias, normalize, visibleRoles, display, render,
  });
})();
