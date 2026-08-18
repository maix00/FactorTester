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
    const derived = editor.mode === "derived" || editor.mode === "clone" || current?.parentId;
    const defaults = current || parent || {};
    const name = input("text", current?.name || editor.name || (editor.mode === "clone"
      ? `${model().groupLabel(parent)} ${context.t("副本")}` : ""));
    name.placeholder = context.t("组名称");
    form.append(field(context.t("名称"), name));

    let productGroupRef = "";
    let factorRefs = [];
    let splitCount;
    let groupIndex;
    let allGroups;
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
      : (productScope.items?.length ? productScope.items : state.groups || []);
    const factorItems = factorScopeBlocked ? []
      : (factorScope.items?.length ? factorScope.items : state.factors || []);
    const productGroup = groupPicker(context, state, productGroupRef, value => {
      productGroupRef = value[0] || "";
    }, productItems, !productScopeBlocked);
    const selectedFactors = factorScopeBlocked ? []
      : factorScope.ready && factorScope.source === "outer"
      ? factorScope.items.map(item => FTStrategyEditorScope.itemLabel("factor", item)).filter(Boolean)
      : (editor.mode === "base"
        ? selectedFactorAliases(state, defaults)
        : [defaults.factorAlias || selectedFactorAlias(state)].filter(Boolean));
    factorRefs = selectedFactors;
    const factor = factorPicker(
      context, state, factorRefs, editor.mode === "base", values => {
        factorRefs = values;
      }, factorItems, !factorScopeBlocked,
    );
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

    const mask = document.createElement("textarea");
    mask.rows = 3;
    mask.placeholder = context.t("每行一个产品代码；留空继承父组或产品组");
    const requestedMask = Array.isArray(editor.productMask)
      ? Object.fromEntries(editor.productMask.map(item => [item, true])) : null;
    mask.value = Object.entries(requestedMask || current?.productMask || defaults.productMask || {})
      .filter(([, enabled]) => enabled).map(([key]) => key).join("\n");
    structure.append(field(context.t("品种筛选"), mask));

    const initialOverrides = model().registeredOverrides(
      current || (editor.mode === "clone" ? parent : {}), state.manifest,
    );
    const overrideEditor = window.FTStrategyEditorOverrides?.create?.({
      context, manifest: state.manifest, inheritedValues: state.values,
      state, initial: initialOverrides,
      mountedTabs: current?.override_mounted_tabs || [],
    });
    const scopeNote = document.createElement("small");
    scopeNote.className = "backtest-group-scope-note";
    const scopeErrors = window.FTStrategyEditorScope?.validate(state) || [];
    scopeNote.textContent = scopeErrors.length
      ? scopeErrors.map(item => context.t(item.message)).join("；")
      : context.t("因子和产品组候选范围按外层设置或当前可见目录确定");
    if (scopeErrors.length) scopeNote.classList.add("error");

    const fallbackOverrides = FTBacktestGroupOverrides.render({
      context, manifest: state.manifest, inheritedValues: state.values,
      overrides: initialOverrides,
    });
    const editorTabs = window.FTStrategyEditorTabs?.create ? FTStrategyEditorTabs.create({
      context, state,
      mountedTabs: current?.override_mounted_tabs || [],
      onMountedTabsChange: tabs => overrideEditor?.setMountedTabs(tabs),
      renderStructure: () => structure,
      renderFactor: () => field(
        context.t(editor.mode === "base" ? "因子（可多选）" : "因子"), factor,
      ),
      renderProduct: () => field(context.t("产品组"), productGroup),
      renderOverrides: ({tab}) => overrideEditor?.panel(tab) || fallbackOverrides,
    }) : null;
    if (editorTabs) form.append(scopeNote, editorTabs);
    else form.append(scopeNote, field(context.t("产品组"), productGroup), field(
      context.t(editor.mode === "base" ? "因子（可多选）" : "因子"), factor,
    ), structure, field(context.t("覆盖字段"), fallbackOverrides));

    appendActions(context, form, async () => {
      try {
        const errors = window.FTStrategyEditorScope?.validate(state) || [];
        if (errors.length) throw new Error(errors.map(item => context.t(item.message)).join("；"));
        const parsedOverrides = overrideEditor?.value?.() || fallbackOverrides.value();
        const productMask = mask.value.split(/[\n,]+/).map(value => value.trim()).filter(Boolean);
        if (editor.mode === "base") {
          const group = productItems.find(item => productGroupID(item) === productGroupRef)
            || state.groups.find(item => productGroupID(item) === productGroupRef);
          model().addBaseBatch(state, {
            name: name.value.trim(), product_path_selection: group,
            factorAliases: factorRefs, splitCount: splitCount.value,
            groupIndex: groupIndex.value, allGroups: allGroups.checked,
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
          const group = productItems.find(item => productGroupID(item) === productGroupRef)
            || state.groups.find(item => productGroupID(item) === productGroupRef);
          Object.assign(patch, {
            product_path_selection: productProjection(group || productGroupRef),
            product_path_selection_id: productGroupRef,
            factorAlias: factorRefs[0] || "",
            factorAliases: factorRefs,
            splitCount: splitCount.value,
            groupIndex: groupIndex.value,
            override_mounted_tabs: editorTabs?.value?.().mountedTabs,
          });
          model().updateGroup(state, current.id, patch);
        } else {
          const selectedGroup = productItems.find(item => productGroupID(item) === productGroupRef);
          const productPatch = productGroupRef ? {
            product_path_selection: productProjection(selectedGroup || productGroupRef),
            product_path_selection_id: productGroupRef,
          } : {};
          model().addDerived(state, parent.id, {
            name: name.value.trim(), productMask, overrides: parsedOverrides,
            ...productPatch,
            factorAlias: factorRefs[0] || "",
            factorAliases: factorRefs,
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
    structure.append(grid);
    const initialOverrides = model().registeredOverrides(current, state.manifest);
    const overrideEditor = window.FTStrategyEditorOverrides?.create?.({
      context, manifest: state.manifest, inheritedValues: state.values,
      state, initial: initialOverrides,
      mountedTabs: current?.override_mounted_tabs || [],
    });
    const fallbackOverrides = FTBacktestGroupOverrides.render({
      context, manifest: state.manifest, inheritedValues: state.values,
      overrides: initialOverrides,
    });
    const editorTabs = window.FTStrategyEditorTabs?.create ? FTStrategyEditorTabs.create({
      context, state,
      mountedTabs: current?.override_mounted_tabs || [],
      onMountedTabsChange: tabs => overrideEditor?.setMountedTabs(tabs),
      renderStructure: () => structure,
      renderFactor: () => scopeSummary(context, state, "factor"),
      renderProduct: () => scopeSummary(context, state, "product_path_selection"),
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
            override_mounted_tabs: editorTabs?.value?.().mountedTabs,
          });
        } else {
          model().addLongShort(
            state, longGroupRef, shortGroupRef, name.value, {
              ...parsedOverrides,
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

  function groupPicker(...args) { return pickerTools().groupPicker(...args); }
  function strategyGroupPicker(...args) { return pickerTools().strategyGroupPicker(...args); }
  function factorPicker(...args) { return pickerTools().factorPicker(...args); }
  function selectedFactorAliases(...args) {
    return pickerTools().selectedFactorAliases(...args);
  }
  function selectedFactorAlias(...args) { return pickerTools().selectedFactorAlias(...args); }
  function factorAlias(...args) { return pickerTools().factorAlias(...args); }
  function productGroupID(...args) { return pickerTools().productGroupID(...args); }
  function productGroupLabel(...args) { return pickerTools().productGroupLabel(...args); }
  function productProjection(...args) { return pickerTools().productProjection(...args); }
  function scopeSummary(context, state, kind) {
    return window.FTStrategyEditorScope.summary(context, state, kind);
  }

  function titleFor(context, mode) {
    return context.t({
      base: "新增分组", derived: "派生组", clone: "复制为派生组",
      edit: "编辑分组", rename: "重命名策略", ls: "Long-Short 组合",
    }[mode] || "分组");
  }

  window.FTBacktestGroupForm = Object.freeze({render});
})();
