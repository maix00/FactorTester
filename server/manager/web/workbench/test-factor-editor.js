(() => {
  function familyChooser(context, state, refresh) {
    const entries = FTTestFactorCatalog.familyEntries(state);
    const picker = FTTestChoicePicker.create(context, {
      className: "test-choice-picker test-factor-family-picker",
      compact: true,
      name: "test-factor-family",
      multi: false,
      items: entries.map(entry => ({
        value: entry.key,
        label: entry.title,
        description: [
          entry.description,
          context.t({
            local: "本地修订", public: "公共因子库", transient: "任务临时源码",
          }[entry.sourceKind] || entry.sourceKind),
          entry.ownerRef || entry.familyRef || "",
        ].filter(Boolean).join(" · "),
      })),
      selected: state.factorCatalog.selectedFamilyEntry?.key
        ? [state.factorCatalog.selectedFamilyEntry.key] : [],
      onChange: values => {
        const entry = entries.find(item => item.key === values[0]);
        if (entry) void FTTestFactorCatalog.selectFamily(context, state, entry, refresh);
      },
    });
    return FTTestFieldRow.create(
      context.t("因子家族"), picker.element,
      window.FTTestFieldHelp?.forField?.(
        state.manifest, "factor_family_ref", context,
      ) || "",
    );
  }

  function familyContent(context, state, refresh, sourceInput, options = {}) {
    const entry = state.factorCatalog.selectedFamilyEntry;
    if (!entry) return FTUI.empty(
      context.t("尚未选择因子家族"), context.t("搜索公共因子库或本地 Git 修订"),
    );
    if (entry.sourceKind === "public") {
      return registeredFactorPanel(context, state, entry, refresh, options);
    }
    const family = FTTestFactorSelection.selectedFamily(state);
    return family
      ? parameterEditor(context, state, family, refresh, sourceInput, options)
      : document.createElement("div");
  }

  function registeredFactorPanel(context, state, family, refresh, options = {}) {
    const factors = FTFactorFamilyPicker.familyFactors(family, state.factors);
    if (!factors.length) {
      return FTUI.empty(context.t("该家族暂无可用因子"), "");
    }
    const ids = factors.map(factor => FTTestFactorSelection.factorID(factor));
    const selected = FTTestFactorSelection.candidates(state)
      .filter(factor => ids.includes(FTTestFactorSelection.factorID(factor)))
      .map(factor => FTTestFactorSelection.factorID(factor));
    const selectedValues = state.kind === "ic" ? selected : selected.slice(-1);
    const picker = FTTestChoicePicker.create(context, {
      className: "test-choice-picker test-public-factor-picker",
      compact: true,
      name: "test-public-factors",
      multi: state.kind === "ic",
      items: factors.map(factor => ({
        value: FTTestFactorSelection.factorID(factor),
        label: FTTestFactorSelection.factorAlias(factor),
        description: factor.chinese_name || factor.description
          || factor.owner_alias || FTTestFactorSelection.factorAlias(factor),
      })).filter(item => item.value),
      selected: selectedValues,
      onChange: values => {
        const requested = new Set(values);
        for (const factor of factors) {
          const id = FTTestFactorSelection.factorID(factor);
          const exists = selectedValues.includes(id);
          if (requested.has(id) && !exists) {
            FTTestFactorSelection.addCandidate(state, factor);
            options.onCreated?.(factor);
          }
          if (!requested.has(id) && exists) FTTestFactorSelection.removeCandidate(state, factor);
        }
        refresh?.();
      },
    });
    return FTTestFieldRow.create(
      context.t("公共因子"), picker.element,
      window.FTTestFieldHelp?.forField?.(
        state.manifest,
        state.kind === "ic" ? ["factor_selections", "factor"] : ["factor", "factor_selections"],
        context,
      ) || "",
    );
  }

  function parameterEditor(context, state, family, refresh, sourceInput, options = {}) {
    const root = document.createElement("div");
    root.className = "test-factor-parameters";
    for (const parameter of family.params || []) {
      const control = parameterControl(
        parameter, state.values.factor_params || {}, context,
      );
      const help = parameter.desc || parameter.value_space_desc || parameter.type || "";
      root.append(FTTestFieldRow.create(parameter.alias || parameter.name, control, help));
    }
    const add = context.button(context.t("添加到因子候选"), async () => {
      await FTTestFactorCatalog.update(context, state, refresh, async () => {
        const entry = state.factorCatalog.selectedFamilyEntry;
        const value = entry?.sourceKind === "transient"
          ? await FTTestSourceUpload.instantiateFactor(
            context, state, entry, state.values.factor_params || {}, sourceInput,
          )
          : await FTTestFactorCatalog.nativeRequest("instantiate", {
            owner_ref: state.values.factor_owner_ref,
            git_commit: state.values.factor_git_commit,
            family: family.family,
            params: state.values.factor_params || {},
          });
        FTTestFactorSelection.addCandidate(state, value);
        options.onCreated?.(value);
      });
    });
    add.disabled = state.factorCatalog.selectedFamilyEntry?.sourceKind !== "transient"
      && !(state.values.factor_owner_ref && state.values.factor_git_commit);
    root.append(add); return root;
  }

  function parameterControl(parameter, values, context) {
    const options = Array.isArray(parameter.options) ? parameter.options : [];
    const initial = values[parameter.alias] ?? parameter.default_value ?? "";
    if (options.length && parameter.input_mode === "enum") {
      const picker = FTTestChoicePicker.create(context, {
        className: "test-choice-picker",
        compact: true,
        name: `factor-parameter-${parameter.alias}`,
        multi: false,
        items: options.map(option => ({
          value: String(option.value ?? ""),
          label: option.label || String(option.value ?? ""),
          description: option.description || option.label || String(option.value ?? ""),
        })),
        selected: [String(initial)],
        onChange: next => { values[parameter.alias] = next[0] ?? ""; },
      });
      values[parameter.alias] = picker.values[0] ?? String(initial);
      return picker.element;
    }
    const control = document.createElement("input");
    control.type = "text";
    control.value = initial;
    values[parameter.alias] = control.value;
    control.addEventListener("input", () => { values[parameter.alias] = control.value; });
    control.addEventListener("change", () => { values[parameter.alias] = control.value; });
    return control;
  }

  function selectField(label, options, value, updateValue, context) {
    const picker = FTTestChoicePicker.create(context, {
      className: "test-choice-picker",
      compact: true,
      name: `factor-source-${label}`,
      multi: false,
      items: [
        {value: "", label: `— ${label} —`, description: context.t("未选择")},
        ...options.map(option => ({
          ...option,
          value: String(option.value),
          description: option.description || option.label,
        })),
      ],
      selected: [value || ""],
      onChange: next => updateValue(next[0] || ""),
    });
    return FTTestFieldRow.create(label, picker.element);
  }

  function errorText(message) {
    const node = document.createElement("p"); node.className = "form-error";
    node.textContent = message; return node;
  }

  window.FTTestFactorEditor = Object.freeze({
    familyChooser, familyContent, parameterEditor, parameterControl,
    registeredFactorPanel, selectField, errorText,
  });
})();
