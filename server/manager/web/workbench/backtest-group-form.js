(() => {
  const model = () => window.FTBacktestGroupModel;

  function render(context, state, editor, onFinish) {
    const form = document.createElement("form");
    form.className = "backtest-group-form";
    const title = document.createElement("h3");
    title.textContent = titleFor(context, editor.mode);
    form.append(title);
    if (editor.mode === "rename") {
      renderRename(context, state, editor, form, onFinish);
    } else if (editor.mode === "ls") {
      renderLongShort(context, state, editor, form, onFinish);
    } else {
      renderGroup(context, state, editor, form, onFinish);
    }
    return form;
  }

  function renderRename(context, state, editor, form, onFinish) {
    const current = editor.strategyKind === "long_short"
      ? state.analysis.ls_configs.find(item => item.id === editor.strategyID)
      : model().find(state, editor.strategyID);
    const name = input("text", current?.name || "");
    name.placeholder = context.t("策略名称");
    name.required = true;
    form.append(field(context.t("名称"), name));
    appendActions(context, form, () => {
      try {
        if (editor.strategyKind === "long_short") {
          model().renameLongShort(state, editor.strategyID, name.value);
        } else {
          model().renameGroup(state, editor.strategyID, name.value);
        }
        onFinish();
      } catch (error) { showError(form, error.message); }
    }, onFinish);
  }

  function renderGroup(context, state, editor, form, onFinish) {
    const current = editor.groupID ? model().find(state, editor.groupID) : null;
    const parent = editor.parentID ? model().find(state, editor.parentID) : null;
    const derived = editor.mode === "derived" || current?.parentId;
    const defaults = current || parent || {};
    const name = input("text", current?.name || editor.name || "");
    name.placeholder = context.t("组名称");
    form.append(field(context.t("名称"), name));

    let productGroupRef = "";
    let factorRefs = [];
    let splitCount;
    let groupIndex;
    let allGroups;
    let productMask = productMaskValues(
      editor.productMask !== undefined ? editor.productMask : defaults.productMask,
    );
    const productScope = window.FTStrategyEditorScope?.scope(
      state, "product_path_selection",
    ) || {items: state.groups || [], ready: true, required: false};
    const factorScope = window.FTStrategyEditorScope?.scope(state, "factor")
      || {items: state.factors || [], ready: true, required: false};
    const productScopeBlocked = productScope.required && !productScope.ready;
    const factorScopeBlocked = factorScope.required && !factorScope.ready;
    productGroupRef = defaults.product_path_selection_id
      || productGroupID(defaults.product_path_selection)
      || (!productScopeBlocked && productScope.ready && productScope.source === "outer"
        ? FTStrategyEditorScope.itemID("product_path_selection", productScope.items[0])
        : productScopeBlocked ? "" : state.groupRef || "");
    const productItems = productScopeBlocked ? []
      : (Array.isArray(productScope.items) ? productScope.items : state.groups || []);
    const factorItems = factorScopeBlocked ? []
      : (factorScope.items?.length ? factorScope.items : state.factors || []);
    const innerScopeValues = {...state.values};
    const innerFactorFields = state.manifest?.strategy_editor?.inner_factor_fields || {};
    const scopedCandidate = window.FTStrategyEditorScope?.scopedField?.(
      state, "factor_candidates", "inner",
    );
    const scopedCombination = window.FTStrategyEditorScope?.scopedField?.(
      state, "factor_combination_mode", "inner",
    );
    const candidateDescriptor = scopedCandidate
      || innerFactorFields.candidate_selection || {};
    const combinationDescriptor = scopedCombination
      || innerFactorFields.combination_mode || {};
    const combinationItems = choiceItems(combinationDescriptor);
    let factorCombinationMode = String(
      defaults.factor_combination_mode || defaults.factorCombinationMode || "",
    );
    const selectedCandidateValues = () => factorItems.filter(item => (
      factorRefs.includes(factorRef(item))
    ));
    innerScopeValues.factor_candidates = selectedCandidateValues();
    const renderProductPanel = () => FTTestProducts.selectionPanel(
      context, state, () => editorTabs?.refreshChips(), {
        groups: productItems,
        selectedRefs: productGroupRef ? [productGroupRef] : [],
        multi: false,
        canCreate: !productScopeBlocked && (
          window.FTStrategyEditorScope?.inlineCreateAllowed?.(
            state, "product_path_candidates", productScope,
          ) ?? productScope.source !== "outer"
        ),
        onChange: values => {
          productGroupRef = values[0] || "";
          innerScopeValues.product_path_selection = productGroupRef;
          editorTabs?.refreshChips();
        },
      },
    );
    const hasStoredFactors = Boolean(
      Array.isArray(defaults.factor_candidate_refs)
        && defaults.factor_candidate_refs.length,
    );
    const storedFactors = hasStoredFactors
      ? defaults.factor_candidate_refs.map(String).filter(Boolean) : [];
    const selectedFactors = factorScopeBlocked ? []
      : factorScope.source === "outer" && editor.mode === "base"
      && !hasStoredFactors
      ? factorScope.items.map(item => factorRef(item)).filter(Boolean)
      : storedFactors;
    factorRefs = selectedFactors;
    innerScopeValues.factor_candidates = selectedCandidateValues();
    const factorSourceState = !factorScopeBlocked && factorScope.source !== "outer"
      ? FTTestFactorCandidateSources.scopedSourceState(state, editor, {
          factor_candidate_refs: editor.draft?.factor_candidate_refs ?? selectedFactors,
          factor_candidates: editor.draft?.factor_candidates,
          factor_source_selections: editor.draft?.factor_source_selections
            ?? defaults.factor_source_selections,
          factor_set_selections: editor.draft?.factor_set_selections
            ?? defaults.factor_set_selections,
          factor_role_bindings: editor.draft?.factor_role_bindings
            ?? defaults.factor_role_bindings,
        })
      : null;
    let overrideEditor;
    let fallbackOverrides;
    let fallbackFactorOverrides;
    let factor;
    let combinationPicker;
    let factorPanel;
    const factorHost = document.createElement("div");
    factorHost.className = "backtest-group-factor-panel";
    const syncScopedFactorSources = () => {
      if (!factorSourceState) return null;
      const snapshot = FTTestFactorCandidateSources.scopedSourceSnapshot(factorSourceState);
      factorRefs = snapshot.factor_candidate_refs;
      innerScopeValues.factor_candidates = snapshot.factor_candidates;
      editor.draft = {...(editor.draft || {}), ...snapshot};
      return snapshot;
    };
    const factorSourceMetadata = () => {
      const snapshot = syncScopedFactorSources();
      FTTestFactorCandidateSources.retainScopedSources(state, factorSourceState);
      return snapshot ? {
        factor_source_selections: snapshot.factor_source_selections,
        factor_set_selections: snapshot.factor_set_selections,
      } : {};
    };
    const renderFactorPanel = () => {
      syncScopedFactorSources();
      const combinationVisible = window.FTStrategyEditorScope?.fieldVisible?.(
        state, "factor_combination_mode", "inner", innerScopeValues,
      ) ?? factorRefs.length > 1;
      const overrideContent = overrideEditor?.panel({key: "factor"})
        || fallbackFactorOverrides;
      const panelOptions = {
        candidateControl: factor,
        candidateLabel: candidateDescriptor.label || context.t("因子候选"),
        candidateHelp: candidateDescriptor.help_text || "",
        combinationVisible,
        combinationControl: combinationPicker,
        combinationLabel: combinationDescriptor.label || context.t("组合方式"),
        combinationHelp: combinationDescriptor.help_text
          || context.t("多个因子候选需要一种组合方式"),
        combinationEmpty: !combinationItems.length
          ? context.t("当前没有可用组合方式，暂不能提交多个因子候选") : "",
        overrideContent,
      };
      if (factorSourceState) {
        factorPanel = FTTestFactorCandidateSources.scopedSourcePanel(
          context, factorSourceState, () => {
            syncScopedFactorSources();
            factorPanel = null;
            renderFactorPanel();
            overrideEditor?.refresh();
            editorTabs?.refreshChips();
          }, panelOptions,
        );
        factorHost.replaceChildren(factorPanel);
        return;
      }
      if (!factorPanel) {
        factorPanel = window.FTTestFactorCandidateSources?.innerPanel?.(
          context, state, () => {}, panelOptions,
        ) || field(
          candidateDescriptor.label || context.t("因子候选"), factor,
          candidateDescriptor.help_text || "",
        );
        factorHost.replaceChildren(factorPanel);
      } else {
        factorPanel.update?.(panelOptions);
      }
    };
    factor = FTTestFactorCandidateSources.candidatePicker(context, state, {
      items: factorItems,
      selected: factorRefs,
      multi: candidateDescriptor.cardinality === "many",
      loading: FTTestObjectPicker.lazyLoading(state, "factors"),
      loadingText: context.t("正在读取因子候选…"),
      canCreate: !factorScopeBlocked
        && candidateDescriptor.allow_inline_create_when_outer_mounted === true,
      name: "backtest-factor-candidates",
      onChange: values => {
        factorRefs = values;
        innerScopeValues.factor_candidates = selectedCandidateValues();
        renderFactorPanel();
        overrideEditor?.refresh();
        editorTabs?.refreshChips();
      },
    });
    combinationPicker = FTTestChoicePicker.create(context, {
      className: "test-choice-picker test-factor-combination-picker",
      compact: true,
      name: "backtest-factor-combination-mode",
      multi: false,
      disabled: combinationItems.length === 0,
      items: combinationItems,
      selected: factorCombinationMode ? [factorCombinationMode] : [],
      onChange: values => { factorCombinationMode = values[0] || ""; },
    });
    splitCount = input("number", defaults.splitCount || state.values.split_count || 5);
    splitCount.min = "1"; splitCount.step = "1";
    groupIndex = input("number", defaults.groupIndex || state.values.group_index || 1);
    groupIndex.min = "1"; groupIndex.step = "1";

    const structure = document.createElement("div");
    structure.className = "backtest-group-form-rows";
    if (derived) {
      const parentLine = document.createElement("p");
      parentLine.className = "backtest-group-parent";
      parentLine.textContent = `${context.t("父组")}: ${model().groupLabel(parent || model().find(state, current?.parentId))}`;
      structure.append(parentLine);
    }
    structure.append(
      field(context.t("分组数"), splitCount), field(context.t("分组序号"), groupIndex),
    );
    if (editor.mode === "base") {
      allGroups = input("checkbox", false);
      allGroups.addEventListener("change", () => { groupIndex.disabled = allGroups.checked; });
      structure.append(field(context.t("一次建立全部分组"), allGroups));
    }

    const initialOverrides = model().registeredOverrides(
      current || {}, state.manifest,
    );
    overrideEditor = window.FTStrategyEditorOverrides?.create?.({
      context, manifest: state.manifest, inheritedValues: innerScopeValues,
      state, initial: initialOverrides,
      mountedTabs: current?.override_mounted_tabs || [],
      onChange: () => editorTabs?.refreshChips(),
    });
    const scopeNote = document.createElement("small");
    scopeNote.className = "backtest-group-scope-note";
    const scopeErrors = window.FTStrategyEditorScope?.validate(state) || [];
    scopeNote.textContent = scopeErrors.length
      ? scopeErrors.map(item => context.t(item.message)).join("；")
      : context.t("因子和产品组候选范围按外层设置或当前可见目录确定");
    if (scopeErrors.length) scopeNote.classList.add("error");

    fallbackOverrides = FTBacktestGroupOverrides.render({
      context, manifest: state.manifest, inheritedValues: innerScopeValues,
      overrides: initialOverrides, scopeSide: "inner",
    });
    fallbackFactorOverrides = FTBacktestGroupOverrides.render({
      context, manifest: state.manifest, inheritedValues: innerScopeValues,
      overrides: initialOverrides, onlyTabs: ["factor"], scopeSide: "inner",
      contentOnly: true,
    });
    let editorTabs = window.FTStrategyEditorTabs?.create ? FTStrategyEditorTabs.create({
      context, state,
      activeKey: editor.activeTabKey || "",
      onActivate: key => { editor.activeTabKey = key || ""; },
      mountedTabs: current?.override_mounted_tabs || [],
      onMountedTabsChange: tabs => overrideEditor?.setMountedTabs(tabs),
      chipValues: () => ({
        ...innerScopeValues,
        ...(overrideEditor?.value?.() || {}),
      }),
      chipSources: () => window.FTTestContentAdapters?.chipSources?.(
        factorSourceState || state, {
        factor_candidate_refs: factorRefs,
        product_path_selection_id: productGroupRef,
        splitCount: Number(splitCount?.value || 0),
        groupIndex: Number(groupIndex?.value || 0),
        productMask,
        },
      ) || {},
      renderStructure: () => structure,
      renderFactor: () => { renderFactorPanel(); return factorHost; },
      renderProduct: renderProductPanel,
      renderProductFilter: () => window.FTStrategyEditorProductFilter?.render(
        context, state, productMask,
        values => { productMask = [...new Set((values || []).map(String).filter(Boolean))]; },
      ) || document.createElement("div"),
      renderOverrides: ({tab}) => overrideEditor?.panel(tab) || fallbackOverrides,
    }) : null;
    renderFactorPanel();
    // The tab surface is created before the lazy factor panel paints.  Refresh
    // once after that first paint so inherited/default chips are visible on
    // the initial render instead of only after the user changes a field.
    editorTabs?.refreshChips();
    if (editorTabs) form.append(scopeNote, editorTabs);
    else form.append(scopeNote, renderProductPanel(),
      factorHost, structure, field(context.t("覆盖字段"), fallbackOverrides));

    appendActions(context, form, async () => {
      try {
        const errors = window.FTStrategyEditorScope?.validate(state) || [];
        if (errors.length) throw new Error(errors.map(item => context.t(item.message)).join("；"));
        const requiresCombination = window.FTStrategyEditorScope?.fieldRequired?.(
          state, "factor_combination_mode", "inner", innerScopeValues,
        ) ?? factorRefs.length > 1;
        if (requiresCombination) {
          if (!combinationItems.length) {
            throw new Error(context.t("当前没有可用组合方式，不能提交多个因子候选"));
          }
          if (!factorCombinationMode) {
            throw new Error(context.t("请选择组合方式"));
          }
        } else {
          factorCombinationMode = "";
        }
        const parsedOverrides = overrideEditor?.value?.() || fallbackOverrides.value();
        if (editor.mode === "base") {
          const group = productItems.find(item => productGroupID(item) === productGroupRef);
          if (!group) throw new Error(context.t("所选产品组不受当前数据源完整支持"));
          model().addBaseBatch(state, {
            name: name.value.trim(), product_path_selection: group,
            factor_candidate_refs: factorRefs, splitCount: splitCount.value,
            ...factorSourceMetadata(),
            factor_combination_mode: factorCombinationMode,
            groupIndex: groupIndex.value, allGroups: allGroups.checked,
            productMask,
            overrides: parsedOverrides,
            override_mounted_tabs: editorTabs?.value?.().mountedTabs,
          });
        } else if (editor.mode === "edit") {
          const previousOverrides = model().registeredOverrides(current, state.manifest);
          const cleared = Object.fromEntries(Object.keys(previousOverrides).map(key => [key, undefined]));
          const patch = {
            ...cleared, ...parsedOverrides, name: name.value.trim() || current.name,
            productMask,
          };
          const group = productItems.find(item => productGroupID(item) === productGroupRef);
          if (!group) throw new Error(context.t("所选产品组不受当前数据源完整支持"));
          Object.assign(patch, {
            product_path_selection: productProjection(group || productGroupRef),
            product_path_selection_id: productGroupRef,
            factor_candidate_refs: factorRefs,
            ...factorSourceMetadata(),
            factor_combination_mode: factorCombinationMode,
            splitCount: splitCount.value,
            groupIndex: groupIndex.value,
            override_mounted_tabs: editorTabs?.value?.().mountedTabs,
          });
          model().updateGroup(state, current.id, patch);
        } else {
          const selectedGroup = productItems.find(item => productGroupID(item) === productGroupRef);
          if (productGroupRef && !selectedGroup) {
            throw new Error(context.t("所选产品组不受当前数据源完整支持"));
          }
          const productPatch = productGroupRef ? {
            product_path_selection: productProjection(selectedGroup || productGroupRef),
            product_path_selection_id: productGroupRef,
          } : {};
          model().addDerived(state, parent.id, {
            name: name.value.trim(), productMask, overrides: parsedOverrides,
            ...productPatch,
            factor_candidate_refs: factorRefs,
            ...factorSourceMetadata(),
            factor_combination_mode: factorCombinationMode,
            splitCount: splitCount.value,
            groupIndex: groupIndex.value,
            override_mounted_tabs: editorTabs?.value?.().mountedTabs,
          });
        }
        onFinish();
      } catch (error) { showError(form, error.message); }
    }, onFinish);
  }

  function renderLongShort(context, state, editor, form, onFinish) {
    const current = editor.strategyID
      ? state.analysis.ls_configs.find(item => item.id === editor.strategyID) : null;
    const groups = model().rootsAndChildren(state).map(item => item.group);
    let longGroupRef = editor.groupIDs?.[0] || current?.longGroupId || "";
    let shortGroupRef = editor.groupIDs?.[1] || current?.shortGroupId || "";
    const longGroup = strategyGroupPicker(context, state, groups, longGroupRef, values => {
      longGroupRef = values[0] || "";
    });
    const shortGroup = strategyGroupPicker(context, state, groups, shortGroupRef, values => {
      shortGroupRef = values[0] || "";
    });
    const name = input("text", "");
    name.value = current?.name || editor.name || "";
    name.placeholder = context.t("组合名称（留空自动生成）");
    const grid = document.createElement("div");
    grid.className = "backtest-group-form-rows";
    grid.append(
      field(context.t("多头组"), longGroup),
      field(context.t("空头组"), shortGroup),
      field(context.t("名称"), name),
    );
    const swap = context.button(context.t("交换多空"), () => {
      const value = longGroupRef; longGroupRef = shortGroupRef; shortGroupRef = value;
      longGroup.setValues([longGroupRef]); shortGroup.setValues([shortGroupRef]);
    });
    swap.type = "button";
    grid.append(swap);
    const structure = document.createElement("div");
    structure.className = "backtest-long-short-structure";
    let productMask = productMaskValues(current?.productMask);
    structure.append(grid);
    const initialOverrides = model().registeredOverrides(current, state.manifest);
    const overrideEditor = window.FTStrategyEditorOverrides?.create?.({
      context, manifest: state.manifest, inheritedValues: state.values,
      state, initial: initialOverrides,
      mountedTabs: current?.override_mounted_tabs || [],
    });
    const fallbackOverrides = FTBacktestGroupOverrides.render({
      context, manifest: state.manifest, inheritedValues: state.values,
      overrides: initialOverrides, scopeSide: "inner",
    });
    const editorTabs = window.FTStrategyEditorTabs?.create ? FTStrategyEditorTabs.create({
      context, state,
      mountedTabs: current?.override_mounted_tabs || [],
      onMountedTabsChange: tabs => overrideEditor?.setMountedTabs(tabs),
      renderStructure: () => structure,
      renderFactor: () => scopeSummary(context, state, "factor"),
      renderProduct: () => scopeSummary(context, state, "product_path_selection"),
      renderProductFilter: () => window.FTStrategyEditorProductFilter?.render(
        context, state, productMask,
        values => { productMask = [...new Set((values || []).map(String).filter(Boolean))]; },
      ) || document.createElement("div"),
      renderOverrides: ({tab}) => overrideEditor?.panel(tab) || fallbackOverrides,
    }) : null;
    if (editorTabs) form.append(editorTabs);
    else form.append(structure, field(context.t("覆盖字段"), fallbackOverrides));
    appendActions(context, form, () => {
      try {
        const scopeErrors = window.FTStrategyEditorScope?.validate(state) || [];
        if (scopeErrors.length) {
          throw new Error(scopeErrors.map(item => context.t(item.message)).join("；"));
        }
        const parsedOverrides = overrideEditor?.value?.() || fallbackOverrides.value();
        if (current) {
          const previous = model().registeredOverrides(current, state.manifest);
          const cleared = Object.fromEntries(Object.keys(previous).map(key => [key, undefined]));
          model().updateLongShort(state, current.id, {
            ...cleared, ...parsedOverrides,
            name: name.value.trim() || current.name,
            longGroupId: longGroupRef, shortGroupId: shortGroupRef,
            productMask,
            override_mounted_tabs: editorTabs?.value?.().mountedTabs,
          });
        } else {
          model().addLongShort(
            state, longGroupRef, shortGroupRef, name.value, {
              ...parsedOverrides,
              productMask,
              override_mounted_tabs: editorTabs?.value?.().mountedTabs,
            },
          );
        }
        onFinish();
      } catch (error) { showError(form, error.message); }
    }, onFinish);
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
    form.querySelector(".backtest-group-form-error").textContent = message;
  }

  function field(label, control, help = "") {
    // Shared object pickers expose their DOM control as `.element` while
    // retaining imperative helpers such as `setValues` on the wrapper. Keep
    // the wrapper for callers that need those helpers, but only mount the DOM
    // element in the field row. Without this normalization, opening an add or
    // edit form attempts to append the picker wrapper itself and the browser
    // aborts the render, which looks like the Add button did nothing.
    return FTTestFieldRow.create(label, control?.element || control, help);
  }

  function input(type, value) {
    const control = document.createElement("input");
    control.type = type;
    if (type === "checkbox") control.checked = Boolean(value); else control.value = value ?? "";
    return control;
  }

  function pickerTools() {
    if (!window.FTStrategyEditorPickers) {
      throw new Error("策略编辑器候选控件尚未加载");
    }
    return window.FTStrategyEditorPickers;
  }

  function strategyGroupPicker(...args) { return pickerTools().strategyGroupPicker(...args); }
  function selectedFactorRefs(...args) {
    return pickerTools().selectedFactorRefs(...args);
  }
  function selectedFactorAlias(...args) { return pickerTools().selectedFactorAlias(...args); }
  function factorAlias(...args) { return pickerTools().factorAlias(...args); }
  function factorRef(...args) { return pickerTools().factorRef(...args); }
  function choiceItems(descriptor) {
    const raw = Array.isArray(descriptor?.options) ? descriptor.options : [];
    return raw.map(item => Array.isArray(item)
      ? {value: String(item[0] ?? ""), label: String(item[1] ?? item[0] ?? "")}
      : {
        ...item,
        value: String(item?.value ?? ""),
        label: item?.label || String(item?.value ?? ""),
      }).filter(item => item.value);
  }
  function productGroupID(...args) { return pickerTools().productGroupID(...args); }
  function productGroupLabel(...args) { return pickerTools().productGroupLabel(...args); }
  function productProjection(...args) { return pickerTools().productProjection(...args); }
  function scopeSummary(context, state, kind) {
    return window.FTStrategyEditorScope.summary(context, state, kind);
  }

  function titleFor(context, mode) {
    return context.t({
      base: "新增分组", derived: "派生组",
      edit: "编辑分组", rename: "重命名策略", ls: "Long-Short 组合",
    }[mode] || "分组");
  }

  function productMaskValues(value) {
    if (typeof model().productMaskValues === "function") {
      return model().productMaskValues(value);
    }
    if (Array.isArray(value)) return [...new Set(value.map(String).filter(Boolean))];
    if (!value || typeof value !== "object") return [];
    return Object.entries(value)
      .filter(([, enabled]) => enabled)
      .map(([key]) => key);
  }

  window.FTBacktestGroupForm = Object.freeze({render});
})();
