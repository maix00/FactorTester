(() => {
  const roleLabels = {
    ranking: "排序", screen: "筛选", entry: "入场",
    exit: "退出", sizing: "目标权重",
  };

  function factorRef(value) {
    if (typeof value === "string") return value.trim();
    if (!value || typeof value !== "object") return "";
    return String(value.ref || "").trim();
  }

  function factorLabel(value) {
    if (typeof value === "string") return value.trim();
    return String(value?.alias || factorRef(value)).trim();
  }

  function normalize(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(Object.entries(value)
      .map(([role, factor]) => [role, factorRef(factor)])
      .filter(([, ref]) => ref));
  }

  function visibleRoles(field, values) {
    const serialization = field?.serialization || {};
    const strategyKind = String(values?.strategy_intent_mode || "group");
    return [...(serialization.roles_by_strategy_kind?.[strategyKind]
      || serialization.allowed_roles || [])];
  }

  function sourceDescription(context, values, factor) {
    const refs = [...new Set((factor?.factor_set_refs || []).filter(Boolean))];
    const selectedSets = values?.factor_set_selections || [];
    const names = refs.map(ref => {
      const item = selectedSets.find(value => value?.target_ref === ref);
      return item?.title_zh || item?.set_id || ref;
    });
    if (names.length) return `${context.t("因子集合")}: ${names.join("、")}`;
    if (factor?.source_kind === "transient" || factor?.source_origin === "transient") {
      return context.t("现场新建/临时因子");
    }
    return context.t("因子库");
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
      .map(item => ({
        ref: factorRef(item), label: factorLabel(item),
        description: sourceDescription(context, values, item),
      }))
      .filter(item => item.ref);
    const bindings = normalize(options.value);
    for (const role of visibleRoles(field, values)) {
      const label = context.t(roleLabels[role] || role);
      const picker = FTTestChoicePicker.create(context, {
        className: "test-choice-picker",
        compact: true,
        name: `factor-role-${role}`,
        multi: false,
        disabled,
        items: [
          {
            value: "",
            label: context.t("使用主因子"),
            description: context.t("不为此角色设置单独因子"),
          },
          ...candidates.map(candidate => ({
            value: candidate.ref,
            label: candidate.label,
            description: candidate.description,
          })),
        ],
        selected: [bindings[role] || ""],
        onChange: values => {
          const next = {...bindings};
          if (values[0]) next[role] = values[0];
          else delete next[role];
          onChange(next);
        },
      });
      root.append(FTTestFieldRow.create(
        label, picker.element, "", {className: "factor-role-child-row"},
      ));
    }
    if (!root.childElementCount) {
      root.append(FTUI.empty(context.t("当前策略没有可绑定角色"), ""));
    }
    return root;
  }

  function section(options) {
    const {context, field} = options;
    const root = document.createElement("section");
    root.className = "factor-role-section factor-candidate-child-section";
    const heading = document.createElement("div");
    heading.className = "factor-role-section-heading";
    const copy = document.createElement("span");
    copy.className = "factor-role-section-copy";
    const title = document.createElement("b");
    title.textContent = context.t(field?.label || "因子角色");
    copy.append(title);
    const help = window.FTTestFieldHelp?.forField?.(
      options.manifest, options.fieldKey || "factor_role_bindings", context,
    );
    if (help && window.FTUI?.helpIcon) copy.append(" ", FTUI.helpIcon(help));
    const value = document.createElement("span");
    value.className = "factor-role-section-value";
    value.setAttribute("aria-hidden", "true");
    heading.append(copy, value);
    root.append(heading, render(options));
    return root;
  }

  window.FTTestFactorRoles = Object.freeze({
    factorRef, factorLabel, normalize, visibleRoles, display, render, section,
  });
})();
