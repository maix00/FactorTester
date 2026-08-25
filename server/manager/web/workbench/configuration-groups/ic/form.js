(() => {
  const model = () => window.FTICConfigurationGroupModel;

  function render(context, state, editor, onFinish) {
    const current = editor.groupID ? model().find(state, editor.groupID) : null;
    const form = document.createElement("form");
    form.className = "backtest-group-form ic-configuration-group-form";
    const title = document.createElement("h3");
    title.textContent = context.t(current ? "编辑配置组" : "新增配置组");
    form.append(title);

    // An IC configuration group owns its selected factor, but its available
    // range follows the same registered outer/inner scope contract as a
    // backtest strategy. Without an outer factor tab it sees the visible
    // catalog; with one it can only filter the outer candidate pool.
    const factorScope = window.FTStrategyEditorScope?.scope?.(state, "factor")
      || {
        items: Array.isArray(state.factors) ? state.factors : [],
        required: false, ready: true, source: "visible",
      };
    const factorScopeBlocked = factorScope.required && !factorScope.ready;
    const factorItems = factorScopeBlocked ? []
      : (Array.isArray(factorScope.items) ? factorScope.items : []);
    const productScope = window.FTStrategyEditorScope?.scope?.(
      state, "product_path_selection",
    ) || {
      items: Array.isArray(state.groups) ? state.groups : [],
      required: false, ready: true, source: "visible",
    };
    const productScopeBlocked = productScope.required && !productScope.ready;
    const productItems = productScopeBlocked ? []
      : (Array.isArray(productScope.items) ? productScope.items : []);
    const draft = editor.draft || (editor.draft = {});
    let factorRef = draft.factor_ref ?? current?.factor_ref ?? "";
    let productScopeRef = draft.product_scope_ref ?? current?.product_scope_ref ?? "";

    const name = input("text", current?.name || "");
    name.placeholder = context.t("配置组名称");
    let delayValue = current?.entry_delay_bars ?? firstDelay(state.values?.ic_lags);
    const delay = input("number", delayValue);
    delay.min = "0";
    delay.step = "1";
    const inheritedHorizon = window.FTICConfiguration?.normalizeHorizon
      ? FTICConfiguration.normalizeHorizon(state.values?.forward_return_horizons)
      : {sampling: "scale_aware"};
    let horizon = structuredClone(current?.horizon || inheritedHorizon);
    const horizonMode = document.createElement("select");
    for (const [value, label] of [["scale_aware", "按因子周期"], ["explicit", "显式网格"]]) {
      const option = document.createElement("option");
      option.value = value; option.textContent = context.t(label);
      horizonMode.append(option);
    }
    horizonMode.value = horizon.sampling || "scale_aware";
    const horizonBases = input("text", (horizon.bases || ["signal"]).join(", "));
    const horizonMultipliers = input("text", (horizon.multipliers || [1]).join(", "));
    const rank = input("checkbox", (current?.methods || inheritedMethods(state)).includes("rank"));
    const pearson = input(
      "checkbox", (current?.methods || inheritedMethods(state)).includes("pearson"),
    );
    const basis = document.createElement("select");
    const basisDefinition = state.manifest?.defaults?.return_price_basis || {};
    const basisOptions = basisDefinition.value_descriptor?.options || [];
    for (const optionValue of basisOptions) {
      const option = document.createElement("option");
      option.value = String(optionValue.value);
      option.textContent = context.t(optionValue.label || optionValue.value);
      basis.append(option);
    }
    basis.value = current?.return_price_basis || state.values?.return_price_basis
      || basisDefinition.value || "next_open_to_open_adjusted";
    const structure = document.createElement("div");
    structure.className = "backtest-group-form-rows ic-configuration-group-structure";
    structure.append(
      field(context.t("名称"), name),
      field(context.t("Horizon 模式"), horizonMode),
      field(context.t("Horizon 基准"), horizonBases),
      field(context.t("Horizon 倍数"), horizonMultipliers),
      field(context.t("Rank IC"), rank),
      field(context.t("Pearson IC"), pearson),
      field(context.t("收益率定义"), basis),
    );

    const factor = FTTestFactorCandidateSources.candidatePicker(context, state, {
      items: factorItems,
      selected: factorRef ? [factorRef] : [],
      multi: false,
      loading: !factorScopeBlocked && FTTestObjectPicker.lazyLoading(state, "factors"),
      loadingText: context.t("正在读取因子候选…"),
      canCreate: !factorScopeBlocked && inlineCreateAllowed(
        state, "factor_candidates", factorScope,
      ),
      name: "ic-configuration-group-factor",
      onChange: values => {
        factorRef = values[0] || "";
        draft.factor_ref = factorRef;
        editorTabs?.refreshChips();
      },
    });
    const renderFactor = () => FTTestFactorCandidateSources.innerPanel?.(
      context, state, () => {}, {
        candidateControl: factor,
        candidateLabel: context.t("因子"),
        candidateHelp: context.t("每个 IC 配置组只选择一个冻结因子"),
        combinationVisible: false,
      },
    ) || field(context.t("因子"), factor);
    const renderProduct = () => FTTestProducts.selectionPanel(
      context, state, () => editorTabs?.refreshChips(), {
        groups: productItems,
        constrain: false,
        loading: !productScopeBlocked && FTTestObjectPicker.lazyLoading(state, "products"),
        selectedRefs: productScopeRef ? [productScopeRef] : [],
        multi: false,
        canCreate: !productScopeBlocked && inlineCreateAllowed(
          state, "product_path_candidates", productScope,
        ),
        onChange: values => {
          productScopeRef = values[0] || "";
          draft.product_scope_ref = productScopeRef;
          editorTabs?.refreshChips();
        },
      },
    );
    let editorTabs = window.FTStrategyEditorTabs?.create ? FTStrategyEditorTabs.create({
      context, state,
      activeKey: editor.activeTabKey || "",
      onActivate: key => { editor.activeTabKey = key || ""; },
      mountedTabs: current?.editor_mounted_tabs || [],
      chipValues: () => ({
        ...state.values,
        ic_lags: [delayValue],
        factor_candidates: factorItems.filter(item => factorIdentity(item) === factorRef),
        product_path_selection: productScopeRef,
      }),
      chipSources: () => window.FTTestContentAdapters?.chipSources?.(state, {
        factor_candidate_refs: factorRef ? [factorRef] : [],
        product_path_selection_id: productScopeRef,
      }) || {},
      renderStructure: () => structure,
      renderFactor,
      renderProduct,
      renderOverrides: ({tab}) => {
        if (tab.field !== "ic_lags") return document.createElement("div");
        delay.value = delayValue;
        delay.onchange = () => { delayValue = Number(delay.value); };
        return field(context.t(tab.label || "Delay"), delay,
          context.t("每个配置组只允许一个非负 Delay"));
      },
    }) : null;
    form.append(editorTabs || structure);
    appendActions(context, form, () => {
      try {
        if (!factorItems.some(item => factorIdentity(item) === factorRef)) {
          throw new Error(context.t("请选择一个当前范围内的因子"));
        }
        if (!productItems.some(item => productIdentity(item) === productScopeRef)) {
          throw new Error(context.t("请选择一个当前范围内的产品组"));
        }
        horizon = horizonMode.value === "scale_aware"
          ? {sampling: "scale_aware"}
          : {
            sampling: "explicit",
            bases: tokens(horizonBases.value),
            multipliers: tokens(horizonMultipliers.value).map(Number),
          };
        const methods = [rank.checked ? "rank" : "", pearson.checked ? "pearson" : ""]
          .filter(Boolean);
        const value = {
          name: name.value.trim(), factor_ref: factorRef,
          product_scope_ref: productScopeRef,
          entry_delay_bars: Number(delayValue), horizon, methods,
          return_price_basis: basis.value.trim(),
          editor_mounted_tabs: editorTabs?.value?.().mountedTabs,
        };
        if (current) model().update(state, current.config_group_id, value);
        else model().add(state, value);
        onFinish();
      } catch (error) { showError(form, error.message); }
    }, onFinish);
    return form;
  }

  function inheritedMethods(state) {
    const value = String(state.values?.ic_correlation || "rank");
    return value === "both" ? ["rank", "pearson"]
      : [value === "pearson" ? "pearson" : "rank"];
  }

  function inlineCreateAllowed(state, fieldKey, scope) {
    if (window.FTStrategyEditorScope?.inlineCreateAllowed) {
      return FTStrategyEditorScope.inlineCreateAllowed(state, fieldKey, scope);
    }
    const descriptor = window.FTStrategyEditorScope?.scopedField?.(
      state, fieldKey, "inner",
    ) || {};
    return scope.source === "outer"
      ? descriptor.allow_inline_create_when_outer_mounted === true
      : descriptor.allow_inline_create_when_outer_unmounted !== false;
  }

  function firstDelay(value) {
    const values = Array.isArray(value) ? value : [value ?? 0];
    const delay = Number(values[0]);
    return Number.isInteger(delay) && delay >= 0 ? delay : 0;
  }

  function factorIdentity(value) {
    return String(value?.ref || "");
  }

  function productIdentity(value) {
    return String(window.FTTestProducts?.groupID?.(value)
      || value?.group_ref || value?.product_group_ref || value?.id || "");
  }

  function tokens(value) {
    return String(value || "").split(/[\s,，;；]+/).map(item => item.trim()).filter(Boolean);
  }

  function appendActions(context, form, saveAction, cancelAction) {
    const status = document.createElement("span");
    status.className = "backtest-group-form-error";
    const actions = document.createElement("div");
    actions.className = "backtest-group-form-actions";
    const save = context.button(context.t("保存"), saveAction);
    save.type = "button";
    const cancel = context.button(context.t("取消"), cancelAction);
    cancel.type = "button";
    actions.append(cancel, save);
    form.append(status, actions);
  }

  function showError(form, message) {
    const status = form.querySelector?.(".backtest-group-form-error");
    if (status) status.textContent = message;
  }

  function field(label, control, help = "") {
    return FTTestFieldRow.create(label, control?.element || control, help);
  }

  function input(type, value) {
    const control = document.createElement("input");
    control.type = type;
    if (type === "checkbox") control.checked = Boolean(value);
    else control.value = value ?? "";
    return control;
  }

  window.FTICConfigurationGroupForm = Object.freeze({render});
})();
