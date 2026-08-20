(() => {
  function lazyState() {
    return Object.fromEntries([
      "factors", "products", "categories", "templates", "outputs", "profiles",
      "run_inputs",
    ].map(key => [key, {status: "idle", error: "", promise: null}]));
  }

  function initializeInputState(state) {
    if (!Array.isArray(state.transientFactorSources)) state.transientFactorSources = [];
    if (!Array.isArray(state.transientFactorFamilies)) state.transientFactorFamilies = [];
    if (!Array.isArray(state.transientStrategySources)) state.transientStrategySources = [];
    if (!Array.isArray(state.strategySpecs)) state.strategySpecs = [];
    if (!Array.isArray(state.strategyInspections)) state.strategyInspections = [];
    if (!Array.isArray(state.runInputDependencies)) state.runInputDependencies = [];
    state.runInputStatus = state.runInputStatus || {busy: false, error: ""};
    return state;
  }

  function mergeByID(existing, incoming) {
    const result = new Map();
    for (const item of [...(existing || []), ...(incoming || [])]) {
      const id = item?.factor_ref || item?.target_ref || item?.family_ref
        || item?.group_ref || item?.product_group_ref || item?.id;
      if (id) result.set(String(id), item);
    }
    return [...result.values()];
  }

  function seedSavedCatalogs(state) {
    state.factors = [...(Array.isArray(state.savedFactors) ? state.savedFactors : [])];
    state.families = [];
    const storedGroups = [
      ...(Array.isArray(state.savedTemporaryObjects?.product_groups)
        ? state.savedTemporaryObjects.product_groups : []),
      ...(Array.isArray(state.analysis.product_path_selections)
        ? state.analysis.product_path_selections : []),
      state.analysis.product_path_selection,
      ...Object.values(state.analysis.product_selections || {}),
    ].filter(Boolean);
    const byID = new Map();
    for (const group of storedGroups) {
      const id = FTTestLazyCode.groupID(group);
      if (id) byID.set(id, group);
    }
    for (const id of state.groupRefs || []) {
      if (!byID.has(id)) byID.set(id, {
        group_ref: id, title_zh: id, paths: [], selected_paths: [],
        _savedPlaceholder: true,
      });
    }
    state.groups = [...byID.values()];
    state.savedGroupIDs = new Set(state.groups.map(group => FTTestLazyCode.groupID(group)));
  }

  function applyWorkspaceConfiguration(state) {
    const payload = state.workspace?.configuration?.payload || {};
    state.analysis = structuredClone(payload.analyses?.[state.kind] || {});
    state.savedFactors = Array.isArray(payload.shared?.factors)
      ? structuredClone(payload.shared.factors) : [];
    state.savedTemporaryObjects = payload.shared?.temporary_objects
      && typeof payload.shared.temporary_objects === "object"
      ? structuredClone(payload.shared.temporary_objects) : {};
    state.factorRef = state.savedFactors[0]?.factor_ref || "";
    state.groupRefs = window.FTTestProducts?.restoreReferences
      ? FTTestProducts.restoreReferences(state.analysis, payload.ui?.[state.kind] || {})
      : FTTestLazyCode.fallbackGroupReferences(state.analysis, payload.ui?.[state.kind] || {});
    state.groupRef = state.groupRefs[0] || "";
    const savedOutputs = payload.ui?.[state.kind]?.output_requests;
    state.outputRequestsExplicit = Array.isArray(savedOutputs);
    state.outputRequests = Array.isArray(savedOutputs) ? [...savedOutputs] : [];
    restoreTemporaryObjects(state);
  }

  function restoreTemporaryObjects(state) {
    const saved = state.savedTemporaryObjects || {};
    const copy = key => Array.isArray(saved[key]) ? structuredClone(saved[key]) : [];
    state.transientFactorSources = copy("factor_sources");
    state.transientFactorFamilies = copy("factor_families");
    state.transientStrategySources = copy("strategy_sources");
    state.strategySpecs = copy("strategy_specs");
    state.strategyInspections = copy("strategy_inspections");
    state.runInputDependencies = copy("run_input_dependencies");
    if (!state.values) return;
    state.values.factor_candidates = mergeByID(
      state.values.factor_candidates || [], copy("factors"),
    );
    state.values.category_candidates = mergeByID(
      state.values.category_candidates || [], copy("categories"),
    );
  }

  function restoreWorkspace(state) {
    const key = localStorage.getItem(`ft-${state.kind}-workspace`) || "";
    if (!state.workspace || state.workspace.workspace_id !== key) {
      state.workspace = state.workspaces.find(item => item.workspace_id === key) || null;
    }
    applyWorkspaceConfiguration(state);
  }

  function defaultRunValues(manifest) {
    const values = {};
    for (const item of manifest?.run_fields || []) {
      if (item.placement !== "outputs") values[item.key] = structuredClone(item.default);
    }
    return values;
  }

  function clearDraft(state) {
    state.workspace = null;
    try { localStorage.removeItem(`ft-${state.kind}-workspace`); } catch (_) {}
    state.analysis = {};
    state.savedFactors = [];
    state.savedTemporaryObjects = {};
    state.factorRef = "";
    state.groupRef = "";
    state.groupRefs = [];
    state.values = null;
    state.settingsInitialized = false;
    state.settingsMountedTabs = [];
    state.settingsTabKey = "";
    state.transientFactorSources = [];
    state.transientFactorFamilies = [];
    state.transientStrategySources = [];
    state.strategySpecs = [];
    state.strategyInspections = [];
    state.runInputDependencies = [];
    state.runInputStatus = {busy: false, error: ""};
    state.outputRequests = [];
    state.outputRequestsExplicit = false;
    state.testRunBatch = [];
    state.activeRunGroupID = "";
    state.selectedBacktestGroupIDs = [];
    state.selectedBacktestLongShortIDs = [];
    state.backtestExpandedBatches = {};
    state.backtestGroupEditor = null;
    state.backtestGroupsOpen = false;
    state.runValues = defaultRunValues(state.manifest);
    return state;
  }

  const draftKeys = Object.freeze([
    "analysis", "savedFactors", "savedTemporaryObjects",
    "factorRef", "groupRef", "groupRefs", "values",
    "settingsTabKey", "settingsMountedTabs", "outputRequests",
    "outputRequestsExplicit", "runValues", "transientFactorSources",
    "transientFactorFamilies", "transientStrategySources", "strategySpecs",
    "strategyInspections", "runInputDependencies", "selectedBacktestGroupIDs",
    "selectedBacktestLongShortIDs", "backtestExpandedBatches",
  ]);

  function draftSnapshot(state) {
    const values = {};
    for (const key of draftKeys) values[key] = structuredClone(state[key]);
    return {schemaVersion: 1, kind: state.kind, values};
  }

  function restoreDraft(state, snapshot) {
    if (snapshot?.schemaVersion !== 1 || snapshot.kind !== state.kind
        || !snapshot.values || typeof snapshot.values !== "object") return false;
    for (const key of draftKeys) {
      if (key in snapshot.values) state[key] = structuredClone(snapshot.values[key]);
    }
    state.settingsInitialized = false;
    return true;
  }

  function savedSettings(state) {
    const payload = state.workspace?.configuration?.payload || {};
    return payload.ui?.[state.kind]?.settings
      || state.analysis.local_settings || state.analysis.settings || {};
  }

  function savedMountedTabs(state) {
    const saved = state.workspace?.configuration?.payload?.ui?.[state.kind]?.mounted_tabs;
    return Array.isArray(saved) ? saved : undefined;
  }

  window.FTTestState = Object.freeze({
    applyWorkspaceConfiguration, clearDraft, defaultRunValues,
    draftSnapshot, restoreDraft,
    initializeInputState, lazyState,
    mergeByID, restoreWorkspace, savedMountedTabs, savedSettings,
    restoreTemporaryObjects, seedSavedCatalogs,
  });
})();
