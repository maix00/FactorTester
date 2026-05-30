/**
 * base_groups.js — Base group CRUD data model
 *
 * Pure logic module. Zero DOM dependencies.
 * Part of Phase 1 datamodel layer for Issue #85.
 *
 * Data shape:
 *   { id, name, testerId, factorAlias, groupCount, groupIndex, isAllGroups,
 *     feeMode, feeRate, feeMap, useCloseToday, rebalanceMode, needsRegenerate }
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

    // ---------------------------------------------------------------------------
    // Validation
    // ---------------------------------------------------------------------------

    var VALID_FEE_MODES = ['none', 'uniform', 'per_product', 'custom'];
    var VALID_REBALANCE_MODES = ['each_period', 'buy_and_hold', 'recycle'];

    /**
     * Validate a base group config.
     * @param {object} config - raw config to validate
     * @returns {{valid: boolean, errors: string[]}}
     */
    function validate(config) {
        var errors = [];

        if (!config || typeof config !== 'object') {
            return { valid: false, errors: ['config must be an object'] };
        }

        // Required string fields
        if (!config.name || typeof config.name !== 'string' || !config.name.trim()) {
            errors.push('name is required (non-empty string)');
        }
        if (!config.testerId || typeof config.testerId !== 'string' || !config.testerId.trim()) {
            errors.push('testerId is required (non-empty string)');
        }
        if (!config.factorAlias || typeof config.factorAlias !== 'string' || !config.factorAlias.trim()) {
            errors.push('factorAlias is required (non-empty string)');
        }

        // groupCount
        if (typeof config.groupCount !== 'number' || config.groupCount < 1 || Math.floor(config.groupCount) !== config.groupCount) {
            errors.push('groupCount must be a positive integer (≥ 1)');
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
        if (config.feeMode !== undefined && VALID_FEE_MODES.indexOf(config.feeMode) === -1) {
            errors.push('feeMode must be one of: ' + VALID_FEE_MODES.join(', '));
        }

        // feeRate — only relevant for uniform mode, but always allow
        if (config.feeRate !== undefined && config.feeRate !== null && (typeof config.feeRate !== 'number' || config.feeRate < 0)) {
            errors.push('feeRate must be a non-negative number or null');
        }

        // rebalanceMode
        if (config.rebalanceMode !== undefined && VALID_REBALANCE_MODES.indexOf(config.rebalanceMode) === -1) {
            errors.push('rebalanceMode must be one of: ' + VALID_REBALANCE_MODES.join(', '));
        }

        // useCloseToday (boolean)
        if (config.useCloseToday !== undefined && typeof config.useCloseToday !== 'boolean') {
            errors.push('useCloseToday must be a boolean');
        }

        return { valid: errors.length === 0, errors: errors };
    }

    // ---------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------

    /**
     * Add a new base group.
     * @param {object} config
     * @returns {string} new id
     * @throws {Error} if validation fails
     */
    function add(config) {
        var result = validate(config);
        if (!result.valid) {
            throw new Error('Validation failed: ' + result.errors.join('; '));
        }

        var item = {
            id: _uuid(),
            name: config.name.trim(),
            testerId: config.testerId.trim(),
            factorAlias: config.factorAlias.trim(),
            groupCount: config.groupCount,
            groupIndex: config.groupIndex !== undefined ? config.groupIndex : 1,
            isAllGroups: config.isAllGroups !== undefined ? !!config.isAllGroups : false,
            feeMode: config.feeMode || 'none',
            feeRate: config.feeRate !== undefined ? config.feeRate : null,
            feeMap: config.feeMap !== undefined ? config.feeMap : null,
            useCloseToday: config.useCloseToday !== undefined ? !!config.useCloseToday : false,
            rebalanceMode: config.rebalanceMode || 'each_period',
            needsRegenerate: true,
            startDate: config.startDate || null,
            endDate: config.endDate || null,
        };

        _items.push(item);
        _emit('baseGroupsChanged', { action: 'add', id: item.id });
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
     * Partially update a base group.
     * Automatically sets needsRegenerate=true when groupCount changes.
     * @param {string} id
     * @param {object} patch
     * @returns {object} updated item (deep copy)
     * @throws {Error} if not found or validation fails
     */
    function update(id, patch) {
        var idx = _findIndex(id);
        if (idx === -1) throw new Error('Base group not found: ' + id);

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
        if ('groupCount' in patch && patch.groupCount !== _items[idx].groupCount) {
            needsRegen = true;
        }

        Object.keys(patch).forEach(function(key) {
            _items[idx][key] = patch[key];
        });

        if (needsRegen) {
            _items[idx].needsRegenerate = true;
        }

        _emit('baseGroupsChanged', { action: 'update', id: id, needsRegenerate: needsRegen });
        return _deepCopy(_items[idx]);
    }

    /**
     * Remove a base group by id.
     * @param {string} id
     * @returns {object} removed item
     * @throws {Error} if not found
     */
    function remove(id) {
        var idx = _findIndex(id);
        if (idx === -1) throw new Error('Base group not found: ' + id);

        var removed = _items.splice(idx, 1)[0];
        _emit('baseGroupsChanged', { action: 'remove', id: id });
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

    GT.datamodel.base_groups = {
        add: add,
        get: get,
        getAll: getAll,
        update: update,
        remove: remove,
        list: list,
        validate: validate,
        _reset: _reset,
    };

    GT.log('datamodel.base_groups loaded');
})();
