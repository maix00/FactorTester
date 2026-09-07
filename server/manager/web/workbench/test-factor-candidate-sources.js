(() => {
  const scopedSourceStates = new WeakMap();
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
    const catalog = state?.catalogSourceState || state;
    const byID = new Map();
    const add = item => {
      const value = window.FTFactorModel?.withSourceMetadata?.(item) || item;
      const id = factorID(value);
      if (!id || item?.factor_set_only) return;
      const previous = byID.get(id);
      byID.set(id, previous ? {...previous, ...value} : value);
    };
    (catalog.factors || []).forEach(add);
    (catalog.savedFactors || []).forEach(add);
    if (catalog !== state) {
      (state.factors || []).forEach(add);
      (state.savedFactors || []).forEach(add);
    }
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
      temporary: factor.temporary === true,
      onsite: factor.temporary === true,
      view: window.FTFactorDetailShared?.factorRowView?.(factor)
        || {kind: "factor", ref: factorID(factor)},
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
      loading: FTTestObjectPicker.lazyLoading(state, "factors"),
      loadingText: context.t("正在读取因子候选…"),
      errorText: state.lazy?.factors?.error || "",
      onCreate: context.session ? () => void (
        window.FTStrategyEditorFactorOverlay?.open
          ? FTStrategyEditorFactorOverlay.open(
            context, state, value => saveFactor(context, state, refresh, picker, value),
          )
          : null
      ) : null,
      createLabel: context.t("新建因子"),
      editSelected: item => item.factor?.temporary === true
        || item.factor?.source_kind === "transient",
      onEdit: (_event, item) => void FTStrategyEditorFactorOverlay.open(
        context, state,
        value => saveFactor(context, state, refresh, picker, value), item.factor,
      ),
      editLabel: context.t("编辑因子"),
      onChange: values => {
        syncCandidates(state, values);
        refresh?.();
      },
    });
    // A nested editor can open before the shared visible-factor catalog has
    // finished loading.  Its local authoring state must remain independent,
    // but the picker catalog is live shared data: refresh the already-mounted
    // control when that request completes instead of freezing the one saved
    // factor that happened to seed the draft.
    const catalogPromise = state.lazy?.factors?.promise;
    if (catalogPromise && typeof catalogPromise.then === "function") {
      void catalogPromise.then(() => {
        picker?.setItems(pickerItems(context, state));
        picker?.setValues(selections(state).map(factorID).filter(Boolean));
      }).catch(() => {});
    }
    return FTTestFieldRow.create(
      context.t("因子"), picker.element,
      window.FTTestFieldHelp?.forField?.(
        state.manifest, "factor_source_selections", context,
      ) || "",
    );
  }

  function controlElement(control) {
    return control?.element || control;
  }

  // Unified multi-type candidate picker: 因子 + 因子集合 in one control,
  // each grouped as 「候选（因子）」 / 「候选（因子集合）」 (via the shared
  // FTMultiSelectFilter candidate-type grouping).  Selection writes back to
  // the two distinct source fields: factor_source_selections (syncCandidates)
  // and factor_set_selections (FTTestFactorSets.updateSelection semantics).
  function combinedPickerItems(context, state) {
    const factors = pickerItems(context, state).map(item => ({
      ...item,
      type: "factor",
      typeLabel: context.t("因子"),
    }));
    const sets = (state.factorSetCatalog?.items || []).map(item => ({
      value: item.target_ref,
      label: item.title_zh || item.set_id || item.target_ref,
      description: item.description_zh
        || `${item.member_count || 0} ${context.t("个因子")}`,
      type: "factor_set",
      typeLabel: context.t("因子集合"),
      factorSet: item,
      temporary: item.temporary === true,
      onsite: item.temporary === true,
      view: window.FTFactorDetailShared?.factorSetRowView?.(item)
        || {kind: "factor_set", ref: item.target_ref},
    })).filter(item => item.value);
    return [...factors, ...sets];
  }

  function combinedControl(context, state, refresh) {
    const currentSetSelections = () => (
      window.FTTestFactorSets?.selections?.(state) || []
    );
    const currentSelected = () => [
      ...selections(state).map(factorID).filter(Boolean),
      ...currentSetSelections().map(item => item.target_ref).filter(Boolean),
    ];
    let items = combinedPickerItems(context, state);
    const syncPicker = () => {
      items = combinedPickerItems(context, state);
      picker.setItems(items);
      picker.setValues(currentSelected());
      refresh?.();
    };
    const saveCandidate = (value, previous = null) => {
      if (!value) return;
      if (previous?.type === "factor_set" || value.target_ref) {
        void FTTestFactorSets.addInlineSet(context, state, value, syncPicker);
        return;
      }
      if (previous && previous.value !== factorID(value)) {
        syncCandidates(state, selections(state).filter(row => (
          factorID(row) !== previous.value
        )));
      }
      saveFactor(context, state, syncPicker, null, value);
    };
    const picker = FTTestObjectPicker.create(context, {
      title: context.t("因子候选"),
      note: context.t("因子与冻结集合均作为候选，可跨类型多选"),
      className: "test-factor-direct-source-picker",
      compact: true,
      name: "test-factor-candidates",
      items,
      selected: currentSelected(),
      multi: true,
      loading: FTTestObjectPicker.lazyLoading(state, "factors"),
      loadingText: context.t("正在读取因子候选…"),
      errorText: state.lazy?.factors?.error || state.factorSetCatalog?.error || "",
      // Lazily load factor-set candidates so the 因子集合 group is populated.
      onOpen: async () => {
        if (!(state.factorSetCatalog?.items || []).length
          && window.FTTestFactorSets?.loadCatalog) {
          await window.FTTestFactorSets.loadCatalog(context, state);
          items = combinedPickerItems(context, state);
          picker.setItems(items);
          picker.setValues(currentSelected());
        }
      },
      // Per-type on-the-fly entry: the 「候选（因子）」/「候选（因子集合）」 heading "+"
      // creates the matching object type and lands it in that type's group.
      onAddCandidateForType: type => {
        if (type === "factor_set") {
          void FTTestLazyCode.openObjectEditor(context, {
            kind: "factor_set", mode: "create", ref: "new",
            temporary: true, testState: state,
            onSaved: saveCandidate,
          });
          return;
        }
        const onSaved = saveCandidate;
        void (window.FTStrategyEditorFactorOverlay?.open
          ? FTStrategyEditorFactorOverlay.open(context, state, onSaved)
          : FTTestLazyCode.openObjectEditor(context, {
            kind: "factor", mode: "create", ref: "new", onSaved,
            testState: state, temporary: true,
          }));
      },
      onCreate: context.session ? () => void (
        window.FTStrategyEditorFactorOverlay?.open
          ? FTStrategyEditorFactorOverlay.open(
            context, state, saveCandidate,
          ) : null
      ) : null,
      createLabel: context.t("新建因子"),
      editSelected: item => item.factor?.temporary === true
        || item.factor?.source_kind === "transient",
      onEdit: (_event, item) => void FTStrategyEditorFactorOverlay.open(
        context, state,
        value => saveCandidate(value, item), item.factor,
      ),
      editLabel: context.t("编辑因子"),
      onTemporaryCandidateUpdated: (previous, _next, saved) => saveCandidate(saved, previous),
      onTemporaryCandidateRemoved: item => {
        if (item.type === "factor_set") {
          state.factorSetCatalog.items = state.factorSetCatalog.items.filter(row => (
            row.target_ref !== item.value
          ));
        } else {
          state.factors = (state.factors || []).filter(row => factorID(row) !== item.value);
        }
        items = combinedPickerItems(context, state);
      },
      onChange: values => updateCombined(context, state, items, values, refresh).finally(() => {
        picker.setValues(currentSelected());
      }),
    });
    // A nested editor can open before the shared visible-factor catalog has
    // finished loading; refresh this picker when that request completes so the
    // 因子 candidate group stays live instead of freezing the seeded factor.
    const catalogPromise = state.lazy?.factors?.promise;
    if (catalogPromise && typeof catalogPromise.then === "function") {
      void catalogPromise.then(() => {
        items = combinedPickerItems(context, state);
        picker?.setItems(items);
        picker?.setValues(currentSelected());
      }).catch(() => {});
    }
    return picker;
  }

  async function updateCombined(context, state, items, values, refresh) {
    const requested = new Set(values);
    const factorItems = items.filter(item => item.type === "factor");
    const setItems = items.filter(item => item.type === "factor_set");
    // Factor branch: existing source-selection sync (factor_source_selections).
    syncCandidates(state, values.filter(value => (
      factorItems.some(item => item.value === value)
    )));
    // Factor-set branch: mirror FTTestFactorSets.updateSelection semantics.
    const currentSets = window.FTTestFactorSets?.selections?.(state) || [];
    const removed = currentSets.filter(item => !requested.has(item.target_ref));
    const added = setItems.filter(item => requested.has(item.value)
      && !currentSets.some(value => value.target_ref === item.value));
    state.factorSetCatalog.busy = true;
    state.factorSetCatalog.error = "";
    refresh?.();
    try {
      for (const item of removed) {
        FTTestFactorSelection.detachFactorSet(state, item.target_ref);
        FTTestInputState.detachFactorSet(state, item.target_ref);
        state.factorSetCatalog.runInputs.delete(item.target_ref);
      }
      window.FTTestFactorSets?.setSelections?.(
        state, currentSets.filter(item => requested.has(item.target_ref)),
      );
      for (const item of added) {
        const source = (state.factorSetCatalog?.items || []).find(value => (
          value.target_ref === item.value
        ));
        if (source && window.FTTestFactorSets?.selectSet) {
          await window.FTTestFactorSets.selectSet(context, state, source);
        }
      }
    } catch (error) {
      state.factorSetCatalog.error = error.message || String(error);
    } finally {
      state.factorSetCatalog.busy = false;
      refresh?.();
    }
  }

  function candidatePicker(context, state, options = {}) {
    const available = Array.isArray(options.items) ? options.items : catalogItems(state);
    const factorAlias = value => FTTestFactorSelection.factorAlias(value);
    const pickerRows = () => available.map(item => {
      const id = factorID(item);
      return {
        value: id,
        label: factorAlias(item) || id,
        description: FTTestFactorCandidates.sourceDescription(context, state, item),
        factor: item,
        view: window.FTFactorDetailShared?.factorRowView?.(item)
          || {kind: "factor", ref: id},
      };
    }).filter(item => item.value);
    let picker;
    const saved = value => {
      if (!value) return;
      const id = factorID(value);
      if (!id) return;
      const stateIndex = (state.factors || []).findIndex(item => (
        factorID(item) === id
      ));
      const next = stateIndex >= 0 ? {...state.factors[stateIndex], ...value} : value;
      if (stateIndex >= 0) state.factors[stateIndex] = next;
      else (state.factors ||= []).push(next);
      const availableIndex = available.findIndex(item => (
        factorID(item) === id
      ));
      if (availableIndex >= 0) available[availableIndex] = next; else available.push(next);
      picker?.setItems(pickerRows());
      const values = options.multi
        ? [...new Set([...(picker?.values || []), id])]
        : [id];
      picker?.setValues(values);
      options.onChange?.(values);
    };
    picker = FTTestObjectPicker.create(context, {
      title: context.t(options.title || "因子候选"),
      compact: true,
      items: pickerRows(),
      selected: options.selected || [],
      multi: options.multi === true,
      name: options.name || "test-factor-candidates",
      loading: options.loading === true,
      loadingText: context.t(options.loadingText || "正在读取因子候选…"),
      errorText: options.errorText || state.lazy?.factors?.error || "",
      onCreate: context.session && options.canCreate !== false ? () => void (
        window.FTStrategyEditorFactorOverlay?.open
          ? FTStrategyEditorFactorOverlay.open(context, state, saved)
          : FTTestLazyCode.openObjectEditor(context, {
            kind: "factor", mode: "create", ref: "new", onSaved: saved,
            testState: state, temporary: true,
          })
      ) : null,
      createLabel: context.t("新建因子"),
      editSelected: item => item.factor?.temporary === true
        || item.factor?.source_kind === "transient",
      onEdit: (_event, item) => void FTTestLazyCode.openObjectEditor(context, {
        kind: "factor", mode: "edit", ref: item.value,
        onSaved: saved, testState: state, initialValue: item.factor,
        temporary: true,
      }),
      editLabel: context.t("编辑因子"),
      itemActions: item => {
        const factor = available.find(value => (
          factorID(value) === item.value
        ));
        if (!context.session || !factor?.can_edit || factor.is_public) return [];
        return [{
          label: context.t("编辑"),
          title: context.t("在当前浮层编辑因子"),
          buttonClass: "secondary",
          onClick: event => {
            event?.preventDefault();
            void FTTestLazyCode.openObjectEditor(context, {
              kind: "factor", mode: "edit", ref: item.value,
              onSaved: saved, testState: state, initialValue: factor,
              temporary: factor.temporary === true,
            });
          },
        }];
      },
      onChange: values => options.onChange?.(values),
    });
    return picker;
  }

  function helpFor(context, state, key) {
    return window.FTTestFieldHelp?.forField?.(
      state.manifest, key, context,
    ) || "";
  }

  function candidateHeading(context, state, control, options = {}) {
    return FTTestFieldRow.create(
      options.label || context.t("因子候选"),
      controlElement(control),
      options.help || helpFor(context, state, "factor_candidates"),
      {className: "test-factor-candidate-heading-row"},
    );
  }

  // The nested strategy editor uses the same candidate surface as the outer
  // factor tab.  Only the candidate control and the optional combination
  // control are supplied by the strategy form; row structure, help icons,
  // hierarchy classes, and the override content wrapper stay shared here.
  function innerPanel(context, state, _refresh, options = {}) {
    const root = document.createElement("div");
    root.className = "test-factor-candidate-sources test-factor-candidate-sources-inner";
    root.append(candidateHeading(context, state, options.candidateControl, {
      label: options.candidateLabel,
      help: options.candidateHelp,
    }));
    const dependent = document.createElement("div");
    dependent.className = "test-factor-candidate-dependent-fields";
    root.append(dependent);
    const update = next => {
      dependent.replaceChildren();
      if (next.combinationVisible && next.combinationControl) {
        const row = FTTestFieldRow.create(
          next.combinationLabel || context.t("组合方式"),
          controlElement(next.combinationControl),
          next.combinationHelp || context.t("多个因子候选需要一种组合方式"),
          {className: "factor-candidate-child-row"},
        );
        if (next.combinationEmpty) {
          const empty = document.createElement("small");
          empty.className = "backtest-group-empty-combination-mode";
          empty.textContent = next.combinationEmpty;
          row.querySelector(".test-field-row-control")?.append(empty);
        }
        dependent.append(row);
      }
      if (next.overrideContent) root.append(next.overrideContent);
    };
    root.update = update;
    update(options);
    return root;
  }

  function panel(context, state, refresh, options = {}) {
    const root = document.createElement("div");
    root.className = "test-factor-candidate-sources";
    let direct = null;
    const refreshPanel = () => {
      direct?.setStatus?.({errorText: state.factorSetCatalog?.error || ""});
      refresh?.();
    };
    // The candidate field is the shared multi-select itself. Its closed
    // summary and checked menu rows are the only selected-object rendering in
    // Factor Execution; callers must not duplicate that state beside it.
    direct = combinedControl(context, state, refreshPanel);
    root.append(candidateHeading(context, state, direct));
    const roleField = options.includeRoles === false
      ? null : state.manifest?.defaults?.factor_role_bindings;
    if (roleField && FTSettingRules.isVisible(roleField, state.values)
      && window.FTTestFactorRoles?.section) {
      root.append(FTTestFactorRoles.section({
        context,
        manifest: state.manifest,
        field: roleField,
        fieldKey: "factor_role_bindings",
        values: state.values,
        value: FTSettingRules.valueFor(
          "factor_role_bindings", roleField, state.values,
        ),
        disabled: !FTSettingRules.isEditable(roleField, state.values),
        onChange: next => {
          FTSettingRules.setValue(
            state.manifest, state.values, "factor_role_bindings", roleField, next,
          );
          refresh?.();
        },
      }));
    }
    return root;
  }

  function scopedSourceState(state, owner, initial = {}) {
    let local = owner && typeof owner === "object"
      ? scopedSourceStates.get(owner) : null;
    if (!local) {
      const wanted = new Set((initial.factor_candidate_refs || []).map(String));
      const available = new Map([
        ...catalogItems(state),
        ...(initial.factor_candidates || []),
        ...(initial.factor_source_selections || []),
      ].filter(item => item?.schema_version === 2 && factorID(item))
        .map(item => [factorID(item), item]));
      const candidates = [...available.values()].filter(item => wanted.has(factorID(item)));
      const direct = Array.isArray(initial.factor_source_selections)
        ? structuredClone(initial.factor_source_selections)
        : candidates.filter(item => !(item.factor_set_refs || []).length);
      local = {
        ...state,
        catalogSourceState: state,
        values: {
          ...(state.values || {}),
          factor_candidates: structuredClone(candidates),
          factor_source_selections: direct,
          factor_set_selections: structuredClone(initial.factor_set_selections || []),
          factor_role_bindings: structuredClone(initial.factor_role_bindings || {}),
        },
      };
      if (owner && typeof owner === "object") scopedSourceStates.set(owner, local);
    }
    local.manifest = state.manifest;
    local.catalogSourceState = state;
    local.factorSetCatalog = state.factorSetCatalog;
    local.lazy = state.lazy;
    return local;
  }

  function scopedSourceSnapshot(state) {
    const candidates = FTTestFactorSelection.candidates(state);
    return {
      factor_candidate_refs: candidates.map(factorID).filter(Boolean),
      factor_candidates: candidates,
      factor_source_selections: structuredClone(selections(state)),
      factor_set_selections: structuredClone(
        window.FTTestFactorSets?.selections?.(state) || [],
      ),
    };
  }

  function retainScopedSources(owner, source) {
    if (!source) return;
    const records = new Map((owner.savedFactors || []).map(item => [factorID(item), item]));
    for (const item of FTTestFactorSelection.candidates(source)) {
      if (factorID(item)) records.set(factorID(item), structuredClone(item));
    }
    // Persist the records a submitted inner group refers to, independently
    // of the asynchronously replaced visible catalog array.
    owner.savedFactors = [...records.values()];
  }

  function scopedSourcePanel(context, state, refresh, options = {}) {
    const root = panel(context, state, refresh, {includeRoles: false});
    root.classList.add("test-factor-candidate-sources-scoped");
    if (options.combinationVisible && options.combinationControl) {
      const row = FTTestFieldRow.create(
        options.combinationLabel || context.t("组合方式"),
        controlElement(options.combinationControl),
        options.combinationHelp || context.t("多个因子候选需要一种组合方式"),
        {className: "factor-candidate-child-row"},
      );
      if (options.combinationEmpty) {
        const empty = document.createElement("small");
        empty.className = "backtest-group-empty-combination-mode";
        empty.textContent = options.combinationEmpty;
        row.querySelector(".test-field-row-control")?.append(empty);
      }
      root.append(row);
    }
    // Factor mode, warmup mode/window and other registered overrides are
    // peers of the candidate field. They must never inherit candidate-child
    // indentation merely because they share the Factor Execution tab.
    if (options.overrideContent) root.append(options.overrideContent);
    return root;
  }

  window.FTTestFactorCandidateSources = Object.freeze({
    candidateHeading, candidatePicker, innerPanel, panel,
    scopedSourcePanel, scopedSourceSnapshot, scopedSourceState, retainScopedSources,
    selections, syncCandidates,
  });
})();
