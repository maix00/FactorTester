/**
 * core/group-settings.js — 分组测试统一数据管理层
 *
 * 职责：
 *   - _dirty:   编辑模式下被修改但未提交的参数字典（{key: value}）
 *   - _cache:   运行时计算结果缓存（回测结果、结构快照等）
 *   - groups:   Group 对象 CRUD（parent/child 统一树存储）
 *   - lsConfigs: Long-Short 配置 CRUD
 *   - settings: 快照/恢复/对比（序列化层）
 *
 * 不感知 UI/模式/panel。
 * 挂载到 GT.groupSettings 命名空间。
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) { console.warn('[GT core/group-settings] bootstrap missing'); return; }
    if (GT.groupSettings) { console.warn('[GT core/group-settings] already loaded'); return; }

    // ═══════════════════════════════════════════════════════════════
    // Dirty workspace — 编辑模式下的未提交参数
    // ═══════════════════════════════════════════════════════════════

    var _dirty = {};

    // ═══════════════════════════════════════════════════════════════
    // Dirty workspace API
    // ═══════════════════════════════════════════════════════════════

    var api = {};

    // ═══════════════════════════════════════════════════════════════
    // Runtime result cache
    // ═══════════════════════════════════════════════════════════════

    var _lastGrossData = null;
    var _lastMetrics = null;
    var _lastTimestamps = [];
    var _lastNgroups = 0;
    var _currentGroupDetailIndex = null;
    var _longShortDefinitions = [];
    var _lastGroupStructureKey = null;

    api.cache = {
        getLastGrossData: function() { return _lastGrossData; },
        setLastGrossData: function(v) { _lastGrossData = v; },
        getLastMetrics: function() { return _lastMetrics; },
        setLastMetrics: function(v) { _lastMetrics = v; },
        getLastTimestamps: function() { return _lastTimestamps; },
        setLastTimestamps: function(v) { _lastTimestamps = v || []; },
        getLastNgroups: function() { return _lastNgroups; },
        setLastNgroups: function(v) { _lastNgroups = v || 0; },
        getLastGroupStructureKey: function() { return _lastGroupStructureKey; },
        setLastGroupStructureKey: function(v) { _lastGroupStructureKey = v || null; },
        getCurrentGroupDetailIndex: function() { return _currentGroupDetailIndex; },
        setCurrentGroupDetailIndex: function(v) { _currentGroupDetailIndex = v; },
        getLongShortDefinitions: function() { return _longShortDefinitions; },
        setLongShortDefinitions: function(v) { _longShortDefinitions = Array.isArray(v) ? v : []; },
    };

    /** 检查 key 是否在 dirty 中 (无参=是否有任何 dirty) */
    api.isDirty = function(key) {
        if (arguments.length === 0) return Object.keys(_dirty).length > 0;
        return _dirty.hasOwnProperty(key);
    };

    /** 获取 dirty 值，不传 key 则返回整个 dirty 对象 */
    api.getDirty = function(key) {
        if (arguments.length === 0) return _deepCopy(_dirty);
        return _dirty.hasOwnProperty(key) ? _dirty[key] : undefined;
    };

    /** 设置 dirty 值 */
    api.setDirty = function(key, value) { _dirty[key] = value; };

    /** 清除所有 dirty */
    api.clearDirty = function() { _dirty = {}; };

    /** 清除指定 key 的 dirty */
    api.clearDirtyKey = function(key) { delete _dirty[key]; };

    // ═══════════════════════════════════════════════════════════════
    // Internal helpers
    // ═══════════════════════════════════════════════════════════════

    function _deepCopy(obj) {
        if (obj == null || typeof obj !== 'object') return obj;
        if (Array.isArray(obj)) return obj.map(_deepCopy);
        var copy = {};
        Object.keys(obj).forEach(function(k) { copy[k] = _deepCopy(obj[k]); });
        return copy;
    }

    // ═══════════════════════════════════════════════════════════════
    // Groups — unified Group CRUD (base + derived)
    // ═══════════════════════════════════════════════════════════════

    var _groupItems = [];
    var _groupIdCounter = 0;

    function _groupUuid() {
        _groupIdCounter += 1;
        return 'bg_' + Date.now().toString(36) + '_' + _groupIdCounter.toString(36);
    }

    function _groupFindIndex(id) {
        for (var i = 0; i < _groupItems.length; i++) {
            if (_groupItems[i].id === id) return i;
        }
        return -1;
    }

    // ── Group raw access ──

    function _groupGetRaw(id) {
        var idx = _groupFindIndex(id);
        return idx === -1 ? null : _groupItems[idx];
    }

    // =========================================================================
    // FIELD SCHEMA — base + dynamic (panel-registered) fields
    // =========================================================================
    //
    // Core defines only structural fields. Config panel fields (fee, rebalance,
    // liquidity, productMask, etc.) are injected at load time via registerField()
    // from each panel's registry registration.
    //
    // registerField spec:
    //   { key, type: 'string'|'number'|'boolean'|'object'|'any', default, validate?, patchable? }

    var FIELD_SCHEMA = []; // built from _baseFieldSpecs + _dynamicFieldSpecs

    var _baseFieldSpecs = [
        // ── Identity ──
        { key: 'id',          type: 'string',  default: '',    patchable: false },
        { key: 'name',        type: 'string',  default: '',
          validate: function(v, config) { return (!v || typeof v !== 'string' || !v.trim()) ? 'name is required (non-empty string)' : null; } },

        // ── Tree / lineage ──
        { key: 'parentId',     type: 'string',  default: null },

        // ── Tester / factor scoping (root only; child inherit from parent chain) ──
        { key: 'testerId',    type: 'string',  default: '' },
        { key: 'factorAlias', type: 'string',  default: '' },
        { key: 'groupCount',  type: 'number',  default: 5,
          validate: function(v) {
              if (typeof v !== 'number' || v < 1 || Math.floor(v) !== v) return 'groupCount must be a positive integer (≥ 1)';
              return null;
          } },
        { key: 'groupIndex',  type: 'number',  default: 1,
          validate: function(v) {
              if (v === undefined || v === null) return null;
              if (typeof v !== 'number' || v < 1 || Math.floor(v) !== v) return 'groupIndex must be a positive integer (≥ 1)';
              return null;
          } },
        { key: 'isAllGroups', type: 'boolean', default: false },

        // ── State ──
        { key: 'needsRegenerate', type: 'boolean', default: true, patchable: false },

        // ── Time range ──
        { key: 'startDate', type: 'string',  default: null },
        { key: 'endDate',   type: 'string',  default: null },

        // ── Display ──
        { key: 'shortAlias', type: 'string', default: '' },

        // ── Child overrides ──
        { key: 'overrides',    type: 'object',  default: null },

        // ── Runtime (never persisted) ──
        { key: '_expanded', type: 'boolean', default: false, patchable: false },
    ];

    var _dynamicFieldSpecs = [];

    function _rebuildSchema() {
        FIELD_SCHEMA.length = 0;
        for (var i = 0; i < _baseFieldSpecs.length; i++) { FIELD_SCHEMA.push(_baseFieldSpecs[i]); }
        for (var j = 0; j < _dynamicFieldSpecs.length; j++) { FIELD_SCHEMA.push(_dynamicFieldSpecs[j]); }

        // rebuild indexes
        FIELD_BY_KEY = {};
        PATCHABLE_KEYS.length = 0;
        DEEP_COPY_KEYS.length = 0;
        for (var k = 0; k < FIELD_SCHEMA.length; k++) {
            var f = FIELD_SCHEMA[k];
            FIELD_BY_KEY[f.key] = f;
            if (f.patchable !== false) { PATCHABLE_KEYS.push(f.key); }
            if (f.type === 'object') { DEEP_COPY_KEYS.push(f.key); }
        }
    }

    // Derived indexes
    var FIELD_BY_KEY = {};
    var PATCHABLE_KEYS = [];
    var DEEP_COPY_KEYS = [];

    // Build initial schema from base fields
    _rebuildSchema();

    // ═══════════════════════════════════════════════════════════════
    // Dynamic field registration — panels call this to inject fields
    // ═══════════════════════════════════════════════════════════════

    /** Register a field spec from a config panel. Must be called before any groups are created. */
    api.registerField = function(spec) {
        if (!spec || !spec.key) return;
        // dedup: remove existing entry with same key
        for (var i = _dynamicFieldSpecs.length - 1; i >= 0; i--) {
            if (_dynamicFieldSpecs[i].key === spec.key) { _dynamicFieldSpecs.splice(i, 1); }
        }
        _dynamicFieldSpecs.push({
            key: spec.key,
            type: spec.type || 'any',
            default: spec.hasOwnProperty('default') ? spec.default : null,
            validate: spec.validate || null,
            patchable: spec.patchable !== false,
        });
        _rebuildSchema();
    };

    /** Get the registered default value for a field key, or null if not found. */
    api.getFieldDefault = function(key) {
        var f = FIELD_BY_KEY[key];
        return f ? f.default : null;
    };

    // ═══════════════════════════════════════════════════════════════
    // Group CRUD — unified (parent/child tree)
    // ═══════════════════════════════════════════════════════════════

    function _groupsValidate(config) {
        var errors = [];
        var hasParent = !!(config.parentId);

        if (!config || typeof config !== 'object') {
            return { valid: false, errors: ['config must be an object'] };
        }

        if (!hasParent && (!config.name || typeof config.name !== 'string' || !config.name.trim())) {
            errors.push('name is required (non-empty string)');
        }

        if (hasParent) {
            if (_groupFindIndex(config.parentId) === -1) {
                errors.push('parentId references a non-existent group: ' + config.parentId);
            }
        }

        if (!hasParent) {
            // Root nodes require testerId + factorAlias
            if (!config.testerId || typeof config.testerId !== 'string' || !config.testerId.trim()) {
                errors.push('testerId is required (non-empty string)');
            }
            if (!config.factorAlias || typeof config.factorAlias !== 'string' || !config.factorAlias.trim()) {
                errors.push('factorAlias is required (non-empty string)');
            }
        }

        if (typeof config.groupCount !== 'number' || config.groupCount < 1 || Math.floor(config.groupCount) !== config.groupCount) {
            errors.push('groupCount must be a positive integer (≥ 1)');
        }

        if (config.groupIndex !== undefined && config.groupIndex !== null) {
            if (typeof config.groupIndex !== 'number' || config.groupIndex < 1 || Math.floor(config.groupIndex) !== config.groupIndex) {
                errors.push('groupIndex must be a positive integer (≥ 1)');
            }
            if (config.groupCount && config.groupIndex > config.groupCount) {
                errors.push('groupIndex must not exceed groupCount');
            }
        }

        // Run dynamic field validators
        for (var i = 0; i < _dynamicFieldSpecs.length; i++) {
            var f = _dynamicFieldSpecs[i];
            if (f.validate && config.hasOwnProperty(f.key)) {
                var msg = f.validate(config[f.key], config);
                if (msg) errors.push(f.key + ': ' + msg);
            }
        }

        return { valid: errors.length === 0, errors: errors };
    }

    function _groupsAdd(config) {
        var result = _groupsValidate(config);
        if (!result.valid) { throw new Error('Validation failed: ' + result.errors.join('; ')); }

        var hasParent = !!(config.parentId);
        var itemId = (config.id && typeof config.id === 'string' && config.id.trim()) ? config.id.trim() : _groupUuid();
        if (_groupFindIndex(itemId) !== -1) { throw new Error('Duplicate group id: ' + itemId); }

        var item = { id: itemId, name: config.name ? config.name.trim() : '' };

        // Apply all fields from FIELD_SCHEMA
        _fillGroupFromConfig(item, config, hasParent);

        _groupItems.push(item);

        // 子节点自动计算 shortAlias 和 name
        if (hasParent) {
            var needShortAlias = !item.shortAlias || !item.shortAlias.trim();
            var needName = !item.name || !item.name.trim();
            if (needShortAlias || needName) {
                // 找 siblings（同 parentId）
                var siblings = [];
                for (var si = 0; si < _groupItems.length; si++) {
                    var sg = _groupItems[si];
                    if (sg.parentId === item.parentId) {
                        siblings.push(sg);
                    }
                }
                var sibIdx = -1;
                for (var sj = 0; sj < siblings.length; sj++) {
                    if (siblings[sj].id === item.id) { sibIdx = sj; break; }
                }
                var sibNum = sibIdx >= 0 ? (sibIdx + 1) : siblings.length;

                var h = GT.panels && GT.panels.list && GT.panels.list._helpers;
                if (needShortAlias && h && typeof h.deriveShortAlias === 'function') {
                    item.shortAlias = h.deriveShortAlias(item);
                }
                if (needName) {
                    var parentNode = null;
                    if (item.parentId) {
                        for (var pi = 0; pi < _groupItems.length; pi++) {
                            if (_groupItems[pi].id === item.parentId) { parentNode = _groupItems[pi]; break; }
                        }
                    }
                    var parentName = parentNode ? (parentNode.name || parentNode.shortAlias || 'Group') : 'Group';
                    item.name = parentName + '_子组' + sibNum;
                }
            }
        }

        _emit('groupsChanged', { action: 'add', id: item.id });
        return item.id;
    }

    function _fillGroupFromConfig(item, config, hasParent) {
        for (var i = 0; i < FIELD_SCHEMA.length; i++) {
            var f = FIELD_SCHEMA[i];
            if (f.key === 'id' || f.key === 'name') continue;
            if (config.hasOwnProperty(f.key)) {
                item[f.key] = (f.type === 'object') ? _deepCopy(config[f.key]) : config[f.key];
            } else {
                item[f.key] = (f.type === 'object') ? _deepCopy(f.default) : f.default;
            }
        }
        // Reset nullable config fields for child nodes (they resolve from parent)
        if (hasParent) {
            for (var j = 0; j < _dynamicFieldSpecs.length; j++) {
                var df = _dynamicFieldSpecs[j];
                if (!config.hasOwnProperty(df.key)) item[df.key] = null;
            }
        }
    }

    function _groupsGet(id) {
        var idx = _groupFindIndex(id);
        return idx === -1 ? null : _deepCopy(_groupItems[idx]);
    }

    function _groupsGetAll() {
        return _deepCopy(_groupItems);
    }

    function _groupsUpdate(id, patch) {
        var idx = _groupFindIndex(id);
        if (idx === -1) throw new Error('Group not found: ' + id);

        if ('parentId' in patch && patch.parentId !== null && patch.parentId !== _groupItems[idx].parentId) {
            if (_groupFindIndex(patch.parentId) === -1) {
                throw new Error('New parentId references a non-existent group: ' + patch.parentId);
            }
            if (_groupsWouldCycle(id, patch.parentId)) {
                throw new Error('Cannot reparent: would create a cycle');
            }
        }

        var merged = _deepCopy(_groupItems[idx]);
        Object.keys(patch).forEach(function(key) { merged[key] = patch[key]; });
        var result = _groupsValidate(merged);
        if (!result.valid) { throw new Error('Validation failed: ' + result.errors.join('; ')); }

        var needsRegen = false;
        if (!_groupItems[idx].parentId && 'groupCount' in patch && patch.groupCount !== _groupItems[idx].groupCount) {
            needsRegen = true;
        }

        Object.keys(patch).forEach(function(key) {
            var entry = FIELD_BY_KEY[key];
            if (entry && entry.type === 'object') {
                _groupItems[idx][key] = _deepCopy(patch[key]);
            } else {
                _groupItems[idx][key] = patch[key];
            }
        });

        if (needsRegen) { _groupItems[idx].needsRegenerate = true; }

        _emit('groupsChanged', { action: 'update', id: id, needsRegenerate: needsRegen });
        return _deepCopy(_groupItems[idx]);
    }

    function _groupsRemove(id) {
        var idx = _groupFindIndex(id);
        if (idx === -1) throw new Error('Group not found: ' + id);

        var idsToRemove = _groupsCollectDescendantIds(id);
        for (var r = _groupItems.length - 1; r >= 0; r--) {
            if (idsToRemove.indexOf(_groupItems[r].id) !== -1) { _groupItems.splice(r, 1); }
        }
        _emit('groupsChanged', { action: 'remove', id: id, cascadeIds: idsToRemove });
    }

    function _groupsList() {
        return _groupItems.map(function(item) {
            return { id: item.id, name: item.name, testerId: item.testerId, factorAlias: item.factorAlias };
        });
    }

    function _groupsReset() {
        _groupItems.length = 0;
        _groupIdCounter = 0;
    }

    // Tree helpers
    function _groupsGetChildren(parentId) {
        if (!parentId) return [];
        var result = [];
        for (var i = 0; i < _groupItems.length; i++) {
            if (_groupItems[i].parentId === parentId) { result.push(_deepCopy(_groupItems[i])); }
        }
        return result;
    }

    function _groupsGetRoots() {
        var result = [];
        for (var i = 0; i < _groupItems.length; i++) {
            if (_groupItems[i].parentId !== null) continue;
            result.push(_deepCopy(_groupItems[i]));
        }
        return result;
    }

    function _groupsGetDescendants(id) {
        if (_groupFindIndex(id) === -1) throw new Error('Group not found: ' + id);
        return _groupsCollectDescendantIds(id);
    }

    function _groupsCollectDescendantIds(id) {
        var result = [id];
        for (var i = 0; i < _groupItems.length; i++) {
            if (_groupItems[i].parentId === id) {
                result = result.concat(_groupsCollectDescendantIds(_groupItems[i].id));
            }
        }
        return result;
    }

    function _groupsToggleExpanded(id) {
        var idx = _groupFindIndex(id);
        if (idx === -1) return null;
        _groupItems[idx]._expanded = !_groupItems[idx]._expanded;
        return _groupItems[idx]._expanded;
    }

    function _groupsIsAncestor(nodeId, targetId) {
        var node = _groupGetRaw(nodeId);
        while (node) {
            if (node.parentId === targetId) return true;
            if (!node.parentId) return false;
            node = _groupGetRaw(node.parentId);
        }
        return false;
    }

    /**
     * Walk parentId chain to root and return the value of fieldName from root.
     * Returns undefined if not found or if node is already root.
     */
    function _resolveRootField(nodeOrId, fieldName) {
        var node = typeof nodeOrId === 'string' ? _groupGetRaw(nodeOrId) : nodeOrId;
        if (!node) return undefined;
        if (!node.parentId) return node[fieldName]; // already root
        // Walk up
        var visited = {};
        var cur = node;
        while (cur && cur.parentId) {
            if (visited[cur.id]) return undefined; // cycle
            visited[cur.id] = true;
            cur = _groupGetRaw(cur.parentId);
            if (!cur) return undefined;
        }
        return cur ? cur[fieldName] : undefined;
    }

    function _groupsWouldCycle(nodeId, newParentId) {
        return (nodeId === newParentId) || _groupsIsAncestor(newParentId, nodeId);
    }

    // ═══════════════════════════════════════════════════════════════
    // Group utilities — batchKey, displayKey, serialize
    // ═══════════════════════════════════════════════════════════════

    function _groupsBatchKey(testerId, factorAlias, groupCount) {
        return String(testerId) + '|' + factorAlias + '|' + groupCount;
    }

    function _groupsExtractLetter(shortAlias) {
        if (!shortAlias) return null;
        var m = shortAlias.match(/^([A-Z]+)/);
        return m ? m[1] : null;
    }

    function _groupsDisplayKey(group, allGroups) {
        if (!group) return '';
        // 根节点：直接显示 shortAlias/name/id
        if (!group.parentId) return group.shortAlias || group.name || group.id || '';

        allGroups = allGroups || _groupItems;
        // 子节点：向上找链（用 parentId）
        var parent = _groupGetRaw(group.parentId);
        var parentAlias = parent ? _groupsDisplayKey(parent, allGroups) : (group.parentId || '');
        var siblings = allGroups.filter(function(item) {
            return item && item.parentId === group.parentId;
        });
        var pos = siblings.findIndex(function(item) { return item.id === group.id; });
        var suffix = pos >= 0 ? String(pos + 1) : (group.name || group.id || '?');
        return parentAlias + ':' + suffix;
    }

    function _groupsEffectiveProductNames(node, options, seen) {
        if (!node) return [];
        options = options || {};
        seen = seen || {};
        if (seen[node.id]) return [];
        seen[node.id] = true;

        var mask = node.productMask || {};
        var selected = Object.keys(mask).filter(function(name) { return mask[name]; });
        if (selected.length) return selected;

        if (node.parentId) {
            return _groupsEffectiveProductNames(_groupsGet(node.parentId), options, seen);
        }
        // 根节点：用自身 products 或 testerId 解析
        if (Array.isArray(node.products) && node.products.length) return node.products.slice();
        if (node.testerId && typeof options.getProductsForTester === 'function') {
            return options.getProductsForTester(node.testerId) || [];
        }
        return [];
    }

    // ═══════════════════════════════════════════════════════════════
    // Event emission
    // ═══════════════════════════════════════════════════════════════

    function _emit(event, data) {
        if (GT.events && typeof GT.events.emit === 'function') {
            GT.events.emit(event, data);
        }
    }

    // ═══════════════════════════════════════════════════════════════
    // Export groups API
    // ═══════════════════════════════════════════════════════════════

    api.groups = {
        add: _groupsAdd,
        get: _groupsGet,
        getAll: _groupsGetAll,
        update: _groupsUpdate,
        remove: _groupsRemove,
        list: _groupsList,
        validate: _groupsValidate,
        batchKey: _groupsBatchKey,
        extractLetter: _groupsExtractLetter,
        displayKey: _groupsDisplayKey,
        effectiveProductNames: _groupsEffectiveProductNames,
        getDescendants: _groupsGetDescendants,
        getChildren: _groupsGetChildren,
        getRoots: _groupsGetRoots,
        toggleExpanded: _groupsToggleExpanded,
        resolveRootField: _resolveRootField,
        _reset: _groupsReset,
        _getRaw: _groupGetRaw,  // internal: batch.forGroup needs this
    };

    // ═══════════════════════════════════════════════════════════════
    // LS Configs — Long-Short config CRUD
    // ═══════════════════════════════════════════════════════════════

    var _lsItems = [];
    var _lsIdCounter = 0;

    var VALID_LS_FEE_MODES = ['inherit', 'override'];
    var VALID_LS_REBALANCE_MODES = ['each_period', 'buy_and_hold', 'recycle'];

    function _lsUuid() {
        _lsIdCounter += 1;
        return 'ls_' + Date.now().toString(36) + '_' + _lsIdCounter.toString(36);
    }

    function _lsFindIndex(id) {
        for (var i = 0; i < _lsItems.length; i++) {
            if (_lsItems[i].id === id) return i;
        }
        return -1;
    }

    function _lsGroupAlias(group) {
        if (!group) return '';
        if (group.shortAlias) return group.shortAlias;
        if (!group.parentId) return group.name || group.id || '';
        return _groupsDisplayKey(group, _groupItems);
    }

    function _lsDeriveShortAlias(config) {
        if (config.shortAlias && typeof config.shortAlias === 'string' && config.shortAlias.trim()) {
            return config.shortAlias.trim();
        }
        var longGroup = _groupsGet(config.longGroupId);
        var shortGroup = _groupsGet(config.shortGroupId);
        return _lsGroupAlias(longGroup) + '/' + _lsGroupAlias(shortGroup);
    }

    function _lsConfigsValidate(config) {
        var errors = [];
        if (!config || typeof config !== 'object') {
            return { valid: false, errors: ['config must be an object'] };
        }
        if (!config.name || typeof config.name !== 'string' || !config.name.trim()) {
            errors.push('name is required (non-empty string)');
        }
        if (!config.longGroupId || typeof config.longGroupId !== 'string') {
            errors.push('longGroupId is required');
        } else if (!_groupGetRaw(config.longGroupId)) {
            errors.push('longGroupId references a non-existent group: ' + config.longGroupId);
        }
        if (!config.shortGroupId || typeof config.shortGroupId !== 'string') {
            errors.push('shortGroupId is required');
        } else if (!_groupGetRaw(config.shortGroupId)) {
            errors.push('shortGroupId references a non-existent group: ' + config.shortGroupId);
        }
        if (config.feeMode !== undefined && VALID_LS_FEE_MODES.indexOf(config.feeMode) === -1) {
            errors.push('feeMode must be one of: ' + VALID_LS_FEE_MODES.join(', '));
        }
        if (config.feeRate !== undefined && config.feeRate !== null && (typeof config.feeRate !== 'number' || config.feeRate < 0)) {
            errors.push('feeRate must be a non-negative number or null');
        }
        if (config.rebalanceMode !== undefined && config.rebalanceMode !== null && VALID_LS_REBALANCE_MODES.indexOf(config.rebalanceMode) === -1) {
            errors.push('rebalanceMode must be one of: ' + VALID_LS_REBALANCE_MODES.join(', '));
        }
        if (config.metadata !== undefined && (typeof config.metadata !== 'object' || config.metadata === null || Array.isArray(config.metadata))) {
            errors.push('metadata must be a plain object');
        }
        return { valid: errors.length === 0, errors: errors };
    }

    function _lsConfigsAdd(config) {
        var result = _lsConfigsValidate(config);
        if (!result.valid) { throw new Error('Validation failed: ' + result.errors.join('; ')); }
        var item = {
            id: (typeof config.id === 'string' && config.id.trim()) ? config.id : _lsUuid(),
            name: config.name.trim(),
            shortAlias: _lsDeriveShortAlias(config),
            longGroupId: config.longGroupId,
            shortGroupId: config.shortGroupId,
            feeMode: config.feeMode || 'inherit',
            feeRate: config.feeRate !== undefined ? config.feeRate : null,
            useCloseToday: config.useCloseToday !== undefined ? config.useCloseToday : null,
            rebalanceMode: config.rebalanceMode !== undefined ? config.rebalanceMode : null,
            needsRegenerate: true,
            metadata: config.metadata !== undefined ? _deepCopy(config.metadata) : {},
        };
        _lsItems.push(item);
        _emit('lsConfigsChanged', { action: 'add', id: item.id });
        return _deepCopy(item);
    }

    function _lsConfigsGet(id) {
        var idx = _lsFindIndex(id);
        return idx === -1 ? null : _deepCopy(_lsItems[idx]);
    }

    function _lsConfigsGetAll() {
        return _deepCopy(_lsItems);
    }

    function _lsConfigsUpdate(id, patch) {
        var idx = _lsFindIndex(id);
        if (idx === -1) throw new Error('LS config not found: ' + id);
        var merged = _deepCopy(_lsItems[idx]);
        Object.keys(patch).forEach(function(key) { merged[key] = patch[key]; });
        var result = _lsConfigsValidate(merged);
        if (!result.valid) { throw new Error('Validation failed: ' + result.errors.join('; ')); }
        Object.keys(patch).forEach(function(key) { _lsItems[idx][key] = patch[key]; });
        if ('longGroupId' in patch || 'shortGroupId' in patch || 'shortAlias' in patch) {
            if (!('shortAlias' in patch)) {
                // 清除旧 shortAlias，让 _lsDeriveShortAlias 根据新的 longGroupId/shortGroupId 重新派生
                delete _lsItems[idx].shortAlias;
            }
            _lsItems[idx].shortAlias = _lsDeriveShortAlias(_lsItems[idx]);
        }
        _emit('lsConfigsChanged', { action: 'update', id: id });
        return _deepCopy(_lsItems[idx]);
    }

    function _lsConfigsRemove(id) {
        var idx = _lsFindIndex(id);
        if (idx === -1) throw new Error('LS config not found: ' + id);
        var removed = _lsItems.splice(idx, 1)[0];
        _emit('lsConfigsChanged', { action: 'remove', id: id });
        return _deepCopy(removed);
    }

    function _lsConfigsMarkStale(id) {
        var idx = _lsFindIndex(id);
        if (idx === -1) throw new Error('LS config not found: ' + id);
        _lsItems[idx].needsRegenerate = true;
        _emit('lsConfigsChanged', { action: 'markStale', id: id });
        return _deepCopy(_lsItems[idx]);
    }

    function _lsConfigsFindByDerivedGroup(derivedGroupId) {
        return _lsItems.filter(function(item) {
            return item.longGroupId === derivedGroupId || item.shortGroupId === derivedGroupId;
        }).map(function(item) { return _deepCopy(item); });
    }

    function _lsConfigsList() {
        return _lsItems.map(function(item) {
            return { id: item.id, name: item.name, longGroupId: item.longGroupId, shortGroupId: item.shortGroupId };
        });
    }

    function _lsParseCsvNumbers(value) {
        return String(value || '').split(',')
            .map(function(x) { return parseFloat(x.trim()); })
            .filter(function(x) { return !isNaN(x) && isFinite(x); });
    }

    function _lsBuildLegacyLegs(groupsValue, weightsValue, defaultGroups) {
        var groups = _lsParseCsvNumbers(groupsValue);
        if (!groups.length) groups = defaultGroups || [];
        var weights = _lsParseCsvNumbers(weightsValue);
        if (!weights.length) weights = groups.map(function() { return 1; });
        return groups.map(function(groupNo, idx) {
            return {
                group: Math.max(0, Math.floor(groupNo) - 1),
                weight: weights[idx] != null ? weights[idx] : weights[weights.length - 1]
            };
        }).filter(function(leg) { return leg.weight > 0; });
    }

    function _lsDefaultLegacyDefinition() {
        return { id: 'LS1', name: 'Long-Short', longGroups: '1', longWeights: '1', shortGroups: '', shortWeights: '1' };
    }

    function _lsBuildLegacyPayload(def, nGroups) {
        def = def || _lsDefaultLegacyDefinition();
        return {
            name: (def.name || '').trim() || 'Long-Short',
            long: _lsBuildLegacyLegs(def.longGroups || '1', def.longWeights || '1', [1]),
            short: _lsBuildLegacyLegs(def.shortGroups || '', def.shortWeights || '1', [nGroups])
        };
    }

    function _lsBuildLegacyPayloads(definitions, nGroups) {
        var defs = definitions && definitions.length ? definitions : [_lsDefaultLegacyDefinition()];
        return defs.map(function(def) { return _lsBuildLegacyPayload(def, nGroups); });
    }

    function _lsConfigsDisplayName(config) {
        if (!config) return 'Long-Short';
        if (config.shortAlias) return config.shortAlias;
        var longGroup = _groupsGet(config.longGroupId);
        var shortGroup = _groupsGet(config.shortGroupId);
        return _lsGroupAlias(longGroup) + '/' + _lsGroupAlias(shortGroup);
    }

    function _lsConfigsReset() {
        _lsItems.length = 0;
        _lsIdCounter = 0;
    }

    api.lsConfigs = {
        add: _lsConfigsAdd,
        get: _lsConfigsGet,
        getAll: _lsConfigsGetAll,
        update: _lsConfigsUpdate,
        remove: _lsConfigsRemove,
        markStale: _lsConfigsMarkStale,
        findByDerivedGroup: _lsConfigsFindByDerivedGroup,
        list: _lsConfigsList,
        parseCsvNumbers: _lsParseCsvNumbers,
        buildLegacyLegs: _lsBuildLegacyLegs,
        defaultLegacyDefinition: _lsDefaultLegacyDefinition,
        buildLegacyPayload: _lsBuildLegacyPayload,
        buildLegacyPayloads: _lsBuildLegacyPayloads,
        displayName: _lsConfigsDisplayName,
        validate: _lsConfigsValidate,
        _reset: _lsConfigsReset,
    };

    // ═══════════════════════════════════════════════════════════════
    // Settings snapshot/restore — template save & load
    // ═══════════════════════════════════════════════════════════════

    /**
     * Collect current groups & lsConfigs into a flat serializable snapshot.
     * @returns {{ groups: Array, lsConfigs: Array }}
     */
    function _settingsSnapshot() {
        return {
            groups: _groupsGetAll(),
            lsConfigs: _lsConfigsGetAll(),
        };
    }

    /**
     * Apply a snapshot: clear existing state, restore groups → lsConfigs.
     * @param {{ groups?: Array, lsConfigs?: Array }} snap
     * @returns {{ applied: { groups: number, lsConfigs: number }, errors: string[] }}
     */
    function _settingsApply(snap) {
        var result = { applied: { groups: 0, lsConfigs: 0 }, errors: [] };
        snap = _settingsNormalizeSnapshot(snap || {});

        _groupsReset();
        _lsConfigsReset();

        if (snap.groups && Array.isArray(snap.groups)) {
            // Sort: roots first (parentId null/missing), then children — avoids
            // validation failure when child appears before parent in snapshot.
            var sorted = snap.groups.slice().sort(function(a, b) {
                var aHasParent = !!(a.parentId);
                var bHasParent = !!(b.parentId);
                if (aHasParent && !bHasParent) return 1;
                if (!aHasParent && bHasParent) return -1;
                return 0;
            });
            for (var gi = 0; gi < sorted.length; gi++) {
                try { _groupsAdd(sorted[gi]); result.applied.groups++; }
                catch (e) { result.errors.push('groups[' + gi + ']: ' + e.message); }
            }
        }

        if (snap.lsConfigs && Array.isArray(snap.lsConfigs)) {
            for (var li = 0; li < snap.lsConfigs.length; li++) {
                try { _lsConfigsAdd(snap.lsConfigs[li]); result.applied.lsConfigs++; }
                catch (e) { result.errors.push('lsConfigs[' + li + ']: ' + e.message); }
            }
        }

        return result;
    }

    function _settingsNormalizeSnapshot(snap) {
        snap = snap || {};
        return {
            groups: Array.isArray(snap.groups) ? snap.groups : [],
            lsConfigs: Array.isArray(snap.lsConfigs) ? snap.lsConfigs : [],
        };
    }

    function _settingsSummarize(snap) {
        snap = _settingsNormalizeSnapshot(snap || {});
        var groups = snap.groups || [];
        var lsConfigs = snap.lsConfigs || [];
        if (!groups.length && !lsConfigs.length) return null;
        var baseGroups = groups.filter(function(group) { return !group.parentId; });
        var childGroups = groups.filter(function(group) { return !!group.parentId; });
        var lines = [
            '基础组 ' + baseGroups.length + ' 个 · 子组 ' + childGroups.length + ' 个 · Long-Short ' + lsConfigs.length + ' 个'
        ];
        baseGroups.slice(0, 8).forEach(function(group) {
            var alias = group.shortAlias || group.name || group.id || '未命名组';
            var indexText = group.groupIndex != null ? group.groupIndex : '未设置';
            var countText = group.groupCount != null ? group.groupCount : '未设置';
            var feeText = group.feeMode || api.getFieldDefault('feeMode');
            var rebalanceText = group.rebalanceMode || api.getFieldDefault('rebalanceMode');
            lines.push(alias + ' · 第' + indexText + '/' + countText + '组 · 因子 ' + (group.factorAlias || '未设置')
                + ' · 费率 ' + feeText + ' · 再平衡 ' + rebalanceText);
        });
        if (baseGroups.length > 8) {
            lines.push('…另 ' + (baseGroups.length - 8) + ' 个基础组');
        }
        childGroups.slice(0, 4).forEach(function(group) {
            var parent = group.parentId ? _groupsGet(group.parentId) : null;
            lines.push('子组 ' + (group.shortAlias || group.name || group.id || '未命名子组')
                + ' · 父节点 ' + (parent ? (parent.shortAlias || parent.name || parent.id) : (group.parentId || '未设置')));
        });
        lsConfigs.slice(0, 4).forEach(function(config) {
            lines.push('Long-Short ' + (config.shortAlias || config.name || config.id || '未命名 Long-Short')
                + ' · Long ' + (config.longGroupId || '未设置') + ' · Short ' + (config.shortGroupId || '未设置'));
        });
        return lines;
    }

    api.settings = {
        key: 'group_settings',
        order: 50,
        label: '分组测试',
        icon: '🧪',
        collect: _settingsSnapshot,
        apply: _settingsApply,
        summarize: _settingsSummarize,
        normalize: _settingsNormalizeSnapshot,
    };

    GT.groupSettings = api;
    GT.core = GT.core || {};
    GT.log('core/group-settings loaded');
})();
