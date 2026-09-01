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
      loading: FTTestObjectPicker.lazyLoading(state, "factors"),
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
      onCreate: context.session && options.canCreate !== false ? () => void (
        window.FTStrategyEditorFactorOverlay?.open
          ? FTStrategyEditorFactorOverlay.open(context, state, saved)
          : FTTestLazyCode.openObjectEditor(context, {
            kind: "factor", mode: "create", ref: "new", onSaved: saved,
            testState: state, temporary: true,
          })
      ) : null,
      createLabel: context.t("新建因子"),
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
    root.append(candidateHeading(
      context, state, FTTestFactorCandidates.summaryControl(context, state),
    ));
    const sets = FTTestFactorSets.control(context, state, refresh);
    if (sets) root.append(FTTestFieldRow.create(
      context.t("因子集合"), sets,
      helpFor(context, state, "factor_set_selections"),
      {className: "factor-candidate-child-row"},
    ));
    const direct = directControl(context, state, refresh);
    direct.classList.add("factor-candidate-child-row");
    root.append(direct);
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
      const candidates = catalogItems(state).filter(item => wanted.has(factorID(item)));
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
    scopedSourcePanel, scopedSourceSnapshot, scopedSourceState,
    selections, syncCandidates,
  });
})();
