(() => {
  function lazyState() {
    return Object.fromEntries([
      "factors", "products", "categories", "templates", "outputs", "profiles",
      "run_inputs",
    ].map(key => [key, {status: "idle", error: "", promise: null}]));
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
    state.families = [...(Array.isArray(state.savedFamilies) ? state.savedFamilies : [])];
    const storedGroups = [
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
    state.savedFamilies = Array.isArray(payload.shared?.factor_families)
      ? structuredClone(payload.shared.factor_families) : [];
    state.factorRef = state.savedFactors[0]?.factor_ref || "";
    state.groupRefs = window.FTTestProducts?.restoreReferences
      ? FTTestProducts.restoreReferences(state.analysis, payload.ui?.[state.kind] || {})
      : FTTestLazyCode.fallbackGroupReferences(state.analysis, payload.ui?.[state.kind] || {});
    state.groupRef = state.groupRefs[0] || "";
    const savedOutputs = payload.ui?.[state.kind]?.output_requests;
    state.outputRequestsExplicit = Array.isArray(savedOutputs);
    state.outputRequests = Array.isArray(savedOutputs) ? [...savedOutputs] : [];
  }

  function restoreWorkspace(state) {
    const key = localStorage.getItem(`ft-${state.kind}-workspace`) || "";
    if (!state.workspace || state.workspace.workspace_id !== key) {
      state.workspace = state.workspaces.find(item => item.workspace_id === key) || null;
    }
    applyWorkspaceConfiguration(state);
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
    applyWorkspaceConfiguration, lazyState,
    mergeByID, restoreWorkspace, savedMountedTabs, savedSettings,
    seedSavedCatalogs,
  });
})();
