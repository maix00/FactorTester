(() => {
  const model = () => window.FTBacktestGroupModel;

  function strategyGroupPicker(context, state, groups, selected, onChange) {
    return FTTestObjectPicker.create(context, {
      title: context.t("分组"),
      items: groups.map(item => ({
        value: item.id, label: model().groupLabel(item),
        description: item.parentId ? context.t("派生组") : context.t("基础组"),
      })).filter(item => item.value),
      selected: selected ? [selected] : [], multi: false,
      name: `backtest-strategy-group-${Date.now()}`, onChange,
    });
  }

  function factorPicker(
    context, state, selected, multi, onChange, availableItems = state.factors || [],
    canCreate = true,
  ) {
    let picker;
    const saveFactor = value => {
      if (!value) return;
      const alias = factorAlias(value);
      const index = (state.factors || []).findIndex(item => factorAlias(item) === alias);
      const next = index >= 0 ? {...state.factors[index], ...value} : value;
      if (index >= 0) state.factors[index] = next; else state.factors.push(next);
      if (!availableItems.some(item => factorAlias(item) === alias)) availableItems.push(next);
      picker?.setItems(availableItems.map(item => {
        const itemAlias = factorAlias(item);
        return {
          value: itemAlias, label: itemAlias,
          description: item.description || item.desc || item.family || itemAlias,
        };
      }).filter(item => item.value));
      const nextValues = multi
        ? [...new Set([...(picker?.values || []), alias])]
        : [alias];
      picker?.setValues(nextValues);
      onChange?.(nextValues);
    };
    picker = FTTestObjectPicker.create(context, {
      title: context.t("因子"),
      // The surrounding shared field row supplies the label.  Keeping the
      // picker compact prevents a second title row inside the value column
      // and places the create action beside the dropdown like the outer
      // factor-source renderer.
      compact: true,
      items: availableItems.map(item => {
        const alias = factorAlias(item);
        return {
          value: alias, label: alias,
          description: item.description || item.desc || item.family || alias,
        };
      }).filter(item => item.value),
      selected, multi, name: `backtest-factors-${multi ? "multi" : "single"}`,
      onCreate: context.session && canCreate ? () => void (
        window.FTStrategyEditorFactorOverlay?.open
          ? FTStrategyEditorFactorOverlay.open(context, state, saveFactor)
          : FTTestObjectEditorOverlay.open(context, {
            kind: "factor", mode: "create", ref: "new", onSaved: saveFactor,
            testState: state, temporary: true,
          })
      ) : null,
      createLabel: context.t("新建因子"), onChange,
      itemActions: item => {
        const factor = (state.factors || []).find(value => factorAlias(value) === item.value);
        const ref = factor?.factor_alias || factor?.alias || factor?.id || item.value;
        if (!context.session || !factor?.can_edit || factor.is_public) return [];
        return [editAction(context, "factor", ref, saveFactor, state, factor)];
      },
    });
    return picker;
  }

  function editAction(context, kind, ref, onSaved, testState = null, initialValue = null) {
    return {
      label: context.t("编辑"), title: context.t("在当前浮层编辑"),
      buttonClass: "secondary",
      onClick: event => {
        event?.preventDefault();
        void FTTestObjectEditorOverlay.open(context, {
          kind, mode: "edit", ref, onSaved, testState, initialValue,
          temporary: initialValue?.temporary === true,
        });
      },
    };
  }

  function selectedFactorAliases(state, defaults) {
    const values = defaults.factorAliases || defaults.factor_aliases;
    if (Array.isArray(values) && values.length) return values.map(String).filter(Boolean);
    return [defaults.factorAlias || selectedFactorAlias(state)].filter(Boolean);
  }

  function selectedFactorAlias(state) {
    return factorAlias(FTTestFactors.selectedFactor(state));
  }

  function factorAlias(value) {
    if (typeof value === "string") return value;
    return value?.factor_alias || value?.alias || value?.name || "";
  }

  function productGroupID(value) {
    return typeof value === "string" ? value : FTTestProducts.groupID(value);
  }

  function productGroupLabel(value) {
    return typeof value === "string" ? value : FTTestProducts.groupLabel(value);
  }

  function productProjection(value) {
    if (typeof value === "string") {
      return {
        product_path_selection_id: value,
        product_group_template_id: value,
        label: value,
        selected_paths: [], paths: [],
      };
    }
    return FTTestProducts.projection(value);
  }

  window.FTStrategyEditorPickers = Object.freeze({
    factorAlias, factorPicker, productGroupID, productGroupLabel,
    productProjection, selectedFactorAlias, selectedFactorAliases, strategyGroupPicker,
  });
})();
