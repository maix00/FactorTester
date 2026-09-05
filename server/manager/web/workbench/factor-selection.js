(() => {
  function candidates(state) {
    return Array.isArray(state.values?.factor_candidates)
      ? state.values.factor_candidates.filter(item => item && typeof item === "object") : [];
  }

  function factorID(value) {
    return value?.ref || "";
  }

  function factorAlias(value) {
    return value?.alias || "";
  }

  function addCandidate(state, value, options = {}) {
    addCandidates(state, [value], options);
  }

  function addCandidates(state, values, options = {}) {
    const rows = candidates(state);
    const byRef = new Map(rows.map((item, index) => [factorID(item), index]));
    const selected = new Set(selectedIDs(state));
    let last = null;
    for (const value of values || []) {
      if (!value || typeof value !== "object" || value.schema_version !== 2
          || !value.ref || !value.alias || !value.identity) continue;
      const index = byRef.get(factorID(value));
      const existing = index === undefined ? {} : rows[index];
      const sourceSets = [...new Set([
        ...(existing.factor_set_refs || []), ...(value.factor_set_refs || []),
      ].filter(Boolean))];
      const setOnly = index === undefined ? Boolean(value.factor_set_only)
        : Boolean(existing.factor_set_only) && Boolean(value.factor_set_only);
      const candidate = {...existing, ...value, ...(sourceSets.length ? {factor_set_refs: sourceSets} : {})};
      if (setOnly) candidate.factor_set_only = true; else delete candidate.factor_set_only;
      if (index === undefined) {
        byRef.set(factorID(value), rows.length);
        rows.push(candidate);
      } else rows[index] = candidate;
      selected.add(factorID(candidate));
      last = candidate;
    }
    if (!last) return;
    state.values.factor_candidates = rows;
    if (state.kind === "ic") {
      state.values.factor_selections = rows.filter(item => selected.has(factorID(item)));
      state.factorRef = factorID(last);
    } else {
      autoSelectPrimary(state, options.select === false ? null : last);
    }
  }

  // Backtest factor candidates form an outer, derived pool.  The legacy
  // scalar `factor` value remains part of the RunSpec contract, so keep it
  // synchronized automatically with the first available candidate instead
  // of exposing a second, conflicting selection control.
  function autoSelectPrimary(state, preferred = null) {
    const rows = candidates(state);
    if (!rows.length) {
      state.values.factor = "";
      state.factorRef = "";
      return;
    }
    const preferredID = factorID(preferred);
    const current = rows.find(item => factorID(item) === state.factorRef)
      || rows.find(item => factorAlias(item) === state.values.factor)
      || (preferredID ? rows.find(item => factorID(item) === preferredID) : null)
      || rows[0];
    state.values.factor = factorAlias(current);
    state.factorRef = factorID(current);
  }

  function removeCandidate(state, factor) {
    const id = factorID(factor);
    state.values.factor_candidates = candidates(state).filter(item => factorID(item) !== id);
    if (state.kind === "ic") {
      state.values.factor_selections = (state.values.factor_selections || [])
        .filter(item => factorID(item) !== id);
    } else {
      autoSelectPrimary(state);
    }
    if (state.factorRef === id) state.factorRef = "";
    if (state.kind !== "ic") autoSelectPrimary(state);
  }

  function detachFactorSet(state, targetRef) {
    const selected = new Set(selectedIDs(state));
    const rows = candidates(state).flatMap(factor => {
      const refs = (factor.factor_set_refs || []).filter(ref => ref !== targetRef);
      if (!refs.length && factor.factor_set_only) {
        selected.delete(factorID(factor));
        return [];
      }
      return [{...factor, factor_set_refs: refs}];
    });
    state.values.factor_candidates = rows;
    if (state.kind === "ic") {
      state.values.factor_selections = rows.filter(item => selected.has(factorID(item)));
    } else {
      autoSelectPrimary(state);
    }
    syncSelection(state);
  }

  function setSelected(state, factor, checked) {
    if (state.kind === "ic") {
      const selected = new Set(selectedIDs(state));
      if (checked) selected.add(factorID(factor)); else selected.delete(factorID(factor));
      state.values.factor_selections = candidates(state).filter(item => selected.has(factorID(item)));
      state.factorRef = factorID(state.values.factor_selections[0] || {}) || "";
    } else {
      autoSelectPrimary(state);
    }
  }

  function setSelectedIDs(state, values) {
    const wanted = new Set((values || []).map(String));
    const rows = candidates(state);
    if (state.kind === "ic") {
      state.values.factor_selections = rows.filter(item => wanted.has(factorID(item)));
      state.factorRef = factorID(state.values.factor_selections[0] || {}) || "";
    } else {
      autoSelectPrimary(state);
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
      autoSelectPrimary(state);
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
    addCandidates(state, restored, {select: false});
    if (state.kind !== "ic") autoSelectPrimary(state);
  }

  function selectedFactor(state) {
    return candidates(state).find(item => factorID(item) === state.factorRef)
      || state.factors.find(item => factorID(item) === state.factorRef);
  }

  function selectedFactors(state) {
    if (state.kind !== "ic") return [selectedFactor(state)].filter(Boolean);
    const selected = new Set(selectedIDs(state));
    return candidates(state).filter(item => selected.has(factorID(item)));
  }

  function selectedFamily(state, factor = null) {
    const selected = factor || selectedFactor(state);
    const familyRef = selected?.identity?.family_ref || "";
    const familyAlias = selected?.identity?.family_alias
      || selected?.family || selected?.factor_family_alias || "";
    const registered = (state.families || []).find(item => [
      item.ref, item.family_ref, item.alias, item.factor_family_alias,
    ].includes(familyRef) || [
      item.alias, item.family, item.factor_family_alias,
    ].includes(familyAlias));
    if (registered) return registered;
    if (familyAlias) return {ref: familyRef, alias: familyAlias};
    return null;
  }

  window.FTTestFactorSelection = Object.freeze({
    candidates, factorID, factorAlias, addCandidate, addCandidates, autoSelectPrimary,
    removeCandidate, detachFactorSet,
    setSelected, setSelectedIDs, isSelected, selectedIDs,
    syncSelection, restoreFrozenSelections,
    selectedFactor, selectedFactors, selectedFamily,
  });
})();
