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

  function editAction(context, kind, ref, onSaved, testState = null, initialValue = null) {
    return {
      label: context.t("编辑"), title: context.t("在当前浮层编辑"),
      buttonClass: "secondary",
      onClick: event => {
        event?.preventDefault();
        void FTTestLazyCode.openObjectEditor(context, {
          kind, mode: "edit", ref, onSaved, testState, initialValue,
          temporary: initialValue?.temporary === true,
        });
      },
    };
  }

  function selectedFactorRefs(state, defaults) {
    const values = defaults.factor_candidate_refs;
    if (Array.isArray(values) && values.length) return values.map(String).filter(Boolean);
    return [factorRef(FTTestFactors.selectedFactor(state))].filter(Boolean);
  }

  function selectedFactorAlias(state) {
    return factorAlias(FTTestFactors.selectedFactor(state));
  }

  function factorAlias(value) {
    if (typeof value === "string") return value;
    return value?.alias || "";
  }

  function factorRef(value) {
    if (typeof value === "string") return value;
    return value?.ref || "";
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
    factorAlias, factorRef, productGroupID, productGroupLabel,
    productProjection, selectedFactorAlias, selectedFactorRefs, strategyGroupPicker,
  });
})();
