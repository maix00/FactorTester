(() => {
  function groupID(value) {
    return value?.group_ref || value?.product_group_ref || value?.id
      || value?.product_group_template_id || value?.product_path_selection_id || "";
  }

  function groupLabel(value) {
    return value?.title_zh || value?.name || value?.label || groupID(value);
  }

  function projection(group) {
    const id = groupID(group);
    const paths = [...(group?.paths || group?.selected_paths || [])];
    return {
      product_path_selection_id: id,
      product_group_template_id: id,
      label: groupLabel(group),
      selected_paths: paths,
      paths,
    };
  }

  function referenceOf(value) {
    return typeof value === "string" ? value : groupID(value);
  }

  function uniqueReferences(values) {
    return [...new Set((values || []).map(referenceOf).filter(Boolean))];
  }

  function restoreReferences(analysis = {}, ui = {}) {
    const values = [
      ...(ui.product_group_refs || []),
      ...(analysis.product_path_selections || []),
      ...(analysis.local_settings?.product_path_selections || []),
      analysis.product_path_selection,
      analysis.product_path_selection_id,
      analysis.local_settings?.product_group_ref,
      ui.product_group_ref,
    ];
    return uniqueReferences(values);
  }

  function synchronize(state) {
    const saved = uniqueReferences(state.values?.product_path_selections || []);
    if (state.kind === "ic") {
      state.groupRefs = uniqueReferences(state.groupRefs?.length ? state.groupRefs : saved);
      state.groupRef = state.groupRefs[0] || "";
    } else {
      state.groupRef = state.groupRef || saved[0] || "";
      state.groupRefs = state.groupRef ? [state.groupRef] : [];
    }
    if (state.values) {
      state.values.product_path_candidates = state.groups.map(projection);
      state.values.product_path_selections = selectedGroups(state).map(projection);
    }
    return state.groupRefs;
  }

  function selectedGroups(state) {
    const selected = new Set(state.kind === "ic" ? state.groupRefs : [state.groupRef]);
    return state.groups.filter(group => selected.has(groupID(group)));
  }

  function selectedProjections(state) {
    return selectedGroups(state).map(projection);
  }

  function setSelected(state, group, checked) {
    const id = groupID(group);
    if (state.kind === "ic") {
      const refs = new Set(state.groupRefs || []);
      if (checked) refs.add(id); else refs.delete(id);
      state.groupRefs = [...refs];
    } else {
      state.groupRef = checked ? id : "";
    }
    synchronize(state);
  }

  function selectNew(state, group) {
    setSelected(state, group, true);
  }

  function panel(context, state, refresh) {
    const root = document.createElement("div");
    root.className = "test-product-manager";
    root.append(candidatePanel(context, state, refresh));
    const toolbar = document.createElement("div");
    toolbar.className = "test-product-manager-actions";
    toolbar.append(context.button(context.t("构建产品路径候选"), () => {
      FTProductGroupCreator.open(context, {
        onCreate: group => {
          state.groups.push(group);
          selectNew(state, group);
          refresh?.();
        },
      });
    }));
    root.append(toolbar);
    return root;
  }

  function candidatePanel(context, state, refresh) {
    const root = document.createElement("fieldset");
    root.className = "test-product-selector test-object-field";
    const legend = document.createElement("legend");
    legend.textContent = context.t("产品路径候选");
    const note = document.createElement("small");
    note.textContent = context.t(state.kind === "ic"
      ? "可多选产品路径候选；每个候选冻结为独立任务，并共同计算所选因子"
      : "选择一个候选作为本次回测的产品范围；候选内部可包含多条产品路径");
    const summary = document.createElement("small");
    const selected = selectedGroups(state);
    const pathCount = selected.reduce((total, group) => (
      total + (group.path_count ?? group.paths?.length ?? group.selected_paths?.length ?? 0)
    ), 0);
    summary.className = "test-product-selection-summary";
    summary.textContent = `${context.t("已选")} ${selected.length} ${context.t("个候选")} · ${pathCount} ${context.t("条产品路径")}`;
    const list = document.createElement("div");
    list.className = "test-product-group-list";
    for (const group of state.groups) {
      const row = document.createElement("label");
      const input = document.createElement("input");
      input.type = state.kind === "ic" ? "checkbox" : "radio";
      input.name = state.kind === "ic" ? "" : `product-path-${state.kind}`;
      input.checked = state.kind === "ic"
        ? (state.groupRefs || []).includes(groupID(group))
        : state.groupRef === groupID(group);
      input.addEventListener("change", () => {
        setSelected(state, group, input.checked);
        refresh?.();
      });
      const copy = document.createElement("span");
      const title = document.createElement("b");
      title.textContent = groupLabel(group);
      const detail = document.createElement("small");
      const count = group.path_count ?? group.paths?.length ?? 0;
      detail.textContent = `${count} ${context.t("条产品路径")}`;
      copy.append(title, detail);
      row.append(input, copy);
      list.append(row);
    }
    if (!state.groups.length) list.append(FTUI.empty(context.t("暂无产品组"), ""));
    const unavailable = (state.groupRefs || []).filter(ref => (
      !state.groups.some(group => groupID(group) === ref)
    ));
    if (unavailable.length) {
      const warning = document.createElement("small");
      warning.className = "test-product-warning";
      warning.textContent = `${context.t("当前不可用的产品组")}: ${unavailable.join("、")}`;
      root.append(legend, note, summary, list, warning);
    } else {
      root.append(legend, note, summary, list);
    }
    return root;
  }

  window.FTTestProducts = Object.freeze({
    groupID, groupLabel, projection, restoreReferences, synchronize,
    selectedGroups, selectedProjections, setSelected, selectNew, panel,
  });
})();
