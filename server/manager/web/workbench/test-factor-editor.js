(() => {
  function familyChooser(context, state, refresh) {
    const field = document.createElement("div");
    field.className = "test-object-field test-factor-family-field";
    const label = document.createElement("b"); label.textContent = context.t("因子家族");
    const button = context.button(
      FTTestFactorCatalog.familyButtonLabel(context, state),
      () => FTFactorFamilyPicker.open(context, {
        items: FTTestFactorCatalog.familyEntries(state),
        selectedKey: state.factorCatalog.selectedFamilyEntry?.key || "",
        onSelect: entry => FTTestFactorCatalog.selectFamily(context, state, entry, refresh),
      }),
    );
    button.classList.add("test-factor-family-button");
    field.append(label, button);
    return field;
  }

  function familyContent(context, state, refresh, sourceInput) {
    const entry = state.factorCatalog.selectedFamilyEntry;
    if (!entry) return FTUI.empty(
      context.t("尚未选择因子家族"), context.t("搜索公共因子库或本地 Git 修订"),
    );
    if (entry.sourceKind === "public") {
      return registeredFactorPanel(context, state, entry, refresh);
    }
    const family = FTTestFactorSelection.selectedFamily(state);
    return family
      ? parameterEditor(context, state, family, refresh, sourceInput)
      : document.createElement("div");
  }

  function registeredFactorPanel(context, state, family, refresh) {
    const root = document.createElement("div");
    root.className = "test-registered-factor-list";
    const title = document.createElement("b");
    title.textContent = context.t("公共因子家族中的已登记因子"); root.append(title);
    const factors = FTFactorFamilyPicker.familyFactors(family, state.factors);
    if (!factors.length) {
      root.append(FTUI.empty(context.t("该家族暂无可用因子"), "")); return root;
    }
    for (const factor of factors) {
      const row = document.createElement("div");
      const copy = document.createElement("span");
      const name = document.createElement("b");
      name.textContent = FTTestFactorSelection.factorAlias(factor);
      const note = document.createElement("small");
      note.textContent = factor.chinese_name || factor.description || factor.owner_alias || "";
      copy.append(name, note);
      const exists = FTTestFactorSelection.candidates(state).some(item => (
        FTTestFactorSelection.factorID(item) === FTTestFactorSelection.factorID(factor)
      ));
      const add = context.button(context.t(exists ? "已加入" : "加入候选"), () => {
        FTTestFactorSelection.addCandidate(state, factor); refresh();
      });
      add.disabled = exists; row.append(copy, add); root.append(row);
    }
    return root;
  }

  function parameterEditor(context, state, family, refresh, sourceInput) {
    const root = document.createElement("div");
    root.className = "test-factor-parameters";
    for (const parameter of family.params || []) {
      const field = document.createElement("label");
      const title = document.createElement("b");
      title.textContent = parameter.alias || parameter.name;
      const help = document.createElement("small");
      help.textContent = parameter.desc || parameter.value_space_desc || parameter.type || "";
      const control = parameterControl(parameter, state.values.factor_params || {});
      field.append(title, control, help); root.append(field);
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
      });
    });
    add.disabled = state.factorCatalog.selectedFamilyEntry?.sourceKind !== "transient"
      && !(state.values.factor_owner_ref && state.values.factor_git_commit);
    root.append(add); return root;
  }

  function parameterControl(parameter, values) {
    const options = Array.isArray(parameter.options) ? parameter.options : [];
    const control = options.length && parameter.input_mode === "enum"
      ? document.createElement("select") : document.createElement("input");
    if (control.tagName === "SELECT") {
      for (const option of options) {
        const item = document.createElement("option");
        item.value = String(option.value ?? ""); item.textContent = option.label || item.value;
        control.append(item);
      }
    } else control.type = "text";
    control.value = values[parameter.alias] ?? parameter.default_value ?? "";
    values[parameter.alias] = control.value;
    control.addEventListener("input", () => { values[parameter.alias] = control.value; });
    control.addEventListener("change", () => { values[parameter.alias] = control.value; });
    return control;
  }

  function selectField(label, options, value, updateValue) {
    const field = document.createElement("label"); field.className = "test-object-field";
    const text = document.createElement("b"); text.textContent = label;
    const select = document.createElement("select");
    const empty = document.createElement("option");
    empty.value = ""; empty.textContent = `— ${label} —`; select.append(empty);
    for (const option of options) {
      const item = document.createElement("option");
      item.value = option.value; item.textContent = option.label; select.append(item);
    }
    select.value = value || ""; select.addEventListener("change", () => updateValue(select.value));
    field.append(text, select); return field;
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
