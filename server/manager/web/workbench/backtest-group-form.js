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

    let productGroup;
    let productGroupRef = "";
    let factor;
    let factorRefs = [];
    let splitCount;
    let groupIndex;
    let allGroups;
    if (!derived) {
      productGroupRef = defaults.product_path_selection_id
        || FTTestProducts.groupID(defaults.product_path_selection)
        || state.groupRef || "";
      productGroup = groupPicker(context, state, productGroupRef, value => {
        productGroupRef = value[0] || "";
      });
      const selectedFactors = editor.mode === "base"
        ? selectedFactorAliases(state, defaults)
        : [defaults.factorAlias || selectedFactorAlias(state)].filter(Boolean);
      factorRefs = selectedFactors;
      factor = factorPicker(context, state, factorRefs, editor.mode === "base", values => {
        factorRefs = values;
      });
      splitCount = input("number", defaults.splitCount || state.values.split_count || 5);
      splitCount.min = "1"; splitCount.step = "1";
      groupIndex = input("number", defaults.groupIndex || state.values.group_index || 1);
      groupIndex.min = "1"; groupIndex.step = "1";
      const structure = document.createElement("div");
      structure.className = "backtest-group-form-rows";
      structure.append(
        field(context.t("产品组"), productGroup), field(
          context.t(editor.mode === "base" ? "因子（可多选）" : "因子"), factor,
        ),
        field(context.t("分组数"), splitCount), field(context.t("分组序号"), groupIndex),
      );
      form.append(structure);
      if (editor.mode === "base") {
        allGroups = input("checkbox", false);
        allGroups.addEventListener("change", () => { groupIndex.disabled = allGroups.checked; });
        form.append(field(context.t("一次建立全部分组"), allGroups));
      }
    } else {
      const parentLine = document.createElement("p");
      parentLine.className = "backtest-group-parent";
      parentLine.textContent = `${context.t("父组")}: ${model().groupLabel(parent || model().find(state, current?.parentId))}`;
      form.append(parentLine);
    }

    const mask = document.createElement("textarea");
    mask.rows = 3;
    mask.placeholder = context.t("每行一个产品代码；留空继承父组或产品组");
    const requestedMask = Array.isArray(editor.productMask)
      ? Object.fromEntries(editor.productMask.map(item => [item, true])) : null;
    mask.value = Object.entries(requestedMask || current?.productMask || defaults.productMask || {})
      .filter(([, enabled]) => enabled).map(([key]) => key).join("\n");
    form.append(field(context.t("品种筛选"), mask));

    const overrides = FTBacktestGroupOverrides.render({
      context, manifest: state.manifest, inheritedValues: state.values,
      overrides: model().registeredOverrides(
        current || (editor.mode === "clone" ? parent : {}), state.manifest,
      ),
    });
    const overrideDetails = document.createElement("details");
    const overrideSummary = document.createElement("summary");
    overrideSummary.textContent = context.t("逐组设置覆盖");
    overrideDetails.append(overrideSummary, field(context.t("覆盖字段"), overrides));
    form.append(overrideDetails);

    appendActions(context, form, async () => {
      try {
        const parsedOverrides = overrides.value();
        const productMask = mask.value.split(/[\n,]+/).map(value => value.trim()).filter(Boolean);
        if (editor.mode === "base") {
          const group = state.groups.find(item => FTTestProducts.groupID(item) === productGroupRef);
          model().addBaseBatch(state, {
            name: name.value.trim(), product_path_selection: group,
            factorAliases: factorRefs, splitCount: splitCount.value,
            groupIndex: groupIndex.value, allGroups: allGroups.checked,
          });
        } else if (editor.mode === "edit") {
          const previousOverrides = model().registeredOverrides(current, state.manifest);
          const cleared = Object.fromEntries(Object.keys(previousOverrides).map(key => [key, undefined]));
          const patch = {
            ...cleared, ...parsedOverrides, name: name.value.trim() || current.name,
            productMask,
          };
          if (!derived) {
            const group = state.groups.find(item => FTTestProducts.groupID(item) === productGroupRef);
            Object.assign(patch, {
              product_path_selection: FTTestProducts.projection(group),
              product_path_selection_id: productGroupRef,
              factorAlias: factorRefs[0] || "",
              splitCount: splitCount.value,
              groupIndex: groupIndex.value,
            });
          }
          model().updateGroup(state, current.id, patch);
        } else {
          model().addDerived(state, parent.id, {
            name: name.value.trim(), productMask, overrides: parsedOverrides,
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
    form.append(grid);
    const overrides = FTBacktestGroupOverrides.render({
      context, manifest: state.manifest, inheritedValues: state.values,
      overrides: model().registeredOverrides(current, state.manifest),
    });
    const overrideDetails = document.createElement("details");
    const overrideSummary = document.createElement("summary");
    overrideSummary.textContent = context.t("Long-Short 覆盖设置");
    overrideDetails.append(overrideSummary, field(context.t("覆盖字段"), overrides));
    form.append(overrideDetails);
    appendActions(context, form, () => {
      try {
        const parsedOverrides = overrides.value();
        if (current) {
          const previous = model().registeredOverrides(current, state.manifest);
          const cleared = Object.fromEntries(Object.keys(previous).map(key => [key, undefined]));
          model().updateLongShort(state, current.id, {
            ...cleared, ...parsedOverrides,
            name: name.value.trim() || current.name,
            longGroupId: longGroupRef, shortGroupId: shortGroupRef,
          });
        } else {
          model().addLongShort(
            state, longGroupRef, shortGroupRef, name.value, parsedOverrides,
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

  function groupPicker(context, state, selected, onChange) {
    const saveGroup = value => {
      const id = FTTestProducts.groupID(value);
      if (!id) return;
      const index = state.groups.findIndex(item => FTTestProducts.groupID(item) === id);
      if (index >= 0) state.groups[index] = {...state.groups[index], ...value};
      else state.groups.push(value);
      onChange?.([id]);
    };
    return FTTestObjectPicker.create(context, {
      title: context.t("产品组"),
      items: state.groups.map(item => ({
        value: FTTestProducts.groupID(item),
        label: FTTestProducts.groupLabel(item),
        description: item.description || item.desc || FTTestProducts.groupLabel(item),
        source_managed: item.source_managed === true,
      })).filter(item => item.value),
      selected: selected ? [selected] : [], multi: false, name: "backtest-product-group",
      onCreate: context.session ? () => void FTTestObjectEditorOverlay.open(context, {
        kind: "product_group", mode: "create", ref: "new", onSaved: saveGroup,
      }) : null,
      createLabel: context.t("新建产品组"), onChange,
      itemActions: item => {
        const group = state.groups.find(value => FTTestProducts.groupID(value) === item.value);
        if (!context.session || !group || group.source_managed) return [];
        return [editAction(context, "product_group", item.value, saveGroup)];
      },
    });
  }

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

  function factorPicker(context, state, selected, multi, onChange) {
    const saveFactor = value => {
      if (!value) return;
      const alias = factorAlias(value);
      const index = (state.factors || []).findIndex(item => factorAlias(item) === alias);
      if (index >= 0) state.factors[index] = {...state.factors[index], ...value};
      else state.factors.push(value);
      onChange?.(multi ? [alias] : [alias]);
    };
    return FTTestObjectPicker.create(context, {
      title: context.t("因子"),
      items: (state.factors || []).map(item => {
        const alias = factorAlias(item);
        return {
          value: alias, label: alias,
          description: item.description || item.desc || item.family || alias,
        };
      }).filter(item => item.value),
      selected, multi, name: `backtest-factors-${multi ? "multi" : "single"}`,
      onCreate: context.session ? () => void FTTestObjectEditorOverlay.open(context, {
        kind: "factor", mode: "create", ref: "new", onSaved: saveFactor,
      }) : null,
      createLabel: context.t("新建因子"), onChange,
      itemActions: item => {
        const factor = (state.factors || []).find(value => factorAlias(value) === item.value);
        const ref = factor?.factor_alias || factor?.alias || factor?.id || item.value;
        if (!context.session || !factor?.can_edit || factor.is_public) return [];
        return [editAction(context, "factor", ref, saveFactor)];
      },
    });
  }

  function editAction(context, kind, ref, onSaved) {
    return {
      label: context.t("编辑"), title: context.t("在当前浮层编辑"),
      buttonClass: "secondary",
      onClick: event => {
        event?.preventDefault();
        void FTTestObjectEditorOverlay.open(context, {
          kind, mode: "edit", ref, onSaved,
        });
      },
    };
  }

  function selectedFactorAliases(state, defaults) {
    const values = defaults.factorAliases || defaults.factor_aliases;
    if (Array.isArray(values) && values.length) return values.map(String).filter(Boolean);
    return [defaults.factorAlias || selectedFactorAlias(state)].filter(Boolean);
  }

  function factorAlias(value) {
    return value?.factor_alias || value?.alias || value?.name || "";
  }

  function selectedFactorAlias(state) {
    return factorAlias(FTTestFactors.selectedFactor(state));
  }

  function titleFor(context, mode) {
    return context.t({
      base: "新增分组", derived: "派生组", clone: "复制为派生组",
      edit: "编辑分组", rename: "重命名策略", ls: "Long-Short 组合",
    }[mode] || "分组");
  }

  window.FTBacktestGroupForm = Object.freeze({render});
})();
