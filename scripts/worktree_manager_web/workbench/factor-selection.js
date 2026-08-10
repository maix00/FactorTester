(() => {
  function candidates(state) {
    return Array.isArray(state.values?.factor_candidates)
      ? state.values.factor_candidates.filter(item => item && typeof item === "object") : [];
  }

  function factorID(value) {
    return value?.factor_ref || value?.target_ref || value?.alias || value?.factor_alias || "";
  }

  function factorAlias(value) {
    return value?.factor_alias || value?.alias || value?.name || value?.factor_ref || "";
  }

  function addCandidate(state, value) {
    if (!value || typeof value !== "object" || !factorID(value)) return;
    const rows = candidates(state);
    const index = rows.findIndex(item => factorID(item) === factorID(value));
    const candidate = {...value, factor_alias: factorAlias(value)};
    if (index >= 0) rows[index] = candidate; else rows.push(candidate);
    state.values.factor_candidates = rows;
    if (state.kind === "ic") {
      const selected = selectedIDs(state);
      if (!selected.includes(factorID(candidate))) selected.push(factorID(candidate));
      state.values.factor_selections = rows.filter(item => selected.includes(factorID(item)));
    } else {
      state.values.factor = factorAlias(candidate);
    }
    state.factorRef = factorID(candidate);
  }

  function removeCandidate(state, factor) {
    const id = factorID(factor);
    state.values.factor_candidates = candidates(state).filter(item => factorID(item) !== id);
    if (state.kind === "ic") {
      state.values.factor_selections = (state.values.factor_selections || [])
        .filter(item => factorID(item) !== id);
    } else if (state.values.factor === factorAlias(factor)) {
      state.values.factor = "";
    }
    if (state.factorRef === id) state.factorRef = "";
  }

  function setSelected(state, factor, checked) {
    if (state.kind === "ic") {
      const selected = new Set(selectedIDs(state));
      if (checked) selected.add(factorID(factor)); else selected.delete(factorID(factor));
      state.values.factor_selections = candidates(state).filter(item => selected.has(factorID(item)));
      state.factorRef = factorID(state.values.factor_selections[0] || {}) || "";
    } else {
      state.values.factor = checked ? factorAlias(factor) : "";
      state.factorRef = checked ? factorID(factor) : "";
    }
  }

  function isSelected(state, factor) {
    if (state.kind === "ic") return selectedIDs(state).includes(factorID(factor));
    return state.values.factor === factorAlias(factor) || state.factorRef === factorID(factor);
  }

  function selectedIDs(state) {
    return (Array.isArray(state.values.factor_selections) ? state.values.factor_selections : [])
      .map(item => typeof item === "string" ? item : factorID(item)).filter(Boolean);
  }

  function syncSelection(state) {
    const rows = candidates(state);
    if (state.factorRef && rows.some(item => factorID(item) === state.factorRef)) return;
    if (state.kind === "ic") {
      state.factorRef = factorID((state.values.factor_selections || [])[0] || {}) || "";
    } else {
      const alias = state.values.factor || "";
      state.factorRef = factorID(rows.find(item => factorAlias(item) === alias) || {}) || state.factorRef;
    }
  }

  function restoreFrozenSelections(state) {
    const restored = [];
    if (state.factorRef) {
      const selected = state.factors.find(item => factorID(item) === state.factorRef);
      if (selected) restored.push(selected);
    }
    if (Array.isArray(state.values.factor_selections)) {
      restored.push(...state.values.factor_selections.filter(item => (
        item && typeof item === "object"
      )));
    }
    for (const factor of restored) addCandidate(state, factor);
  }

  function selectedFactor(state) {
    return candidates(state).find(item => factorID(item) === state.factorRef)
      || state.factors.find(item => factorID(item) === state.factorRef);
  }

  function selectedFamily(state, factor = null) {
    const ref = factor?.family_ref || factor?.factor_family_ref || state.values.factor_family_ref;
    const loaded = state.factorCatalog?.selectedFamily;
    if (loaded && (!factor || loaded.family_ref === ref)) return loaded;
    const registered = state.families.find(item => [
      item.family_ref, item.alias, item.factor_family_alias,
    ].includes(ref || factor?.family || factor?.factor_family_alias));
    if (registered) return registered;
    if (factor?.family || factor?.factor_family_alias) return {
      family: factor.family || factor.factor_family_alias,
      family_ref: ref || "",
    };
    return null;
  }

  window.FTTestFactorSelection = Object.freeze({
    candidates, factorID, factorAlias, addCandidate, removeCandidate,
    setSelected, isSelected, selectedIDs,
    syncSelection, restoreFrozenSelections,
    selectedFactor, selectedFamily,
  });
})();
