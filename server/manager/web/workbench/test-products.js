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

  async function hydrateReferencedGroups(context, state, catalog = []) {
    const known = new Set((catalog || []).map(groupID).filter(Boolean));
    const missing = uniqueReferences(state.groupRefs || []).filter(ref => (
      ref.startsWith("product-group:") && !known.has(ref)
    ));
    if (!missing.length) return catalog;
    const resolved = await Promise.all(missing.map(async ref => {
      try {
        const value = await context.api(
          `/api/product-library/product-groups/${encodeURIComponent(ref)}`,
        );
        return value?.group || null;
      } catch (_error) {
        return null;
      }
    }));
    return [...catalog, ...resolved.filter(Boolean)];
  }

  function hasResolvedLabel(group) {
    const id = groupID(group);
    const label = group?.title_zh || group?.name || group?.label || "";
    return Boolean(id && label && label !== id && group?._savedPlaceholder !== true);
  }

  function needsReferenceHydration(state) {
    const catalog = new Map((state.groups || []).map(group => [groupID(group), group]));
    return uniqueReferences(state.groupRefs || []).some(ref => (
      ref.startsWith("product-group:") && !hasResolvedLabel(catalog.get(ref))
    ));
  }

  async function hydrateStateReferences(context, state) {
    if (!needsReferenceHydration(state)) return false;
    const resolvedCatalog = (state.groups || []).filter(hasResolvedLabel);
    const hydrated = await hydrateReferencedGroups(context, state, resolvedCatalog);
    const byID = new Map((state.groups || []).map(group => [groupID(group), group]));
    for (const group of hydrated) {
      const id = groupID(group);
      if (id) byID.set(id, group);
    }
    state.groups = [...byID.values()];
    synchronize(state);
    return true;
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
      ...(analysis.execution?.settings?.product_path_selections || []),
      analysis.product_path_selection,
      analysis.product_path_selection_id,
      analysis.execution?.settings?.product_group_ref,
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

  function retainedImportedGroups(state) {
    const referenced = new Set(uniqueReferences(state.groupRefs || []));
    const saved = state.savedGroupIDs instanceof Set
      ? state.savedGroupIDs : new Set();
    return (state.groups || []).filter(group => {
      const id = groupID(group);
      return group?.temporary === true || group?.source_kind === "transient"
        || ["inline", "test_inline"].includes(group?.origin)
        || ["inline", "test_inline"].includes(group?.source_origin)
        // Assistance documents and old frozen configurations may contain a
        // complete referenced object without a transient-origin marker.  It
        // is still an authoritative candidate for this draft and must not be
        // discarded merely because the server directory does not list it.
        || (referenced.has(id) && saved.has(id));
    });
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
    return FTTestLazyCode.openObjectEditor(context, {
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

  function panel(context, state, refresh) {
    const root = document.createElement("div");
    root.className = "test-product-manager";
    root.append(selectionPanel(context, state, refresh));
    return root;
  }

  function selectionPanel(context, state, refresh, options = {}) {
    if (state.lazy?.products?.status === "idle") {
      void window.FTTests?.ensureProductsForExecution?.(context, state, refresh);
    }
    const allGroups = () => {
      const current = typeof options.groups === "function"
        ? options.groups() : (Array.isArray(options.groups) ? options.groups : state.groups);
      return Array.isArray(current) ? current : [];
    };
    const groups = () => options.constrain !== false
      && window.FTStrategyEditorScope?.constrainedCandidates
      ? FTStrategyEditorScope.constrainedCandidates(
          state, "product_path_candidates", allGroups(),
        )
      : allGroups();
    const selectedRefs = Array.isArray(options.selectedRefs)
      ? uniqueReferences(options.selectedRefs)
      : (state.kind === "ic" ? state.groupRefs : [state.groupRef]).filter(Boolean);
    const catalogStatus = () => {
      const catalogError = String(state.lazy?.products?.error || "").trim();
      const unavailable = selectedRefs.filter(ref => (
        !groups().some(group => groupID(group) === ref)
      ));
      return {
        errorText: catalogError
          ? `${context.t("产品组候选读取失败")}: ${catalogError}` : "",
        statusText: unavailable.length
          ? `${context.t("当前不可用的产品组")}: ${unavailable.join("、")}` : "",
      };
    };
    let picker = null;
    const savedGroup = value => {
      const group = upsertGroup(state, value);
      if (!group) return;
      const scopedGroups = allGroups();
      if (scopedGroups !== state.groups) {
        const index = scopedGroups.findIndex(item => groupID(item) === groupID(group));
        if (index >= 0) scopedGroups[index] = group; else scopedGroups.push(group);
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
    const pickerItems = () => groups().map(group => {
      const view = window.FTFactorDetailShared?.productGroupRowView?.(group)
        || {kind: "product_group", ref: groupID(group)};
      return {
        value: groupID(group),
        label: groupLabel(group),
        description: [
          group.description || group.desc || "",
          `${group.path_count ?? group.paths?.length ?? group.selected_paths?.length ?? 0} ${context.t("条产品路径")}`,
        ].filter(Boolean).join(" · "),
        source_managed: group.source_managed === true,
        group,
        view: {...view, onSaved: savedGroup},
      };
    }).filter(item => item.value);
    const syncCatalog = () => {
      picker?.setStatus({loading: false, ...catalogStatus()});
      picker?.setItems(pickerItems());
    };
    picker = FTTestObjectPicker.create(context, {
      title: context.t("产品路径候选"),
      note: context.t(state.kind === "ic"
        ? "可多选产品组；每个候选冻结为独立 IC 任务"
        : "选择一个产品组作为本次回测的产品范围"),
      items: pickerItems(),
      selected: selectedRefs,
      multi: options.multi ?? (state.kind === "ic"),
      loading: options.loading ?? FTTestObjectPicker.lazyLoading(state, "products"),
      loadingText: context.t("正在读取产品组候选…"),
      ...catalogStatus(),
      compact: true,
      name: `test-product-groups-${state.kind}`,
      onCreate: context.session && options.canCreate !== false
        ? () => void openEditor(context, "create", "new", savedGroup, state)
        : null,
      createLabel: context.t("新建产品组"),
      testState: state,
      onRefresh: async () => {
        picker?.setStatus({loading: true, text: "", errorText: ""});
        await window.FTTests?.refreshProductsForExecution?.(context, state, refresh);
        syncCatalog();
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
    const catalogPromise = state.lazy?.products?.promise;
    if (catalogPromise && typeof catalogPromise.then === "function") {
      void catalogPromise.then(syncCatalog, syncCatalog);
    }
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
    return root;
  }

  window.FTTestProducts = Object.freeze({
    groupID, groupLabel, projection, restoreReferences, synchronize,
    selectedGroups, selectedProjections, setSelected, selectNew, panel,
    selectionPanel, hydrateReferencedGroups, hydrateStateReferences,
    retainedImportedGroups,
    needsReferenceHydration,
  });
})();
