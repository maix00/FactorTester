(() => {
  const structuralKeys = new Set([
    "id", "name", "parentId", "product_path_selection",
    "product_path_selection_id", "factorAlias", "splitCount", "groupIndex",
    "isAllGroups", "productMask", "needsRegenerate",
    "batchId", "override_mounted_tabs",
  ]);
  let sequence = 0;

  function identifier(prefix, requested = "") {
    if (requested) return requested;
    sequence += 1;
    return `${prefix}_${Date.now().toString(36)}_${sequence.toString(36)}`;
  }

  function initialize(state) {
    return FTBacktestGroupBatches.normalize(state);
  }

  function selected(state) {
    initialize(state);
    const wanted = new Set(state.selectedBacktestGroupIDs);
    return state.analysis.groups.filter(group => wanted.has(group.id));
  }

  function toggle(state, id, checked, selection = "multi") {
    initialize(state);
    if (selection === "single") {
      state.selectedBacktestGroupIDs = checked ? [id] : [];
      return;
    }
    const values = new Set(state.selectedBacktestGroupIDs);
    if (checked) values.add(id); else values.delete(id);
    state.selectedBacktestGroupIDs = [...values];
  }

  function selectedLongShort(state) {
    initialize(state);
    const wanted = new Set(state.selectedBacktestLongShortIDs);
    return state.analysis.ls_configs.filter(item => wanted.has(item.id));
  }

  function toggleLongShort(state, id, checked, selection = "multi") {
    initialize(state);
    if (selection === "single") {
      state.selectedBacktestLongShortIDs = checked ? [id] : [];
      return;
    }
    const values = new Set(state.selectedBacktestLongShortIDs);
    if (checked) values.add(id); else values.delete(id);
    state.selectedBacktestLongShortIDs = [...values];
  }

  function selectionID(value) {
    return FTTestProducts.groupID(value);
  }

  function groupLabel(group) {
    return group?.name || group?.id || "";
  }

  function addBaseBatch(state, draft) {
    initialize(state);
    const splitCount = positiveInteger(draft.splitCount, "splitCount");
    const groupIndex = positiveInteger(draft.groupIndex || 1, "groupIndex");
    if (!draft.allGroups && groupIndex > splitCount) {
      throw new Error("groupIndex cannot exceed splitCount");
    }
    const selection = draft.product_path_selection;
    const selectionId = selectionID(selection);
    if (!selectionId) throw new Error("product_path_selection is required");
    const factorAliases = [...new Set(
      (Array.isArray(draft.factorAliases) ? draft.factorAliases : [draft.factorAlias])
        .map(value => String(value || "").trim()).filter(Boolean),
    )];
    if (!factorAliases.length) throw new Error("factorAlias is required");
    const indexes = draft.allGroups
      ? Array.from({length: splitCount}, (_, index) => index + 1)
      : [groupIndex];
    const created = [];
    // A batch is an authoring event, not a configuration equivalence class.
    // Repeating the same draft therefore deliberately receives a new ID.
    const batchId = FTBacktestGroupBatches.nextID(state);
    factorAliases.forEach(factorAlias => {
      const factorGroups = indexes.map(index => {
        const useRequestedName = factorAliases.length === 1 && indexes.length === 1;
        const id = identifier("bg", useRequestedName ? draft.id : "");
        const requestedName = draft.name && useRequestedName
          ? String(draft.name).trim() : "";
        const name = requestedName
          ? uniqueName(state, requestedName)
          : FTBacktestGroupBatches.defaultName(batchId, id);
        return {
          id,
          batchId,
          name, parentId: null,
          product_path_selection: FTTestProducts.projection(selection),
          product_path_selection_id: selectionId,
          factorAlias,
          splitCount, groupIndex: index, isAllGroups: false,
          needsRegenerate: true,
        };
      });
      state.analysis.groups.push(...factorGroups);
      created.push(...factorGroups);
    });
    state.selectedBacktestGroupIDs = created.map(group => group.id);
    return created;
  }

  function addDerived(state, parentID, draft = {}) {
    initialize(state);
    const parent = find(state, parentID);
    if (!parent) throw new Error("parent group is required");
    const productMask = productMaskFrom(draft.productMask);
    const requestedName = String(draft.name || "").trim();
    // A derived strategy is its own authoring event. It may inherit the
    // parent's settings, but it must not be folded into the parent's batch.
    const batchId = FTBacktestGroupBatches.nextID(state);
    const id = identifier("dg", draft.id);
    const name = requestedName
      ? uniqueName(state, requestedName)
      : FTBacktestGroupBatches.defaultName(batchId, id);
    const group = {
      ...explicitOverrides(draft.overrides),
      id,
      batchId,
      name,
      parentId: parent.id,
      productMask,
      needsRegenerate: true,
    };
    state.analysis.groups.push(group);
    state.selectedBacktestGroupIDs = [group.id];
    return group;
  }

  function updateGroup(state, id, patch) {
    initialize(state);
    const index = state.analysis.groups.findIndex(group => group.id === id);
    if (index < 0) throw new Error("group not found");
    const current = state.analysis.groups[index];
    const next = mergePatch(current, patch);
    next.needsRegenerate = true;
    if (Object.prototype.hasOwnProperty.call(patch, "name")) {
      next.name = uniqueName(state, String(patch.name || "").trim(), id);
    }
    if (!next.parentId) {
      next.splitCount = positiveInteger(next.splitCount, "splitCount");
      next.groupIndex = positiveInteger(next.groupIndex, "groupIndex");
      if (next.groupIndex > next.splitCount) {
        throw new Error("groupIndex cannot exceed splitCount");
      }
    }
    if (patch.productMask !== undefined) next.productMask = productMaskFrom(patch.productMask);
    state.analysis.groups[index] = next;
    return next;
  }

  function addLongShort(state, longID, shortID, name = "", overrides = {}) {
    initialize(state);
    if (longID === shortID || !find(state, longID) || !find(state, shortID)) {
      throw new Error("two different groups are required");
    }
    const requestedName = String(name || "").trim();
    const batchId = FTBacktestGroupBatches.nextID(state);
    const id = identifier("ls");
    const item = {
      id,
      batchId,
      name: requestedName
        ? uniqueName(state, requestedName)
        : FTBacktestGroupBatches.defaultName(batchId, id),
      longGroupId: longID,
      shortGroupId: shortID,
      feeMode: "inherit",
      feeRate: null,
      useCloseToday: null,
      needsRegenerate: true,
      metadata: {},
      override_mounted_tabs: [],
      ...explicitOverrides(overrides),
    };
    state.analysis.ls_configs.push(item);
    return item;
  }

  function updateLongShort(state, id, patch = {}) {
    initialize(state);
    const index = state.analysis.ls_configs.findIndex(item => item.id === id);
    if (index < 0) throw new Error("Long-Short 组合不存在");
    const current = state.analysis.ls_configs[index];
    const longID = patch.longGroupId ?? current.longGroupId;
    const shortID = patch.shortGroupId ?? current.shortGroupId;
    if (longID === shortID || !find(state, longID) || !find(state, shortID)) {
      throw new Error("两个不同的分组是必需的");
    }
    const next = mergePatch(current, {
      ...patch, longGroupId: longID, shortGroupId: shortID,
    });
    if (Object.prototype.hasOwnProperty.call(patch, "name")) {
      next.name = uniqueName(state, String(patch.name || "").trim(), id);
    }
    next.needsRegenerate = true;
    state.analysis.ls_configs[index] = next;
    return next;
  }

  function renameGroup(state, id, name) {
    return updateGroup(state, id, {name: String(name || "").trim()});
  }

  function renameLongShort(state, id, name) {
    initialize(state);
    const item = state.analysis.ls_configs.find(value => value.id === id);
    if (!item) throw new Error("Long-Short 组合不存在");
    item.name = uniqueName(state, String(name || "").trim(), id);
    item.needsRegenerate = true;
    return item;
  }

  function swapLongShort(state, id) {
    initialize(state);
    const item = state.analysis.ls_configs.find(value => value.id === id);
    if (!item) throw new Error("Long-Short 组合不存在");
    const longGroupId = item.longGroupId;
    item.longGroupId = item.shortGroupId;
    item.shortGroupId = longGroupId;
    item.needsRegenerate = true;
    return item;
  }

  function removeSelected(state) {
    initialize(state);
    const removed = new Set(state.selectedBacktestGroupIDs);
    let changed = true;
    while (changed) {
      changed = false;
      for (const group of state.analysis.groups) {
        if (group.parentId && removed.has(group.parentId) && !removed.has(group.id)) {
          removed.add(group.id);
          changed = true;
        }
      }
    }
    state.analysis.groups = state.analysis.groups.filter(group => !removed.has(group.id));
    state.analysis.ls_configs = state.analysis.ls_configs.filter(item => (
      !removed.has(item.longGroupId) && !removed.has(item.shortGroupId)
    ));
    state.selectedBacktestGroupIDs = [];
    return [...removed];
  }

  function removeLongShort(state, id) {
    initialize(state);
    state.analysis.ls_configs = state.analysis.ls_configs.filter(item => item.id !== id);
    state.selectedBacktestLongShortIDs = state.selectedBacktestLongShortIDs.filter(
      value => value !== id,
    );
  }

  function removeSelectedLongShort(state) {
    initialize(state);
    const removed = new Set(state.selectedBacktestLongShortIDs);
    state.analysis.ls_configs = state.analysis.ls_configs.filter(item => !removed.has(item.id));
    state.selectedBacktestLongShortIDs = [];
    return [...removed];
  }

  function find(state, id) {
    return initialize(state).groups.find(group => group.id === id) || null;
  }

  function rootsAndChildren(state) {
    const groups = initialize(state).groups;
    const children = new Map();
    for (const group of groups) {
      if (!group.parentId) continue;
      const values = children.get(group.parentId) || [];
      values.push(group);
      children.set(group.parentId, values);
    }
    const result = [];
    const append = (group, depth, seen = new Set()) => {
      if (seen.has(group.id)) return;
      const next = new Set(seen); next.add(group.id);
      result.push({group, depth});
      for (const child of children.get(group.id) || []) append(child, depth + 1, next);
    };
    groups.filter(group => !group.parentId).forEach(group => append(group, 0));
    groups.filter(group => !result.some(item => item.group.id === group.id))
      .forEach(group => result.push({group, depth: 0}));
    return result;
  }

  function uniqueName(state, requested, exceptID = "") {
    return FTBacktestGroupBatches.uniqueName(state, requested, exceptID);
  }

  function groupBatches(state) {
    return FTBacktestGroupBatches.groupBatches(state, find, rootsAndChildren);
  }

  function registeredOverrides(group, manifest) {
    const keys = new Set(Object.keys(manifest?.defaults || {}));
    return Object.fromEntries(Object.entries(group || {}).filter(([key, value]) => (
      keys.has(key) && !structuralKeys.has(key) && value !== undefined
    )));
  }

  function mergePatch(current, patch = {}) {
    const next = {...current};
    for (const [key, value] of Object.entries(patch || {})) {
      if (value === undefined) delete next[key]; else next[key] = value;
    }
    return next;
  }

  function explicitOverrides(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(Object.entries(value).filter(([, item]) => item !== undefined));
  }

  function productMaskFrom(value) {
    if (Array.isArray(value)) {
      return Object.fromEntries(value.map(item => [String(item).trim(), true]).filter(([key]) => key));
    }
    return value && typeof value === "object" ? {...value} : {};
  }

  function positiveInteger(value, field) {
    const number = Number(value);
    if (!Number.isInteger(number) || number < 1) throw new Error(`${field} must be positive`);
    return number;
  }

  window.FTBacktestGroupModel = Object.freeze({
    addBaseBatch, addDerived, addLongShort, find, groupLabel, initialize,
    registeredOverrides, removeLongShort, removeSelected, removeSelectedLongShort,
    groupBatches, renameGroup, renameLongShort, rootsAndChildren, selected,
    selectedLongShort, selectionID, toggle, toggleLongShort, updateGroup,
    swapLongShort, updateLongShort,
  });
})();
