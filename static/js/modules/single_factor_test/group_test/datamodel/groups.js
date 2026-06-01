/**
 * groups.js — Unified group CRUD data model
 *
 * Pure logic module. Zero DOM dependencies.
 * Part of Phase 1 datamodel layer for Issue #85.
 *
 * Data shape (base group / derived group):
 *   { id, name, testerId, factorAlias, groupCount, groupIndex, isAllGroups,
 *     feeMode, feeRate, feeMap, useCloseToday, rebalanceMode, needsRegenerate,
 *     startDate, endDate,
 *     // Derived-only fields:
 *     isDerived, parentId, baseGroupId, productMask, feeOverride,
 *     closeTodayOverride, rebalanceOverride, metadata,
 *     // Runtime:
 *     shortAlias, _expanded }
 *
 * Tree helpers (getTree, getDescendants, toggleExpanded, getChildren, getRoots)
 * work on ALL groups — just filter by isDerived / parentId.
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
    //   key            : property name on the group object
    //   type           : 'string' | 'number' | 'boolean' | 'object' | 'any'
    //                     - 'object' fields are deep-copied in add/update
    //   requiredFor    : 'both' | 'base' | 'derived' | 'none'
    //   defaultBase    : default value when building a base group
    //   defaultDerived : default value when building a derived group
    //   validate       : optional function(value, fullConfig) → null | errorString
    //   allowPatch     : if false, the field is immutable after add (not in patchableKeys)
    //
    // To add a new config tab field or a new derived-only override:
    //   → add ONE entry here. add(), update(), validate() all pick it up automatically.
    // =========================================================================

    var FIELD_SCHEMA = [
        // ── Identity ──
        { key: 'id',          type: 'string',  requiredFor: 'none',    defaultBase: '',    defaultDerived: '',    allowPatch: false },
        { key: 'name',        type: 'string',  requiredFor: 'both',    defaultBase: '',    defaultDerived: '',    validate: function(v) { return (!v || typeof v !== 'string' || !v.trim()) ? 'name is required (non-empty string)' : null; } },
        { key: 'isDerived',   type: 'boolean', requiredFor: 'none',    defaultBase: false, defaultDerived: true,  allowPatch: false },

        // ── Tree / lineage (meaningful for derived; null for base) ──
        { key: 'parentId',     type: 'string',  requiredFor: 'none', defaultBase: null, defaultDerived: null },
        { key: 'baseGroupId',  type: 'string',  requiredFor: 'none', defaultBase: null, defaultDerived: null,
          validate: function(v, config) {
              if (!config.isDerived) return null;
              if (!v || typeof v !== 'string') return 'baseGroupId is required for derived groups';
              if (v === '__batch__') return null; // batch-creation sentinel, resolved by caller
              if (!_getRaw(v)) return 'baseGroupId references a non-existent group: ' + v;
              return null;
          } },

        // ── Tester / factor scoping (base only) ──
        { key: 'testerId',    type: 'string',  requiredFor: 'base',   defaultBase: '',    defaultDerived: '' },
        { key: 'factorAlias', type: 'string',  requiredFor: 'base',   defaultBase: '',    defaultDerived: '' },
        { key: 'groupCount',  type: 'number',  requiredFor: 'base',   defaultBase: 5,     defaultDerived: 1,
          validate: function(v, config) {
              if (config.isDerived) return null;
              if (typeof v !== 'number' || v < 1 || Math.floor(v) !== v) return 'groupCount must be a positive integer (≥ 1)';
              return null;
          } },
        { key: 'groupIndex',  type: 'number',  requiredFor: 'none',   defaultBase: 1,     defaultDerived: 1,
          validate: function(v) {
              if (v === undefined || v === null) return null;
              if (typeof v !== 'number' || v < 1 || Math.floor(v) !== v) return 'groupIndex must be a positive integer (≥ 1)';
              return null;
          } },
        { key: 'isAllGroups', type: 'boolean', requiredFor: 'none',   defaultBase: false, defaultDerived: false },

        // ── Fee config (shared, base owns; derived inherits + may override) ──
        { key: 'feeMode',     type: 'string',  requiredFor: 'none', defaultBase: 'none', defaultDerived: 'none',
          validate: function(v) {
              if (v !== undefined && VALID_FEE_MODES.indexOf(v) === -1) return 'feeMode must be one of: ' + VALID_FEE_MODES.join(', ');
              return null;
          } },
        { key: 'feeRate',     type: 'any',     requiredFor: 'none', defaultBase: null,   defaultDerived: null,
          validate: function(v) {
              if (v !== undefined && v !== null && (typeof v !== 'number' || v < 0)) return 'feeRate must be a non-negative number or null';
              return null;
          } },
        { key: 'feeMap',      type: 'object',  requiredFor: 'none', defaultBase: null,   defaultDerived: null },

        // ── Close-today / rebalance (shared) ──
        { key: 'useCloseToday',   type: 'boolean', requiredFor: 'none', defaultBase: false,          defaultDerived: false },
        { key: 'rebalanceMode',   type: 'string',  requiredFor: 'none', defaultBase: 'each_period',  defaultDerived: 'each_period',
          validate: function(v) {
              if (v !== undefined && VALID_REBALANCE_MODES.indexOf(v) === -1) return 'rebalanceMode must be one of: ' + VALID_REBALANCE_MODES.join(', ');
              return null;
          } },

        // ── State flags ──
        { key: 'needsRegenerate', type: 'boolean', requiredFor: 'none', defaultBase: true,  defaultDerived: false, allowPatch: false },

        // ── Time range ──
        { key: 'startDate', type: 'string',  requiredFor: 'none', defaultBase: null, defaultDerived: null },
        { key: 'endDate',   type: 'string',  requiredFor: 'none', defaultBase: null, defaultDerived: null },

        // ── Display ──
        { key: 'shortAlias', type: 'string', requiredFor: 'none', defaultBase: '', defaultDerived: '' },

        // ═══════════════════════════════════════════════════════════════════
        // Derived-only overrides — add new override fields HERE
        // ═══════════════════════════════════════════════════════════════════
        { key: 'productMask',         type: 'object',  requiredFor: 'none', defaultBase: {},     defaultDerived: {} },
        { key: 'feeOverride',         type: 'any',     requiredFor: 'none', defaultBase: null,   defaultDerived: null },
        { key: 'closeTodayOverride',  type: 'any',     requiredFor: 'none', defaultBase: null,   defaultDerived: null },
        { key: 'rebalanceOverride',   type: 'any',     requiredFor: 'none', defaultBase: null,   defaultDerived: null },

        // ── Derived tree metadata ──
        { key: 'metadata',        type: 'object',  requiredFor: 'none', defaultBase: {},     defaultDerived: {} },

        // ── Runtime (never persisted) ──
        { key: '_expanded', type: 'boolean', requiredFor: 'none', defaultBase: false, defaultDerived: false, allowPatch: false },
    ];

    // Derived indexes from FIELD_SCHEMA (computed once at load)
    var FIELD_BY_KEY = {};
    var PATCHABLE_KEYS = [];
    var REQUIRED_BASE = [];
    var REQUIRED_DERIVED = [];
    var DEEP_COPY_KEYS = [];

    (function _buildSchemaIndexes() {
        for (var i = 0; i < FIELD_SCHEMA.length; i++) {
            var f = FIELD_SCHEMA[i];
            FIELD_BY_KEY[f.key] = f;
            if (f.allowPatch !== false) { PATCHABLE_KEYS.push(f.key); }
            if (f.requiredFor === 'base' || f.requiredFor === 'both') { REQUIRED_BASE.push(f.key); }
            if (f.requiredFor === 'derived' || f.requiredFor === 'both') { REQUIRED_DERIVED.push(f.key); }
            if (f.type === 'object') { DEEP_COPY_KEYS.push(f.key); }
        }
    })();

    /**
     * Build a new item from config using FIELD_SCHEMA defaults.
     * @param {object} config - raw input config
     * @returns {object} item ready to push into _items
     */
    function _buildItem(config) {
        var isDerived = !!(config.isDerived);
        var item = { id: (typeof config.id === 'string' && config.id.trim()) ? config.id : _uuid() };
        for (var i = 0; i < FIELD_SCHEMA.length; i++) {
            var f = FIELD_SCHEMA[i];
            if (f.key === 'id') continue; // already set
            if (f.key === 'isDerived') continue; // set below
            var defVal = isDerived ? f.defaultDerived : f.defaultBase;
            if (config.hasOwnProperty(f.key)) {
                item[f.key] = (f.type === 'object') ? _deepCopy(config[f.key]) : config[f.key];
            } else {
                item[f.key] = (f.type === 'object') ? _deepCopy(defVal) : defVal;
            }
        }
        // These two must reflect the actual config, not defaults
        item.isDerived = isDerived;
        item.name = (config.name || '').trim();
        return item;
    }

    /**
     * Validate config using FIELD_SCHEMA validators + required checks.
     * @returns {{valid: boolean, errors: string[]}}
     */
    function _validateBySchema(config) {
        var errors = [];
        if (!config || typeof config !== 'object') {
            return { valid: false, errors: ['config must be an object'] };
        }
        var isDerived = !!(config.isDerived);

        // Required fields
        var requiredKeys = isDerived ? REQUIRED_DERIVED : REQUIRED_BASE;
        for (var r = 0; r < requiredKeys.length; r++) {
            var rk = requiredKeys[r];
            var rv = config[rk];
            if (rv === undefined || rv === null || (typeof rv === 'string' && !rv.trim())) {
                errors.push(rk + ' is required');
            }
        }

        // Per-field validators
        for (var i = 0; i < FIELD_SCHEMA.length; i++) {
            var f = FIELD_SCHEMA[i];
            if (!f.validate) continue;
            var val = config[f.key];
            var err = f.validate(val, config);
            if (err) errors.push(err);
        }

        // parentId cycle check (done in add/update, not here)
        // groupIndex <= groupCount check
        if (config.groupIndex != null && config.groupCount != null && config.groupIndex > config.groupCount) {
            errors.push('groupIndex must not exceed groupCount');
        }

        return { valid: errors.length === 0, errors: errors };
    }

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

    // ---------------------------------------------------------------------------
    // Validation
    // ---------------------------------------------------------------------------

    var VALID_FEE_MODES = ['none', 'uniform', 'per_product', 'custom'];
    var VALID_REBALANCE_MODES = ['each_period', 'buy_and_hold', 'recycle'];

    /**
     * Validate a group config using FIELD_SCHEMA.
     * When isDerived, testerId/factorAlias/groupCount are optional (inherited from baseGroupId).
     * @param {object} config - raw config to validate
     * @returns {{valid: boolean, errors: string[]}}
     */
    function validate(config) {
        return _validateBySchema(config);
    }

    // ---------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------

    /**
     * Add a new group (base or derived) using FIELD_SCHEMA.
     * @param {object} config
     * @returns {string} new id
     * @throws {Error} if validation fails or parentId cycle detected
     */
    function add(config) {
        var result = validate(config);
        if (!result.valid) {
            throw new Error('Validation failed: ' + result.errors.join('; '));
        }

        // Cycle detection for parentId on derived groups (schema validates existence, we check cycles)
        if (config.parentId) {
            if (_wouldCycle(null, config.parentId)) {
                throw new Error('parentId would create a cycle');
            }
        }

        var item = _buildItem(config);

        _items.push(item);
        _emit('groupsChanged', { action: 'add', id: item.id, isDerived: item.isDerived });
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
            if (DEEP_COPY_KEYS.indexOf(key) !== -1) {
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
        var target = _getRaw(id);
        for (var i = 0; i < _items.length; i++) {
            var child = _items[i];
            if (child.id === id) continue;
            // Direct parent-child link, OR derived group whose baseGroupId points to a deleted base group
            if (child.parentId === id || (target && !target.isDerived && child.isDerived && child.baseGroupId === id)) {
                result = result.concat(_collectDescendantIds(child.id));
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
