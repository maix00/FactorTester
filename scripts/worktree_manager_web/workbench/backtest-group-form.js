(() => {
  const model = () => window.FTBacktestGroupModel;

  function render(context, state, editor, onFinish) {
    const form = document.createElement("form");
    form.className = "backtest-group-form";
    const title = document.createElement("h3");
    title.textContent = titleFor(context, editor.mode);
    form.append(title);
    if (editor.mode === "ls") {
      renderLongShort(context, state, editor, form, onFinish);
    } else {
      renderGroup(context, state, editor, form, onFinish);
    }
    return form;
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
    let factor;
    let splitCount;
    let groupIndex;
    let allGroups;
    if (!derived) {
      productGroup = select(state.groups, item => FTTestProducts.groupID(item), item => (
        FTTestProducts.groupLabel(item)
      ));
      productGroup.value = defaults.product_path_selection_id
        || FTTestProducts.groupID(defaults.product_path_selection)
        || state.groupRef || "";
      factor = editor.mode === "base"
        ? factorChecklist(context, state.factors, defaults.factorAlias || selectedFactorAlias(state))
        : select(state.factors, factorAlias, factorAlias);
      if (editor.mode !== "base") factor.value = defaults.factorAlias || selectedFactorAlias(state);
      splitCount = input("number", defaults.splitCount || state.values.split_count || 5);
      splitCount.min = "1"; splitCount.step = "1";
      groupIndex = input("number", defaults.groupIndex || state.values.group_index || 1);
      groupIndex.min = "1"; groupIndex.step = "1";
      const structure = document.createElement("div");
      structure.className = "backtest-group-form-grid";
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
    overrideDetails.append(overrideSummary, field(
      context.t("覆盖字段"), overrides, context.t("只保存本组显式覆盖的注册字段"),
    ));
    form.append(overrideDetails);

    appendActions(context, form, async () => {
      try {
        const parsedOverrides = overrides.value();
        const productMask = mask.value.split(/[\n,]+/).map(value => value.trim()).filter(Boolean);
        if (editor.mode === "base") {
          const group = state.groups.find(item => FTTestProducts.groupID(item) === productGroup.value);
          model().addBaseBatch(state, {
            name: name.value.trim(), product_path_selection: group,
            factorAliases: factor.selectedAliases(), splitCount: splitCount.value,
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
            const group = state.groups.find(item => FTTestProducts.groupID(item) === productGroup.value);
            Object.assign(patch, {
              product_path_selection: FTTestProducts.projection(group),
              product_path_selection_id: productGroup.value,
              factorAlias: factor.value,
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
    const groups = model().rootsAndChildren(state).map(item => item.group);
    const longGroup = select(groups, item => item.id, model().groupLabel);
    const shortGroup = select(groups, item => item.id, model().groupLabel);
    longGroup.value = editor.groupIDs?.[0] || "";
    shortGroup.value = editor.groupIDs?.[1] || "";
    const name = input("text", "");
    name.placeholder = context.t("组合名称（留空自动生成）");
    const grid = document.createElement("div");
    grid.className = "backtest-group-form-grid";
    grid.append(
      field(context.t("多头组"), longGroup),
      field(context.t("空头组"), shortGroup),
      field(context.t("名称"), name),
    );
    const swap = context.button(context.t("交换多空"), () => {
      const value = longGroup.value; longGroup.value = shortGroup.value; shortGroup.value = value;
    });
    swap.type = "button";
    grid.append(swap);
    form.append(grid);
    appendActions(context, form, () => {
      try {
        model().addLongShort(state, longGroup.value, shortGroup.value, name.value);
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
    const root = document.createElement("label");
    const title = document.createElement("b"); title.textContent = label;
    root.append(title, control);
    if (help) { const copy = document.createElement("small"); copy.textContent = help; root.append(copy); }
    return root;
  }

  function input(type, value) {
    const control = document.createElement("input");
    control.type = type;
    if (type === "checkbox") control.checked = Boolean(value); else control.value = value ?? "";
    return control;
  }

  function select(values, valueFor, labelFor) {
    const control = document.createElement("select");
    const empty = document.createElement("option"); empty.value = ""; empty.textContent = "—";
    control.append(empty);
    for (const value of values || []) {
      const option = document.createElement("option");
      option.value = String(valueFor(value) || "");
      option.textContent = String(labelFor(value) || option.value);
      control.append(option);
    }
    return control;
  }

  function factorChecklist(context, values, selected = "") {
    const root = document.createElement("div");
    root.className = "backtest-factor-checklist";
    const selectedAliases = new Set(selected ? [selected] : []);
    for (const factor of values || []) {
      const alias = factorAlias(factor);
      if (!alias) continue;
      const label = document.createElement("label");
      const input = document.createElement("input"); input.type = "checkbox";
      input.checked = selectedAliases.has(alias);
      const copy = document.createElement("span"); copy.textContent = alias;
      label.append(input, copy); root.append(label);
    }
    root.selectedAliases = () => [...root.querySelectorAll("label")]
      .filter(label => label.querySelector("input")?.checked)
      .map(label => label.querySelector("span")?.textContent || "")
      .filter(Boolean);
    const actions = document.createElement("div");
    actions.className = "backtest-factor-checklist-actions";
    const all = context.button(context.t("全选"), () => {
      root.querySelectorAll('input[type="checkbox"]').forEach(input => { input.checked = true; });
    });
    const clear = context.button(context.t("清空"), () => {
      root.querySelectorAll('input[type="checkbox"]').forEach(input => { input.checked = false; });
    });
    all.type = "button"; clear.type = "button";
    actions.append(all, clear); root.prepend(actions);
    return root;
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
      edit: "编辑分组", ls: "创建 Long-Short 组合",
    }[mode] || "分组");
  }

  window.FTBacktestGroupForm = Object.freeze({render});
})();
