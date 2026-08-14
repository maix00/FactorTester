(() => {
  function prepare(state) {
    if (state.factorCatalog?.prepared) return;
    state.factorCatalog = {
      native: Boolean(nativeHandler()), owners: [], revisions: [], families: [],
      selectedFamily: null, selectedFamilyEntry: null, selectedFamilyName: "",
      busy: false, error: "", prepared: true, initialized: false,
    };
    const selection = FTTestFactorSelection;
    state.values.factor_candidates = selection.candidates(state);
    selection.restoreFrozenSelections(state);
    selection.syncSelection(state);
    FTTestFactorSets.prepare(state);
  }

  async function initialize(context, state) {
    prepare(state);
    if (state.factorCatalog.initialized) return;
    state.factorCatalog.initialized = true;
    if (!state.factorCatalog.native) {
      restoreFamilyEntry(state);
      await FTTestFactorSets.initialize(context, state);
      return;
    }
    try {
      state.factorCatalog.owners = await nativeList("owners");
      if (!state.values.factor_owner_ref && state.factorCatalog.owners.length) {
        state.values.factor_owner_ref = state.factorCatalog.owners[0].owner_ref;
      }
      await loadRevisions(state);
    } catch (error) {
      state.factorCatalog.error = error.message;
    }
    await FTTestFactorSets.initialize(context, state);
  }

  function familyEntries(state) {
    return FTFactorFamilyPicker.entries({
      publicFamilies: state.families,
      localFamilies: state.factorCatalog.families,
      transientFamilies: state.transientFactorFamilies,
      ownerRef: state.values.factor_owner_ref,
      gitCommit: state.values.factor_git_commit,
    });
  }

  function familyButtonLabel(context, state) {
    const selected = state.factorCatalog.selectedFamilyEntry;
    if (!selected) return context.t("搜索并选择因子家族…");
    const labels = {
      local: "本地修订", public: "公共因子库", transient: "任务临时源码",
    };
    return `${selected.title} · ${context.t(labels[selected.sourceKind] || selected.sourceKind)}`;
  }

  async function selectFamily(context, state, entry, refresh) {
    const catalog = state.factorCatalog;
    catalog.selectedFamilyEntry = entry;
    catalog.selectedFamilyName = entry.family;
    if (entry.sourceKind === "transient") {
      catalog.selectedFamily = entry.familyMetadata || entry;
      state.values.factor_family_ref = "";
      state.values.factor_params = defaultParameters(catalog.selectedFamily);
      refresh();
      return;
    }
    if (entry.sourceKind === "local") {
      await update(context, state, refresh, () => loadFamily(state));
      return;
    }
    catalog.selectedFamily = null;
    state.values.factor_family_ref = entry.familyRef;
    state.values.factor_params = {};
    refresh();
  }

  async function loadRevisions(state) {
    const catalog = state.factorCatalog;
    catalog.revisions = state.values.factor_owner_ref
      ? await nativeList("revisions", {owner_ref: state.values.factor_owner_ref, limit: 50}) : [];
    if (!catalog.revisions.some(item => item.git_commit === state.values.factor_git_commit)) {
      state.values.factor_git_commit = catalog.revisions[0]?.git_commit || "";
    }
    await loadFamilies(state);
  }

  async function loadFamilies(state) {
    const catalog = state.factorCatalog;
    catalog.families = state.values.factor_owner_ref && state.values.factor_git_commit
      ? await nativeList("families", {
        owner_ref: state.values.factor_owner_ref,
        git_commit: state.values.factor_git_commit,
      }) : [];
    restoreFamilyEntry(state);
    await loadFamily(state);
  }

  function restoreFamilyEntry(state) {
    const catalog = state.factorCatalog;
    if (catalog.selectedFamilyEntry) return;
    const selection = FTTestFactorSelection;
    const current = selection.candidates(state)
      .find(item => selection.factorID(item) === state.factorRef) || selection.selectedFactor(state);
    const entries = familyEntries(state);
    const exact = entries.find(item => (
      item.factor_refs?.includes(selection.factorID(current))
      || item.familyRef === current?.family_ref
      || item.familyRef === current?.factor_family_ref
    ));
    const currentSource = current?.source_kind === "transient"
      ? "transient" : current?.git_commit ? "local" : "public";
    const named = entries.find(item => item.sourceKind === currentSource
      && (item.family === current?.family || item.family === current?.factor_family_alias));
    catalog.selectedFamilyEntry = exact || named || null;
    catalog.selectedFamilyName = catalog.selectedFamilyEntry?.family || "";
  }

  async function loadFamily(state) {
    const catalog = state.factorCatalog;
    if (catalog.selectedFamilyEntry?.sourceKind === "transient") {
      catalog.selectedFamily = catalog.selectedFamilyEntry.familyMetadata
        || catalog.selectedFamilyEntry;
      state.values.factor_family_ref = "";
      return;
    }
    if (catalog.selectedFamilyEntry?.sourceKind === "public") {
      catalog.selectedFamily = null;
      state.values.factor_family_ref = catalog.selectedFamilyEntry.familyRef;
      state.values.factor_params = {};
      return;
    }
    if (!(state.values.factor_owner_ref && state.values.factor_git_commit
      && catalog.selectedFamilyName)) {
      catalog.selectedFamily = null;
      state.values.factor_family_ref = "";
      state.values.factor_params = {};
      return;
    }
    const previousRef = state.values.factor_family_ref;
    const value = await nativeRequest("family", {
      owner_ref: state.values.factor_owner_ref,
      git_commit: state.values.factor_git_commit,
      family: catalog.selectedFamilyName,
    });
    catalog.selectedFamily = value;
    state.values.factor_family_ref = value.family_ref || "";
    if (previousRef !== state.values.factor_family_ref) {
      state.values.factor_params = defaultParameters(value);
    }
  }

  function defaultParameters(family) {
    return Object.fromEntries((family?.params || []).map(item => (
      [item.alias, item.default_value ?? ""]
    )));
  }

  async function update(context, state, refresh, operation) {
    state.factorCatalog.busy = true;
    state.factorCatalog.error = "";
    refresh();
    try { await operation(); }
    catch (error) { state.factorCatalog.error = error.message; }
    finally { state.factorCatalog.busy = false; refresh(); }
  }

  function nativeHandler() {
    return window.webkit?.messageHandlers?.factorTesterLocalFactorSets;
  }

  async function nativeRequest(action, payload = {}) {
    const handler = nativeHandler();
    if (!handler?.postMessage) throw new Error("FTClient local factor catalog is unavailable");
    return await handler.postMessage({action, ...payload});
  }

  async function nativeList(action, payload = {}) {
    const value = await nativeRequest(action, payload);
    return Array.isArray(value) ? value : [];
  }

  window.FTTestFactorCatalog = Object.freeze({
    prepare, initialize, familyEntries, familyButtonLabel, selectFamily,
    loadRevisions, loadFamilies, loadFamily, restoreFamilyEntry,
    defaultParameters, update, nativeRequest, nativeList,
  });
})();
