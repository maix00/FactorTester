(() => {
  function normalize(state) {
    state.analysis = state.analysis && typeof state.analysis === "object"
      ? state.analysis : {};
    state.analysis.groups = Array.isArray(state.analysis.groups)
      ? state.analysis.groups : [];
    state.analysis.ls_configs = Array.isArray(state.analysis.ls_configs)
      ? state.analysis.ls_configs : [];
    const groupsByID = new Map(state.analysis.groups.map(group => [group.id, group]));
    const resolveBatch = (group, seen = new Set()) => {
      if (group.batchId) return group.batchId;
      if (!group.parentId || seen.has(group.id)) {
        group.batchId = `batch:${group.id}`;
        return group.batchId;
      }
      const parent = groupsByID.get(group.parentId);
      if (!parent) {
        group.batchId = `batch:${group.id}`;
        return group.batchId;
      }
      const nextSeen = new Set(seen); nextSeen.add(group.id);
      group.batchId = resolveBatch(parent, nextSeen);
      return group.batchId;
    };
    state.analysis.groups.forEach(group => {
      resolveBatch(group);
      // Remove deprecated display-only aliases without making them part of
      // the authoring or execution schema again.
      removeDeprecatedDisplayMetadata(group);
      group.override_mounted_tabs = window.FTTestConfigurationCompiler?.authoringItemMountedTabs
        ? FTTestConfigurationCompiler.authoringItemMountedTabs(
          state.manifest, group, group.override_mounted_tabs,
        )
        : ["__strategy__", "factor", "product_path_selection"];
      if (!group.name) group.name = defaultName(group.batchId, group.id);
    });
    state.analysis.ls_configs.forEach(item => {
      removeDeprecatedDisplayMetadata(item);
      item.override_mounted_tabs = window.FTTestConfigurationCompiler?.authoringItemMountedTabs
        ? FTTestConfigurationCompiler.authoringItemMountedTabs(
          state.manifest, item, item.override_mounted_tabs,
        )
        : ["__strategy__", "factor", "product_path_selection"];
      if (!item.batchId) item.batchId = `batch:${item.id || "long-short"}`;
      if (!item.name) item.name = defaultName(item.batchId, item.id);
    });
    const batchIDs = new Set([
      ...state.analysis.groups.map(group => group.batchId),
      ...state.analysis.ls_configs.map(item => item.batchId),
    ]);
    const numericBatchIDs = [...batchIDs]
      .map(value => /^batch:(\d+)$/.exec(String(value))?.[1])
      .filter(Boolean).map(Number);
    const inferredSequence = numericBatchIDs.length ? Math.max(...numericBatchIDs) : 0;
    state.backtestBatchSequence = Number.isInteger(state.backtestBatchSequence)
      ? Math.max(state.backtestBatchSequence, inferredSequence) : inferredSequence;
    state.selectedBacktestGroupIDs = Array.isArray(state.selectedBacktestGroupIDs)
      ? state.selectedBacktestGroupIDs : [];
    state.selectedBacktestLongShortIDs = Array.isArray(state.selectedBacktestLongShortIDs)
      ? state.selectedBacktestLongShortIDs : [];
    return state.analysis;
  }

  function nextID(state) {
    normalize(state);
    state.backtestBatchSequence += 1;
    const existing = new Set([
      ...state.analysis.groups.map(group => group.batchId),
      ...state.analysis.ls_configs.map(item => item.batchId),
    ]);
    while (existing.has(`batch:${state.backtestBatchSequence}`)) state.backtestBatchSequence += 1;
    return `batch:${state.backtestBatchSequence}`;
  }

  function defaultName(batchId, strategyId) {
    const batch = String(batchId || "batch:?").trim() || "batch:?";
    const strategy = String(strategyId || "strategy:?").trim() || "strategy:?";
    return `${batch}/${strategy}`;
  }

  function removeDeprecatedDisplayMetadata(item) {
    Object.keys(item || {}).forEach(key => {
      const normalized = String(key).replace(/[_-]/g, "").toLocaleLowerCase();
      if (normalized.startsWith("short") && normalized.endsWith("alias")) delete item[key];
    });
  }

  function uniqueName(state, requested, exceptID = "") {
    const name = String(requested || "").trim();
    if (!name) throw new Error("策略名称不能为空");
    if (hasName(state, name, exceptID)) throw new Error(`策略名称已存在: ${name}`);
    return name;
  }

  function hasName(state, requested, exceptID = "") {
    const name = String(requested || "").trim().toLocaleLowerCase();
    const values = [
      ...(state.analysis?.groups || []), ...(state.analysis?.ls_configs || []),
    ];
    return values.some(item => item.id !== exceptID
      && String(item.name || "").trim().toLocaleLowerCase() === name);
  }

  function groupBatches(state, find, rootsAndChildren) {
    normalize(state);
    const batches = new Map();
    const roots = new Map();
    for (const group of state.analysis.groups) {
      let root = group;
      const seen = new Set();
      while (root.parentId && !seen.has(root.id)) {
        seen.add(root.id);
        root = find(state, root.parentId) || root;
      }
      roots.set(group.id, root);
    }
    for (const item of rootsAndChildren(state)) {
      const root = roots.get(item.group.id) || item.group;
      // The visible list is a hierarchy: descendants stay beneath their root
      // strategy even though each authoring event retains its own batchId for
      // execution metadata. Runtime execution still uses each item's frozen
      // config and does not depend on this presentation grouping.
      const key = root.batchId || item.group.batchId || `batch:${root.id}`;
      if (!batches.has(key)) {
        batches.set(key, {key, root, order: batches.size + 1, items: []});
      }
      batches.get(key).items.push({...item, rootId: root.id});
    }
    return [...batches.values()];
  }

  window.FTBacktestGroupBatches = Object.freeze({
    defaultName, groupBatches, nextID, normalize, uniqueName,
  });
})();
