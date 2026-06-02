/**
 * groups.js — Unified group CRUD data model
 *
 * Pure logic module. Zero DOM dependencies.
 *
 * ═══════════════════════════════════════════════════════════════════════════════
 * FIELD_SCHEMA — single source of truth for ALL group fields
 * ═══════════════════════════════════════════════════════════════════════════════
 *
 * All groups (base & derived) share the exact same set of fields.
 * isDerived is just a boolean flag; base groups have isDerived=false,
 * parentId=null, baseGroupId=null, overrides=null — no special shape.
 *
 * When adding a new config tab / panel that introduces a new field:
 *   → Add ONE entry to FIELD_SCHEMA below.
 *   → add(), validate(), update() all pick it up automatically.
 *   → No need to touch any other code path.
 *
 * FIELD_SCHEMA entry shape:
 *   key       : property name on the group object
 *   type      : 'string' | 'number' | 'boolean' | 'object' | 'any'
 *                - 'object' fields are deep-copied in add/update
 *   default   : default value — same for all groups
 *   validate  : optional function(value, fullConfig) → null | errorString
 *   patchable : if false, the field is immutable after add
 *
 * Data shape (all fields — same for base & derived):
 *   { id, name, isDerived,
 *     parentId, baseGroupId,
 *     testerId, factorAlias, groupCount, groupIndex, isAllGroups,
 *     feeMode, feeRate, feeMap, useCloseToday, rebalanceMode,
 *     liquidityMode, liquidityPercent,
 *     needsRegenerate, startDate, endDate, shortAlias,
 *     productMask, overrides,
 *     _expanded }
 *
 * Tree helpers (getTree, getDescendants, toggleExpanded, getChildren, getRoots)
 * work on ALL groups — isDerived / parentId control tree nesting for list display.
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.datamodel) { GT.datamodel = {}; }

    // ---------------------------------------------------------------------------
    // Internal state
    // ---------------------------------------------------------------------------

    var _items = [];          // array of base group objects
    var _idCounter = 0;

    // ---------------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------------

    function _uuid() {
        _idCounter += 1;
        return 'bg_' + Date.now().toString(36) + '_' + _idCounter.toString(36);
    }

    function _deepCopy(obj) {
        return JSON.parse(JSON.stringify(obj));
    }

    function _findIndex(id) {
        for (var i = 0; i < _items.length; i++) {
            if (_items[i].id === id) return i;
        }
        return -1;
    }

    /** Internal: get raw item without copy (for fast lookups). Returns null if not found. */
    function _getRaw(id) {
        var idx = _findIndex(id);
        return idx === -1 ? null : _items[idx];
    }

    // =========================================================================
    // FIELD SCHEMA — single source of truth for all group properties
    // =========================================================================
    //
    // Each field entry:
    //   key       : property name on the group object
    //   type      : 'string' | 'number' | 'boolean' | 'object' | 'any'
    //                - 'object' fields are deep-copied in add/update
    //   default   : default value when building a group (base or derived — same for all)
    //   validate  : optional function(value, fullConfig) → null | errorString
    //   patchable : if false, the field is immutable after add (default: true)
    //
    // To add a new config tab / panel with a new field:
    //   → Add ONE entry here.
    //   → add(), validate(), update() all pick it up automatically.
    //   → No other code changes needed.
    // =========================================================================

    var FIELD_SCHEMA = [
        // ── Identity ──
        { key: 'id',          type: 'string',  default: '',    patchable: false },
        { key: 'name',        type: 'string',  default: '',
          validate: function(v, config) { if (config && config.isDerived) return null; return (!v || typeof v !== 'string' || !v.trim()) ? 'name is required (non-empty string)' : null; } },
        { key: 'isDerived',   type: 'boolean', default: false, patchable: false },

        // ── Tree / lineage ──
        { key: 'parentId',     type: 'string',  default: null },
        { key: 'baseGroupId',  type: 'string',  default: null,
          validate: function(v, config) {
              if (!config || !config.isDerived) return null;
              if (!v || typeof v !== 'string') return 'baseGroupId is required for derived groups';
              if (v !== '__batch__' && !_getRaw(v)) return 'baseGroupId references a non-existent group: ' + v;
              return null;
          } },

        // ── Tester / factor scoping ──
        { key: 'testerId',    type: 'string',  default: '',
          validate: function(v, config) { if (config && config.isDerived) return null; return (!v || typeof v !== 'string') ? 'testerId is required' : null; } },
        { key: 'factorAlias', type: 'string',  default: '',
          validate: function(v, config) { if (config && config.isDerived) return null; return (!v || typeof v !== 'string') ? 'factorAlias is required' : null; } },
        { key: 'groupCount',  type: 'number',  default: 5,
          validate: function(v, config) {
              if (config && config.isDerived) return null;
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

        // ── Fee config ──
        { key: 'feeMode',     type: 'string',  default: 'none',
          validate: function(v) {
              if (v !== undefined && VALID_FEE_MODES.indexOf(v) === -1) return 'feeMode must be one of: ' + VALID_FEE_MODES.join(', ');
              return null;
          } },
        { key: 'feeRate',     type: 'any',     default: null,
          validate: function(v) {
              if (v !== undefined && v !== null && (typeof v !== 'number' || v < 0)) return 'feeRate must be a non-negative number or null';
              return null;
          } },
        { key: 'feeMap',      type: 'object',  default: null },
        { key: 'feeSensitivity', type: 'number', default: 1,
          validate: function(v) {
              if (v !== undefined && v !== null && (typeof v !== 'number' || v < 0)) return 'feeSensitivity must be a non-negative number or null';
              return null;
          } },

        // ── Close-today / rebalance ──
        { key: 'useCloseToday',   type: 'boolean', default: false },
        { key: 'rebalanceMode',   type: 'string',  default: 'each_period',
          validate: function(v) {
              if (v !== undefined && VALID_REBALANCE_MODES.indexOf(v) === -1) return 'rebalanceMode must be one of: ' + VALID_REBALANCE_MODES.join(', ');
              return null;
          } },

        // ── Liquidity config ──
        { key: 'liquidityMode',   type: 'string',  default: 'infinite',
          validate: function(v) {
              if (v !== undefined && VALID_LIQUIDITY_MODES.indexOf(v) === -1) return 'liquidityMode must be one of: ' + VALID_LIQUIDITY_MODES.join(', ');
              return null;
          } },
        { key: 'liquidityPercent', type: 'number', default: 100,
          validate: function(v) {
              if (v !== undefined && v !== null && (typeof v !== 'number' || v < 0 || v > 100)) return 'liquidityPercent must be a number between 0 and 100';
              return null;
          } },

        // ── State ──
        { key: 'needsRegenerate', type: 'boolean', default: true, patchable: false },

        // ── Time range ──
        { key: 'startDate', type: 'string',  default: null },
        { key: 'endDate',   type: 'string',  default: null },

        // ── Display ──
        { key: 'shortAlias', type: 'string', default: '' },

        // ── Derived lineage / overrides ──
        { key: 'productMask',  type: 'object',  default: {} },
        { key: 'overrides',    type: 'object',  default: null },
        // overrides: null or array of field keys that differ from baseGroup (e.g. ['rebalanceMode', 'feeMode'])

        // ── Runtime (never persisted) ──
        { key: '_expanded', type: 'boolean', default: false, patchable: false },
    ];

    // Derived indexes from FIELD_SCHEMA (computed once at load)
    var FIELD_BY_KEY = {};
    var PATCHABLE_KEYS = [];
    var DEEP_COPY_KEYS = [];

    (function _buildSchemaIndexes() {
        for (var i = 0; i < FIELD_SCHEMA.length; i++) {
            var f = FIELD_SCHEMA[i];
            FIELD_BY_KEY[f.key] = f;
            if (f.patchable !== false) { PATCHABLE_KEYS.push(f.key); }
            if (f.type === 'object') { DEEP_COPY_KEYS.push(f.key); }
        }
    })();

    // ---------------------------------------------------------------------------
    // Shared utilities — single source of truth for batch/combo/alias logic
    // ---------------------------------------------------------------------------

    /**
     * Build the canonical batch/combo key from (testerId, factorAlias, groupCount).
     * Used by both add (letter assignment) and list (batch grouping + display).
     */
    function batchKey(testerId, factorAlias, groupCount) {
        return String(testerId) + '|' + factorAlias + '|' + groupCount;
    }

    /**
     * Extract the letter prefix from a shortAlias (e.g. "A" from "A1a", "AB" from "AB3").
     * Returns null for single-group numeric-only aliases like "5".
     */
    function extractLetter(shortAlias) {
        if (!shortAlias) return null;
        var m = shortAlias.match(/^([A-Z]+)/);
        return m ? m[1] : null;
    }

    function displayKey(group, allGroups) {
        if (!group) return '';
        if (!group.isDerived) return group.shortAlias || group.key || group.name || group.id || '';

        allGroups = allGroups || _items;
        var base = _getRaw(group.baseGroupId);
        var baseAlias = base ? (base.shortAlias || base.name || base.id) : (group.baseGroupId || '');
        var siblings = allGroups.filter(function(item) {
            return item && item.isDerived && item.baseGroupId === group.baseGroupId && item.parentId === group.parentId;
        });
        var pos = siblings.findIndex(function(item) { return item.id === group.id; });
        var suffix = pos >= 0 ? String(pos + 1) : (group.name || group.id || '?');
        if (group.parentId) {
            var parent = _getRaw(group.parentId);
            var parentAlias = parent ? displayKey(parent, allGroups) : baseAlias;
            return parentAlias + ':' + suffix;
        }
        return baseAlias + ':' + suffix;
    }

    // ---------------------------------------------------------------------------
    // Validation
    // ---------------------------------------------------------------------------

    var VALID_FEE_MODES = ['none', 'uniform', 'per_product', 'custom'];
    var VALID_REBALANCE_MODES = ['each_period', 'buy_and_hold', 'recycle'];
    var VALID_LIQUIDITY_MODES = ['infinite', 'percent'];

    /**
     * Validate a group config.
     * When isDerived, testerId/factorAlias/groupCount are optional (inherited from baseGroupId).
     * @param {object} config - raw config to validate
     * @returns {{valid: boolean, errors: string[]}}
     */
    function validate(config) {
        var errors = [];
        var isDerived = !!(config.isDerived);

        if (!config || typeof config !== 'object') {
            return { valid: false, errors: ['config must be an object'] };
        }

        // Required: name (base groups: required; derived groups: auto-resolve from baseGroup)
        if (!config.name || typeof config.name !== 'string' || !config.name.trim()) {
            if (!isDerived) {
                errors.push('name is required (non-empty string)');
            }
        }

        if (isDerived) {
            // Derived group: baseGroupId required
            if (!config.baseGroupId || typeof config.baseGroupId !== 'string') {
                errors.push('baseGroupId is required for derived groups');
            } else if (config.baseGroupId !== '__batch__') {
                var bg = _getRaw(config.baseGroupId);
                if (!bg) {
                    errors.push('baseGroupId references a non-existent group: ' + config.baseGroupId);
                }
            }
            // parentId: if provided, must be an existing node (cycle check in add/update)
            if (config.parentId !== undefined && config.parentId !== null) {
                var parentIdx = _findIndex(config.parentId);
                if (parentIdx === -1) {
                    errors.push('parentId references a non-existent group: ' + config.parentId);
                }
            }
        } else {
            // Base group: testerId, factorAlias, groupCount required
            if (!config.testerId || typeof config.testerId !== 'string' || !config.testerId.trim()) {
                errors.push('testerId is required (non-empty string)');
            }
            if (!config.factorAlias || typeof config.factorAlias !== 'string' || !config.factorAlias.trim()) {
                errors.push('factorAlias is required (non-empty string)');
            }
            if (typeof config.groupCount !== 'number' || config.groupCount < 1 || Math.floor(config.groupCount) !== config.groupCount) {
                errors.push('groupCount must be a positive integer (≥ 1)');
            }
        }

        // groupIndex (1-based index)
        if (config.groupIndex !== undefined && config.groupIndex !== null) {
            if (typeof config.groupIndex !== 'number' || config.groupIndex < 1 || Math.floor(config.groupIndex) !== config.groupIndex) {
                errors.push('groupIndex must be a positive integer (≥ 1)');
            }
            if (config.groupCount && config.groupIndex > config.groupCount) {
                errors.push('groupIndex must not exceed groupCount');
            }
        }

        // feeMode
        if (config.feeMode !== undefined && config.feeMode !== null && VALID_FEE_MODES.indexOf(config.feeMode) === -1) {
            errors.push('feeMode must be one of: ' + VALID_FEE_MODES.join(', '));
        }

        // feeRate
        if (config.feeRate !== undefined && config.feeRate !== null && (typeof config.feeRate !== 'number' || config.feeRate < 0)) {
            errors.push('feeRate must be a non-negative number or null');
        }

        if (config.feeSensitivity !== undefined && config.feeSensitivity !== null && (typeof config.feeSensitivity !== 'number' || config.feeSensitivity < 0)) {
            errors.push('feeSensitivity must be a non-negative number or null');
        }

        // rebalanceMode
        if (config.rebalanceMode !== undefined && config.rebalanceMode !== null && VALID_REBALANCE_MODES.indexOf(config.rebalanceMode) === -1) {
            errors.push('rebalanceMode must be one of: ' + VALID_REBALANCE_MODES.join(', '));
        }

        // liquidityMode / liquidityPercent
        if (config.liquidityMode !== undefined && config.liquidityMode !== null && VALID_LIQUIDITY_MODES.indexOf(config.liquidityMode) === -1) {
            errors.push('liquidityMode must be one of: ' + VALID_LIQUIDITY_MODES.join(', '));
        }
        if (config.liquidityPercent !== undefined && config.liquidityPercent !== null && (typeof config.liquidityPercent !== 'number' || config.liquidityPercent < 0 || config.liquidityPercent > 100)) {
            errors.push('liquidityPercent must be a number between 0 and 100');
        }

        // useCloseToday (boolean)
        if (config.useCloseToday !== undefined && config.useCloseToday !== null && typeof config.useCloseToday !== 'boolean') {
            errors.push('useCloseToday must be a boolean');
        }

        return { valid: errors.length === 0, errors: errors };
    }

    // ---------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------

    /**
     * Add a new group (base or derived).
     * @param {object} config
     * @param {boolean} [config.isDerived] - true for derived groups
     * @param {string} [config.parentId] - parent derived group id
     * @param {string} [config.baseGroupId] - referenced base group id (derived only)
     * @param {object} [config.productMask] - product mask
     * @param {string[]} [config.overrides] - field keys that differ from baseGroup (derived only, computed)
     * @returns {string} new id
     * @throws {Error} if validation fails
     */
    function add(config) {
        var result = validate(config);
        if (!result.valid) {
            throw new Error('Validation failed: ' + result.errors.join('; '));
        }

        // Build item from FIELD_SCHEMA — same shape for base and derived
        var isDerived = !!(config.isDerived);
        var itemId = (config.id && typeof config.id === 'string' && config.id.trim()) ? config.id.trim() : _uuid();
        if (_findIndex(itemId) !== -1) {
            throw new Error('Duplicate group id: ' + itemId);
        }
        var item = { id: itemId, name: config.name.trim(), isDerived: isDerived };
        for (var i = 0; i < FIELD_SCHEMA.length; i++) {
            var f = FIELD_SCHEMA[i];
            if (f.key === 'id' || f.key === 'name' || f.key === 'isDerived') continue;
            if (config.hasOwnProperty(f.key)) {
                item[f.key] = (f.type === 'object') ? _deepCopy(config[f.key]) : config[f.key];
            } else {
                item[f.key] = (f.type === 'object') ? _deepCopy(f.default) : f.default;
            }
        }
        if (isDerived) {
            ['feeMode', 'feeRate', 'feeMap', 'feeSensitivity', 'useCloseToday', 'rebalanceMode', 'liquidityMode', 'liquidityPercent'].forEach(function(key) {
                if (!config.hasOwnProperty(key)) item[key] = null;
            });
        }

        _items.push(item);
        _emit('groupsChanged', { action: 'add', id: item.id, isDerived: isDerived });
        return item.id;
    }

    /**
     * Get a deep copy of a base group by id.
     * @param {string} id
     * @returns {object|null}
     */
    function get(id) {
        var idx = _findIndex(id);
        if (idx === -1) return null;
        return _deepCopy(_items[idx]);
    }

    /**
     * Get deep copies of all base groups.
     * @returns {object[]}
     */
    function getAll() {
        return _deepCopy(_items);
    }

    /**
     * Partially update a group.
     * - For base groups: auto sets needsRegenerate=true when groupCount changes.
     * - For derived groups: cycle detection on parentId change.
     * @param {string} id
     * @param {object} patch
     * @returns {object} updated item (deep copy)
     * @throws {Error} if not found or validation fails
     */
    function update(id, patch) {
        var idx = _findIndex(id);
        if (idx === -1) throw new Error('Group not found: ' + id);

        // Cycle detection for parentId change on derived groups
        if ('parentId' in patch && patch.parentId !== null && patch.parentId !== _items[idx].parentId) {
            var newParentIdx = _findIndex(patch.parentId);
            if (newParentIdx === -1) {
                throw new Error('New parentId references a non-existent group: ' + patch.parentId);
            }
            if (_wouldCycle(id, patch.parentId)) {
                throw new Error('Cannot reparent: would create a cycle');
            }
        }

        // Validate the patch against existing item merged with patch
        var merged = _deepCopy(_items[idx]);
        Object.keys(patch).forEach(function(key) {
            merged[key] = patch[key];
        });
        var result = validate(merged);
        if (!result.valid) {
            throw new Error('Validation failed: ' + result.errors.join('; '));
        }

        var needsRegen = false;
        if (!_items[idx].isDerived && 'groupCount' in patch && patch.groupCount !== _items[idx].groupCount) {
            needsRegen = true;
        }

        Object.keys(patch).forEach(function(key) {
            var entry = FIELD_BY_KEY[key];
            if (entry && entry.type === 'object') {
                _items[idx][key] = _deepCopy(patch[key]);
            } else {
                _items[idx][key] = patch[key];
            }
        });

        if (needsRegen) {
            _items[idx].needsRegenerate = true;
        }

        _emit('groupsChanged', { action: 'update', id: id, needsRegenerate: needsRegen, isDerived: _items[idx].isDerived });
        return _deepCopy(_items[idx]);
    }

    /**
     * Remove a group by id. Also cascades to all descendants (if derived).
     * @param {string} id
     * @returns {object} removed item
     * @throws {Error} if not found
     */
    function remove(id) {
        var idx = _findIndex(id);
        if (idx === -1) throw new Error('Group not found: ' + id);

        // Cascade: remove all descendants
        var idsToRemove = _collectDescendantIds(id);
        var removed = _buildTreeNode(id);

        // Remove in reverse order (descendants first) to avoid index shifts
        for (var r = _items.length - 1; r >= 0; r--) {
            if (idsToRemove.indexOf(_items[r].id) !== -1) {
                _items.splice(r, 1);
            }
        }

        _emit('groupsChanged', { action: 'remove', id: id, cascadeIds: idsToRemove });
        return _deepCopy(removed);
    }

    /**
     * Get a shallow summary list for dropdowns, etc.
     * @returns {{id: string, name: string, testerId: string, factorAlias: string}[]}
     */
    function list() {
        return _items.map(function(item) {
            return {
                id: item.id,
                name: item.name,
                testerId: item.testerId,
                factorAlias: item.factorAlias,
            };
        });
    }

    /**
     * Reset all internal state (useful for testing).
     */
    function _reset() {
        _items = [];
        _idCounter = 0;
    }

    // ---------------------------------------------------------------------------
    // Tree structure methods (work on all groups, but meaningful for derived)
    // ---------------------------------------------------------------------------

    /**
     * Get direct children of a group (by parentId).
     * @param {string} parentId
     * @returns {object[]} deep copies
     */
    function getChildren(parentId) {
        if (!parentId) return [];
        var result = [];
        for (var i = 0; i < _items.length; i++) {
            if (_items[i].parentId === parentId) {
                result.push(_deepCopy(_items[i]));
            }
        }
        return result;
    }

    /**
     * Get all root groups (parentId === null).
     * Optionally filter by isDerived.
     * @param {boolean} [derivedOnly] - if true, only return derived roots
     * @returns {object[]} deep copies
     */
    function getRoots(derivedOnly) {
        var result = [];
        for (var i = 0; i < _items.length; i++) {
            if (_items[i].parentId !== null) continue;
            if (derivedOnly && !_items[i].isDerived) continue;
            result.push(_deepCopy(_items[i]));
        }
        return result;
    }

    /**
     * Recursively collect all descendant IDs of a group (inclusive).
     * @param {string} id
     * @returns {string[]}
     */
    function getDescendants(id) {
        if (_findIndex(id) === -1) throw new Error('Group not found: ' + id);
        return _collectDescendantIds(id);
    }

    function _collectDescendantIds(id) {
        var result = [id];
        for (var i = 0; i < _items.length; i++) {
            if (_items[i].parentId === id) {
                result = result.concat(_collectDescendantIds(_items[i].id));
            }
        }
        return result;
    }

    /**
     * Build a tree node (with children) for a given id.
     * @param {string} id
     * @returns {object|null}
     */
    function _buildTreeNode(id) {
        var idx = _findIndex(id);
        if (idx === -1) return null;
        var node = _deepCopy(_items[idx]);
        node.children = [];
        for (var i = 0; i < _items.length; i++) {
            if (_items[i].parentId === id) {
                var childTree = _buildTreeNode(_items[i].id);
                if (childTree) node.children.push(childTree);
            }
        }
        return node;
    }

    /**
     * Get the tree structure starting from root nodes (derived only by default).
     * Each node includes a `children` array of nested sub-trees.
     * @param {boolean} [derivedOnly] - default true for backwards compat
     * @returns {object[]}
     */
    function getTree(derivedOnly) {
        if (derivedOnly === undefined) derivedOnly = true;
        var roots = [];
        for (var i = 0; i < _items.length; i++) {
            if (_items[i].parentId) continue;
            if (derivedOnly && !_items[i].isDerived) continue;
            roots.push(_buildTreeNode(_items[i].id));
        }
        return roots;
    }

    /**
     * Toggle the _expanded flag on a group.
     * @param {string} id
     * @returns {boolean|null} new expanded state, or null if not found
     */
    function toggleExpanded(id) {
        var idx = _findIndex(id);
        if (idx === -1) return null;
        _items[idx]._expanded = !_items[idx]._expanded;
        return _items[idx]._expanded;
    }

    /**
     * Check if targetId is an ancestor of nodeId (for cycle detection).
     */
    function _isAncestor(nodeId, targetId) {
        var node = _getRaw(nodeId);
        while (node) {
            if (node.parentId === targetId) return true;
            if (!node.parentId) return false;
            node = _getRaw(node.parentId);
        }
        return false;
    }

    /**
     * Check if newParentId would create a cycle if applied to nodeId.
     */
    function _wouldCycle(nodeId, newParentId) {
        return (nodeId === newParentId) || _isAncestor(newParentId, nodeId);
    }

    // ---------------------------------------------------------------------------
    // Event emission (delegates to GT.state.emit when available)
    // ---------------------------------------------------------------------------

    function _emit(event, data) {
        if (GT.state && typeof GT.state.emit === 'function') {
            GT.state.emit(event, data);
        }
    }

    // ---------------------------------------------------------------------------
    // Export
    // ---------------------------------------------------------------------------

    GT.datamodel.groups = {
        add: add,
        get: get,
        getAll: getAll,
        update: update,
        remove: remove,
        list: list,
        validate: validate,
        batchKey: batchKey,
        extractLetter: extractLetter,
        displayKey: displayKey,
        // Tree methods (for derived hierarchy)
        getTree: getTree,
        getDescendants: getDescendants,
        getChildren: getChildren,
        getRoots: getRoots,
        toggleExpanded: toggleExpanded,
        _reset: _reset,
    };

    GT.log('datamodel.groups loaded');
})();
