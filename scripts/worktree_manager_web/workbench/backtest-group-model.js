(() => {
  const structuralKeys = new Set([
    "id", "name", "parentId", "product_path_selection",
    "product_path_selection_id", "factorAlias", "splitCount", "groupIndex",
    "isAllGroups", "shortAlias", "productMask", "needsRegenerate",
  ]);
  let sequence = 0;

  function identifier(prefix, requested = "") {
    if (requested) return requested;
    sequence += 1;
    return `${prefix}_${Date.now().toString(36)}_${sequence.toString(36)}`;
  }

  function initialize(state) {
    state.analysis = state.analysis && typeof state.analysis === "object"
      ? state.analysis : {};
    state.analysis.groups = Array.isArray(state.analysis.groups)
      ? state.analysis.groups : [];
    state.analysis.ls_configs = Array.isArray(state.analysis.ls_configs)
      ? state.analysis.ls_configs : [];
    state.selectedBacktestGroupIDs = Array.isArray(state.selectedBacktestGroupIDs)
      ? state.selectedBacktestGroupIDs : [];
    return state.analysis;
  }

  function selected(state) {
    initialize(state);
    const wanted = new Set(state.selectedBacktestGroupIDs);
    return state.analysis.groups.filter(group => wanted.has(group.id));
  }

  function toggle(state, id, checked) {
    initialize(state);
    const values = new Set(state.selectedBacktestGroupIDs);
    if (checked) values.add(id); else values.delete(id);
    state.selectedBacktestGroupIDs = [...values];
  }

  function selectionID(value) {
    return FTTestProducts.groupID(value);
  }

  function groupLabel(group) {
    return group?.shortAlias || group?.name || group?.id || "";
  }

  function nextLetter(groups) {
    const used = new Set(groups.filter(group => !group.parentId).map(group => (
      String(group.shortAlias || "").match(/^([A-Z]+)/)?.[1]
    )).filter(Boolean));
    let value = 1;
    while (used.has(columnLetter(value))) value += 1;
    return columnLetter(value);
  }

  function columnLetter(value) {
    let result = "";
    for (let number = value; number > 0; number = Math.floor((number - 1) / 26)) {
      result = String.fromCharCode(65 + ((number - 1) % 26)) + result;
    }
    return result;
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
    if (!String(draft.factorAlias || "").trim()) {
      throw new Error("factorAlias is required");
    }
    const letter = nextLetter(state.analysis.groups);
    const indexes = draft.allGroups
      ? Array.from({length: splitCount}, (_, index) => index + 1)
      : [groupIndex];
    const created = indexes.map(index => {
      const shortAlias = `${letter}${index}`;
      const name = draft.name && indexes.length === 1
        ? String(draft.name).trim()
        : `${FTTestProducts.groupLabel(selection)}_${draft.factorAlias}_${splitCount}组_第${index}组`;
      return {
        id: identifier("bg", indexes.length === 1 ? draft.id : ""),
        name, shortAlias, parentId: null,
        product_path_selection: FTTestProducts.projection(selection),
        product_path_selection_id: selectionId,
        factorAlias: String(draft.factorAlias),
        splitCount, groupIndex: index, isAllGroups: false,
        needsRegenerate: true,
      };
    });
    state.analysis.groups.push(...created);
    state.selectedBacktestGroupIDs = created.map(group => group.id);
    return created;
  }

  function addDerived(state, parentID, draft = {}) {
    initialize(state);
    const parent = find(state, parentID);
    if (!parent) throw new Error("parent group is required");
    const productMask = productMaskFrom(draft.productMask);
    const group = {
      ...explicitOverrides(draft.overrides),
      id: identifier("dg", draft.id),
      name: String(draft.name || `${groupLabel(parent)} 派生组`).trim(),
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
    const next = {...current, ...patch, needsRegenerate: true};
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

  function addLongShort(state, longID, shortID, name = "") {
    initialize(state);
    if (longID === shortID || !find(state, longID) || !find(state, shortID)) {
      throw new Error("two different groups are required");
    }
    const longGroup = find(state, longID);
    const shortGroup = find(state, shortID);
    const item = {
      id: identifier("ls"),
      name: String(name || `${groupLabel(longGroup)}/${groupLabel(shortGroup)}`).trim(),
      shortAlias: `${groupLabel(longGroup)}/${groupLabel(shortGroup)}`,
      longGroupId: longID,
      shortGroupId: shortID,
      feeMode: "inherit",
      feeRate: null,
      useCloseToday: null,
      needsRegenerate: true,
      metadata: {},
    };
    state.analysis.ls_configs.push(item);
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

  function registeredOverrides(group, manifest) {
    const keys = new Set(Object.keys(manifest?.defaults || {}));
    return Object.fromEntries(Object.entries(group || {}).filter(([key]) => (
      keys.has(key) && !structuralKeys.has(key)
    )));
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
    registeredOverrides, removeLongShort, removeSelected, rootsAndChildren,
    selected, selectionID, toggle, updateGroup,
  });
})();
