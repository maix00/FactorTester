(() => {
  function prepare(state) {
    state.values.factor_candidates = FTTestFactorSelection.candidates(state);
    FTTestFactorSelection.restoreFrozenSelections(state);
    FTTestFactorSelection.syncSelection(state);
    FTTestFactorSets.prepare(state);
  }

  async function initialize(context, state) {
    prepare(state);
    await FTTestFactorSets.initialize(context, state);
  }

  function panel(context, state, refresh, _contentOptions = {}) {
    const root = document.createElement("div"); root.className = "test-factor-builder";
    root.append(FTTestFactorCandidateSources.panel(context, state, refresh));
    return root;
  }

  function selectedFactor(state) { return FTTestFactorSelection.selectedFactor(state); }
  function selectedFamily(state, factor) { return FTTestFactorSelection.selectedFamily(state, factor); }

  window.FTTestFactors = {initialize, panel, prepare, selectedFactor, selectedFamily};
})();
