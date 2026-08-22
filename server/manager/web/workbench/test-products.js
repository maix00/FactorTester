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
    const groupedRefs = (analysis.configuration_groups || [])
      .map(item => item?.product_scope_ref).filter(Boolean);
    const frozenSelections = analysis.product_selections || {};
    const values = [
      ...(ui.product_group_refs || []),
      ...(analysis.product_path_selections || []),
      ...groupedRefs,
      ...Object.keys(frozenSelections),
      ...Object.values(frozenSelections),
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
      state.productGroupIndex = new Map(state.groups.map(group => [groupID(group), group]));
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

  function openEditor(context, mode, ref, onSaved, testState = null, initialValue = null) {
    return FTTestObjectEditorOverlay.open(context, {
      kind: "product_group", mode, ref, onSaved, testState,
      temporary: mode === "create" || initialValue?.temporary === true,
      initialValue,
    });
  }

  function upsertGroup(state, group) {
    const id = groupID(group);
    if (!id) return null;
    const index = state.groups.findIndex(value => groupID(value) === id);
    if (index >= 0) state.groups[index] = {...state.groups[index], ...group};
    else state.groups.push(group);
    const saved = state.groups[index >= 0 ? index : state.groups.length - 1];
    state.productGroupIndex = new Map(state.groups.map(value => [groupID(value), value]));
    return saved;
  }

  function editAction(context, group, onSaved, state = null) {
    if (!context.session || !group) return null;
    const id = groupID(group);
    if (!id || group.source_managed) return null;
    return {
      label: context.t("编辑"),
      title: context.t("在当前浮层编辑产品组"),
      buttonClass: "secondary",
      onClick: event => {
        event?.preventDefault();
        void openEditor(context, "edit", id, onSaved, group.temporary ? state : null, group);
      },
    };
  }

  function panel(context, state, refresh) {
    const root = document.createElement("div");
    root.className = "test-product-manager";
    root.append(selectionPanel(context, state, refresh));
    return root;
  }

  function selectionPanel(context, state, refresh, options = {}) {
    const allGroups = Array.isArray(options.groups) ? options.groups : state.groups;
    const groups = options.constrain !== false
      && window.FTStrategyEditorScope?.constrainedCandidates
      ? FTStrategyEditorScope.constrainedCandidates(
          state, "product_path_candidates", allGroups,
        )
      : allGroups;
    const selectedRefs = Array.isArray(options.selectedRefs)
      ? uniqueReferences(options.selectedRefs)
      : (state.kind === "ic" ? state.groupRefs : [state.groupRef]).filter(Boolean);
    const selectedSet = new Set(selectedRefs);
    const selected = groups.filter(group => selectedSet.has(groupID(group)));
    const pathCount = selected.reduce((total, group) => (
      total + (group.path_count ?? group.paths?.length ?? group.selected_paths?.length ?? 0)
    ), 0);
    const pickerItems = () => groups.map(group => ({
      value: groupID(group),
      label: groupLabel(group),
      description: [
        group.description || group.desc || "",
        `${group.path_count ?? group.paths?.length ?? group.selected_paths?.length ?? 0} ${context.t("条产品路径")}`,
      ].filter(Boolean).join(" · "),
      source_managed: group.source_managed === true,
    })).filter(item => item.value);
    let picker = null;
    const savedGroup = value => {
      const group = upsertGroup(state, value);
      if (!group) return;
      if (allGroups !== state.groups) {
        const index = allGroups.findIndex(item => groupID(item) === groupID(group));
        if (index >= 0) allGroups[index] = group; else allGroups.push(group);
      }
      if (typeof options.onChange === "function") {
        options.onChange([groupID(group)]);
      } else {
        selectNew(state, group);
        synchronize(state);
      }
      picker?.setItems(pickerItems());
      picker?.setValues([groupID(group)]);
      refresh?.();
    };
    picker = FTTestObjectPicker.create(context, {
      title: context.t("产品路径候选"),
      note: context.t(state.kind === "ic"
        ? "可多选产品组；每个候选冻结为独立 IC 任务"
        : "选择一个产品组作为本次回测的产品范围"),
      items: pickerItems(),
      selected: selectedRefs,
      multi: options.multi ?? (state.kind === "ic"),
      loading: FTTestObjectPicker.lazyLoading(state, "products"),
      loadingText: context.t("正在读取产品组候选…"),
      compact: true,
      name: `test-product-groups-${state.kind}`,
      onCreate: context.session && options.canCreate !== false
        ? () => void openEditor(context, "create", "new", savedGroup, state)
        : null,
      createLabel: context.t("新建产品组"),
      itemActions: item => {
        const action = editAction(
          context,
          groups.find(group => groupID(group) === item.value),
          savedGroup, state,
        );
        return action ? [action] : [];
      },
      onChange: values => {
        const refs = uniqueReferences(values);
        if (typeof options.onChange === "function") {
          options.onChange(refs);
        } else if (state.kind === "ic") {
          state.groupRefs = refs;
          state.groupRef = refs[0] || "";
        } else {
          state.groupRef = refs[0] || "";
          state.groupRefs = state.groupRef ? [state.groupRef] : [];
        }
        synchronize(state);
        refresh?.();
      },
    });
    const summary = `${context.t("已选")} ${selected.length} ${context.t("个候选")} · ${pathCount} ${context.t("条产品路径")}`;
    const help = window.FTTestFieldHelp?.forField?.(
      state.manifest,
      state.kind === "ic"
        ? ["product_path_selections", "product_path_selection"]
        : ["product_path_selection", "product_path_selections"],
      context,
    ) || "";
    const root = FTTestFieldRow.create(
      context.t("产品组"), picker.element, help,
      {className: "test-product-selector"},
    );
    const summaryNote = document.createElement("small");
    summaryNote.className = "test-product-selection-summary";
    summaryNote.textContent = summary;
    root.querySelector(".test-field-row-control")?.append(summaryNote);
    const unavailable = selectedRefs.filter(ref => (
      !groups.some(group => groupID(group) === ref)
    ));
    if (unavailable.length) {
      const warning = document.createElement("small");
      warning.className = "test-product-warning";
      warning.textContent = `${context.t("当前不可用的产品组")}: ${unavailable.join("、")}`;
      root.querySelector(".test-field-row-control").append(warning);
    }
    return root;
  }

  window.FTTestProducts = Object.freeze({
    groupID, groupLabel, projection, restoreReferences, synchronize,
    selectedGroups, selectedProjections, setSelected, selectNew, panel,
    selectionPanel,
  });
})();
