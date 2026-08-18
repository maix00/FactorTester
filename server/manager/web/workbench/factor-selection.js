(() => {
  function candidates(state) {
    return Array.isArray(state.values?.factor_candidates)
      ? state.values.factor_candidates.filter(item => item && typeof item === "object") : [];
  }

  function factorID(value) {
    return value?.factor_ref || value?.target_ref || value?.alias || value?.factor_alias
      || value?.id || value?.name || "";
  }

  function factorAlias(value) {
    return value?.factor_alias || value?.alias || value?.name || value?.factor_ref || "";
  }

  function addCandidate(state, value, options = {}) {
    if (!value || typeof value !== "object" || !factorID(value)) return;
    const rows = candidates(state);
    const index = rows.findIndex(item => factorID(item) === factorID(value));
    const existing = index >= 0 ? rows[index] : {};
    const sourceSets = [...new Set([
      ...(existing.factor_set_refs || []), ...(value.factor_set_refs || []),
    ].filter(Boolean))];
    const setOnly = index >= 0
      ? Boolean(existing.factor_set_only) && Boolean(value.factor_set_only)
      : Boolean(value.factor_set_only);
    const metadata = window.FTFactorModel?.sourceMetadata?.(value) || {};
    const candidate = {
      ...existing, ...value,
      ...(metadata.factor_owner_ref
        ? {factor_owner_ref: metadata.factor_owner_ref} : {}),
      ...(metadata.factor_family_ref
        ? {factor_family_ref: metadata.factor_family_ref} : {}),
      ...(metadata.factor_params !== undefined
        && (value.factor_params !== undefined || value.params !== undefined)
        ? {factor_params: metadata.factor_params} : {}),
      ...(metadata.factor_git_commit
        ? {factor_git_commit: metadata.factor_git_commit} : {}),
      factor_alias: factorAlias(value),
      ...(sourceSets.length ? {factor_set_refs: sourceSets} : {}),
      ...(setOnly ? {factor_set_only: true} : {}),
    };
    if (!candidate.factor_git_commit) delete candidate.factor_git_commit;
    // Keep the unprefixed names for the execution adapter, while the
    // prefixed fields are the per-factor source metadata used by the UI and
    // RunSpec authoring contract.
    if (candidate.factor_owner_ref && !candidate.owner_ref) {
      candidate.owner_ref = candidate.factor_owner_ref;
    }
    if (candidate.factor_family_ref && !candidate.family_ref) {
      candidate.family_ref = candidate.factor_family_ref;
    }
    if (candidate.factor_params !== undefined && candidate.params === undefined) {
      candidate.params = candidate.factor_params;
    }
    if (candidate.factor_git_commit && !candidate.git_commit) {
      candidate.git_commit = candidate.factor_git_commit;
    }
    if (!setOnly) delete candidate.factor_set_only;
    if (index >= 0) rows[index] = candidate; else rows.push(candidate);
    state.values.factor_candidates = rows;
    if (state.kind === "ic") {
      const selected = selectedIDs(state);
      if (!selected.includes(factorID(candidate))) selected.push(factorID(candidate));
      state.values.factor_selections = rows.filter(item => selected.includes(factorID(item)));
    } else {
      // `select: false` means “do not make this newly added row preferred”;
      // it does not disable the automatic scalar primary selection.
      autoSelectPrimary(state, options.select === false ? null : candidate);
    }
    if (state.kind === "ic") state.factorRef = factorID(candidate);
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
    for (const factor of restored) addCandidate(state, factor, {select: false});
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
    const ref = factor?.factor_family_ref || factor?.family_ref;
    const registered = (state.families || []).find(item => [
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
    candidates, factorID, factorAlias, addCandidate, autoSelectPrimary,
    removeCandidate, detachFactorSet,
    setSelected, setSelectedIDs, isSelected, selectedIDs,
    syncSelection, restoreFrozenSelections,
    selectedFactor, selectedFactors, selectedFamily,
  });
})();
