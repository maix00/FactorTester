/**
 * core/add-group-batch.js — addGroupBatch registry (UI list grouping)
 *
 * 管理 addGroupBatch 对象：{ number, name, product_path_selection_id, factor, n_groups }。
 * key = "productPathSelectionId|factorAlias|splitCount"，三元组唯一对应一个 batch。
 *
 * 核心函数：
 *   _addGroupBatchEnsure(productPathSelectionId, factorAlias, nGroups) → 存在则返回已有，否则创建
 *   _addGroupBatchForGroup(group) → 沿 parentId 找根节点，按三元组匹配 batch
 *   _addGroupBatchGet(productPathSelectionId, factorAlias, nGroups) → 按三元组查询
 *   _addGroupBatchGetAll() → 全部 batch
 *
 * 挂载到 GT.groupSettings.addGroupBatch。
 *
 * 与 run-group-batch.js 的区别：
 *   - addGroupBatch = UI 列表分组（前端显示用）
 *   - productCoverageBatch = 后端计算批次（与后端 product_coverage_batch_index 一一对应）
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    // ═══════════════════════════════════════════════════════════════
    // State
    // ═══════════════════════════════════════════════════════════════

    var _batches = {};  // key: "productPathSelectionId|factorAlias|splitCount" → {number, name, product_path_selection_id, factor, n_groups}

    // ═══════════════════════════════════════════════════════════════
    // Helpers
    // ═══════════════════════════════════════════════════════════════

    function _selectionId(selection) {
        return selection ? String(selection.product_path_selection_id || selection.selection_id || selection.id || '') : '';
    }

    function _addGroupBatchKey(productPathSelectionId, factorAlias, nGroups) {
        return (productPathSelectionId || '') + '|' + (factorAlias || '') + '|' + (nGroups || 0);
    }

    function _groupGetRawFn(id) {
        return (GT.groupSettings && GT.groupSettings.groups && GT.groupSettings.groups._getRaw)
            ? GT.groupSettings.groups._getRaw(id)
            : null;
    }

    // ═══════════════════════════════════════════════════════════════
    // Resolve root node (duplicated from group-settings for self-containedness)
    // ═══════════════════════════════════════════════════════════════

    function _resolveRoot(nodeOrId) {
        var node = typeof nodeOrId === 'string' ? _groupGetRawFn(nodeOrId) : nodeOrId;
        if (!node) return null;
        if (!node.parentId) return node;
        var visited = {};
        var cur = node;
        while (cur && cur.parentId) {
            if (visited[cur.id]) return null; // cycle
            visited[cur.id] = true;
            cur = _groupGetRawFn(cur.parentId);
            if (!cur) return null;
        }
        return cur;
    }

    // ═══════════════════════════════════════════════════════════════
    // addGroupBatch CRUD
    // ═══════════════════════════════════════════════════════════════

    function _addGroupBatchEnsure(productPathSelectionId, factorAlias, nGroups) {
        var key = _addGroupBatchKey(productPathSelectionId, factorAlias, nGroups);
        if (_batches[key]) return _batches[key];
        var num = Object.keys(_batches).length + 1;
        var letter = '';
        var n = num;
        while (n > 0) { n--; letter = String.fromCharCode(65 + (n % 26)) + letter; n = Math.floor(n / 26); }
        _batches[key] = {
            number: num,
            name: letter,
            product_path_selection_id: productPathSelectionId || '',
            factor: factorAlias || '',
            n_groups: nGroups || 0
        };
        return _batches[key];
    }

    function _addGroupBatchGet(productPathSelectionId, factorAlias, nGroups) {
        if (typeof productPathSelectionId === 'object' && productPathSelectionId !== null) {
            var g = productPathSelectionId;
            return _batches[_addGroupBatchKey(_selectionId(g.product_path_selection), g.factorAlias, g.splitCount)] || null;
        }
        return _batches[_addGroupBatchKey(productPathSelectionId, factorAlias, nGroups)] || null;
    }

    function _addGroupBatchGetAll() {
        return Object.keys(_batches).map(function(k) { return _batches[k]; });
    }

    function _addGroupBatchForGroup(group) {
        if (!group) return null;
        var root = group.parentId ? _resolveRoot(group) : group;
        if (!root) return null;
        return _addGroupBatchGet(_selectionId(root.product_path_selection), root.factorAlias, root.splitCount);
    }

    function _addGroupBatchUpdate(number, patch) {
        var keys = Object.keys(_batches);
        for (var i = 0; i < keys.length; i++) {
            if (_batches[keys[i]].number === number) {
                var b = _batches[keys[i]];
                Object.keys(patch).forEach(function(k) { b[k] = patch[k]; });
                return b;
            }
        }
        return null;
    }

    function _addGroupBatchRemove(number) {
        var keys = Object.keys(_batches);
        for (var i = 0; i < keys.length; i++) {
            if (_batches[keys[i]].number === number) {
                delete _batches[keys[i]];
                return;
            }
        }
    }

    function _addGroupBatchReset() {
        _batches = {};
    }

    // ═══════════════════════════════════════════════════════════════
    // Export to GT.groupSettings.addGroupBatch
    // ═══════════════════════════════════════════════════════════════

    GT.groupSettings = GT.groupSettings || {};
    GT.groupSettings.addGroupBatch = {
        key: _addGroupBatchKey,
        get: _addGroupBatchGet,
        getAll: _addGroupBatchGetAll,
        ensure: _addGroupBatchEnsure,
        create: _addGroupBatchEnsure,        // alias
        update: _addGroupBatchUpdate,
        remove: _addGroupBatchRemove,
        forGroup: _addGroupBatchForGroup,
        _reset: _addGroupBatchReset,
    };

})();
