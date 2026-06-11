/**
 * core/batches.js — groupAddBatch registry
 *
 * 管理 groupAddBatch 对象：{ number, name, submission_id, factor, n_groups }。
 * key = "testerId|factorAlias|groupCount"，三元组唯一对应一个 batch。
 *
 * 核心函数：
 *   _batchEnsure(testerId, factorAlias, nGroups) → 存在则返回已有，否则创建
 *   _batchForGroup(group) → 沿 parentId 找根节点，按三元组匹配 batch
 *   _batchGet(testerId, factorAlias, nGroups) → 按三元组查询
 *   _batchGetAll() → 全部 batch
 *
 * 挂载到 GT.groupSettings.api.batch。
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    // ═══════════════════════════════════════════════════════════════
    // State
    // ═══════════════════════════════════════════════════════════════

    var _batches = {};  // key: "testerId|factorAlias|groupCount" → {number, name, submission_id, factor, n_groups}

    // 引用 group-settings 的闭包变量（通过闭包引用，而非传入）
    // _resolveRoot, _groupGetRaw 通过 api 获取

    // ═══════════════════════════════════════════════════════════════
    // Helpers
    // ═══════════════════════════════════════════════════════════════

    function _batchKey(testerId, factorAlias, nGroups) {
        return (testerId || '') + '|' + (factorAlias || '') + '|' + (nGroups || 0);
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
    // groupAddBatch CRUD
    // ═══════════════════════════════════════════════════════════════

    /**
     * Ensure a groupAddBatch exists for the given tester/factor/nGroups.
     * 如果三元组匹配的 batch 已存在，直接返回；否则创建新 batch。
     */
    function _batchEnsure(submissionId, factorAlias, nGroups) {
        var key = _batchKey(submissionId, factorAlias, nGroups);
        if (_batches[key]) return _batches[key];
        var num = Object.keys(_batches).length + 1;
        var letter = '';
        var n = num;
        while (n > 0) { n--; letter = String.fromCharCode(65 + (n % 26)) + letter; n = Math.floor(n / 26); }
        _batches[key] = {
            number: num,
            name: letter,
            submission_id: submissionId || '',
            factor: factorAlias || '',
            n_groups: nGroups || 0
        };
        return _batches[key];
    }

    /** Get batch by key components (or by root-like object with testerId/factorAlias/groupCount). */
    function _batchGet(testerId, factorAlias, nGroups) {
        if (typeof testerId === 'object' && testerId !== null) {
            var g = testerId;
            return _batches[_batchKey(g.testerId, g.factorAlias, g.groupCount)] || null;
        }
        return _batches[_batchKey(testerId, factorAlias, nGroups)] || null;
    }

    function _batchGetAll() {
        return Object.keys(_batches).map(function(k) { return _batches[k]; });
    }

    /** For any group node, walk parentId chain to root, then find batch via root's key. */
    function _batchForGroup(group) {
        if (!group) return null;
        var root = group.parentId ? _resolveRoot(group) : group;
        if (!root) return null;
        return _batchGet(root.testerId, root.factorAlias, root.groupCount);
    }

    function _batchUpdate(number, patch) {
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

    function _batchRemove(number) {
        var keys = Object.keys(_batches);
        for (var i = 0; i < keys.length; i++) {
            if (_batches[keys[i]].number === number) {
                delete _batches[keys[i]];
                return;
            }
        }
    }

    function _batchReset() {
        _batches = {};
    }

    // ═══════════════════════════════════════════════════════════════
    // Export to GT.groupSettings.batch
    // ═══════════════════════════════════════════════════════════════

    GT.groupSettings = GT.groupSettings || {};
    GT.groupSettings.batch = {
        get: _batchGet,
        getAll: _batchGetAll,
        ensure: _batchEnsure,
        create: _batchEnsure,        // alias
        update: _batchUpdate,
        remove: _batchRemove,
        forGroup: _batchForGroup,
        batchKey: _batchKey,
        _reset: _batchReset,
    };

})();
