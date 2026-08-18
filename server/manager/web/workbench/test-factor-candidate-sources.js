(() => {
  function descriptor(state) {
    return Object.entries(state?.manifest?.defaults || {}).find(([, field]) => (
      field?.serialization?.kind === "factor_source_selection_list"
    )) || null;
  }

  function storageKey(state) {
    const entry = descriptor(state);
    return entry ? FTSettingRules.storageKey(entry[0], entry[1]) : "";
  }

  function selections(state) {
    const key = storageKey(state);
    const value = key ? state.values?.[key] : [];
    if (Array.isArray(value) && value.length) return value.filter(Boolean);
    // Existing workspace settings may contain only the old derived candidate
    // pool.  This is a UI-state fallback, not RunSpec compatibility: the next
    // authoring save writes the explicit direct-source field.
    return FTTestFactorSelection.candidates(state).filter(item => (
      !(item.factor_set_refs || []).length && !item.factor_set_only
    ));
  }

  function factorID(value) {
    return FTTestFactorSelection.factorID(value);
  }

  function factorLabel(value) {
    return FTTestFactorSelection.factorAlias(value) || factorID(value);
  }

  function catalogItems(state) {
    const byID = new Map();
    const add = item => {
      const value = window.FTFactorModel?.withSourceMetadata?.(item) || item;
      const id = factorID(value);
      if (!id || item?.factor_set_only) return;
      const previous = byID.get(id);
      byID.set(id, previous ? {...previous, ...value} : value);
    };
    (state.factors || []).forEach(add);
    (state.savedFactors || []).forEach(add);
    FTTestFactorSelection.candidates(state).forEach(add);
    selections(state).forEach(add);
    return [...byID.values()];
  }

  function pickerItems(context, state) {
    return catalogItems(state).map(factor => ({
      value: factorID(factor),
      label: factorLabel(factor),
      description: FTTestFactorCandidates.sourceDescription(context, state, factor),
      factor,
    })).filter(item => item.value);
  }

  function writeSelections(state, values) {
    const key = storageKey(state) || "factor_source_selections";
    const entry = descriptor(state);
    if (entry && window.FTSettingRules?.setValue) {
      FTSettingRules.setValue(state.manifest, state.values, entry[0], entry[1], values);
    } else {
      state.values[key] = values;
    }
  }

  function normalizeSelectedValues(state, values) {
    const items = new Map(catalogItems(state).map(item => [factorID(item), item]));
    return [...new Set((values || []).map(value => (
      typeof value === "string" ? value : factorID(value)
    )).filter(Boolean))]
      .map(id => items.get(id) || selections(state).find(item => factorID(item) === id))
      .filter(Boolean);
  }

  function syncCandidates(state, values) {
    const selected = normalizeSelectedValues(state, values);
    const wanted = new Set(selected.map(factorID));
    const rows = FTTestFactorSelection.candidates(state);
    for (const candidate of rows) {
      const id = factorID(candidate);
      if (!id || wanted.has(id) || (candidate.factor_set_refs || []).length) continue;
      FTTestFactorSelection.removeCandidate(state, candidate);
    }
    for (const factor of selected) {
      FTTestFactorSelection.addCandidate(state, {
        ...factor,
        source_kind: factor.source_kind || "factor_library",
      }, {select: false});
    }
    writeSelections(state, selected);
    FTTestFactorSelection.syncSelection(state);
  }

  function saveFactor(context, state, refresh, picker, value) {
    if (!value) return;
    const id = factorID(value);
    if (!id) return;
    const existing = catalogItems(state).find(item => factorID(item) === id);
    const factor = window.FTFactorModel?.withSourceMetadata?.(
      existing ? {...existing, ...value} : value,
    ) || (existing ? {...existing, ...value} : value);
    state.factors = Array.isArray(state.factors) ? state.factors : [];
    const index = state.factors.findIndex(item => factorID(item) === id);
    if (index >= 0) state.factors[index] = {...state.factors[index], ...factor};
    else state.factors.push(factor);
    const next = [...selections(state), factor];
    syncCandidates(state, next);
    picker?.setItems(pickerItems(context, state));
    picker?.setValues(next.map(factorID));
    refresh?.();
  }

  function directControl(context, state, refresh) {
    let picker;
    const selected = selections(state).map(factorID).filter(Boolean);
    picker = FTTestObjectPicker.create(context, {
      title: context.t("因子"),
      note: context.t("从可见因子库多选直接来源；新建因子只在当前浮层完成"),
      className: "test-factor-direct-source-picker",
      compact: true,
      name: "test-factor-direct-sources",
      items: pickerItems(context, state),
      selected,
      multi: true,
      loading: state.lazy?.factors?.status === "loading",
      loadingText: context.t("正在读取因子候选…"),
      onCreate: context.session ? () => void (
        window.FTStrategyEditorFactorOverlay?.open
          ? FTStrategyEditorFactorOverlay.open(
            context, state, value => saveFactor(context, state, refresh, picker, value),
          )
          : null
      ) : null,
      createLabel: context.t("新建因子"),
      onChange: values => {
        syncCandidates(state, values);
        refresh?.();
      },
    });
    return FTTestFieldRow.create(
      context.t("因子"), picker.element,
      window.FTTestFieldHelp?.forField?.(
        state.manifest, "factor_source_selections", context,
      ) || "",
    );
  }

  function panel(context, state, refresh) {
    const root = document.createElement("div");
    root.className = "test-factor-candidate-sources";
    const sets = FTTestFactorSets.control(context, state, refresh);
    if (sets) root.append(FTTestFieldRow.create(
      context.t("因子集合"), sets,
      window.FTTestFieldHelp?.forField?.(
        state.manifest, "factor_set_selections", context,
      ) || "",
    ));
    root.append(directControl(context, state, refresh));
    // factor_candidates is derived from the two rows above.  Keep this row
    // last so the empty-state copy “从上方…添加” always describes the DOM
    // order, including after lazy candidate catalogs finish loading.
    root.append(FTTestFieldRow.create(
      context.t("因子候选"), FTTestFactorCandidates.summaryControl(context, state),
      window.FTTestFieldHelp?.forField?.(
        state.manifest, "factor_candidates", context,
      ) || "",
      {className: "test-factor-candidate-heading-row"},
    ));
    return root;
  }

  window.FTTestFactorCandidateSources = Object.freeze({panel, selections, syncCandidates});
})();
