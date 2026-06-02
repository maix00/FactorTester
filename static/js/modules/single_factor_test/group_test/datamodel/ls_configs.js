/**
 * ls_configs.js — Long-Short config CRUD data model
 *
 * Pure logic module. Zero DOM dependencies.
 * Part of Phase 1 datamodel layer for Issue #85.
 *
 * Data shape:
 *   { id, name, longGroupId, shortGroupId, feeMode, feeRate,
 *     useCloseToday, rebalanceMode, needsRegenerate, metadata }
 *
 * Dependencies:
 *   - GT.datamodel.groups (for longGroupId/shortGroupId validation, unified storage)
 *   - GT.state.emit (for lsConfigsChanged events)
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.datamodel) { GT.datamodel = {}; }

    // ---------------------------------------------------------------------------
    // Internal state
    // ---------------------------------------------------------------------------

    var _items = [];
    var _idCounter = 0;

    var VALID_FEE_MODES = ['inherit', 'override'];
    var VALID_REBALANCE_MODES = ['each_period', 'buy_and_hold', 'recycle'];

    // ---------------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------------

    function _uuid() {
        _idCounter += 1;
        return 'ls_' + Date.now().toString(36) + '_' + _idCounter.toString(36);
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

    function _groupAlias(group) {
        if (!group) return '';
        if (group.shortAlias) return group.shortAlias;
        if (!group.isDerived) return group.name || group.id || '';
        return _deriveDerivedAlias(group);
    }

    function _deriveDerivedAlias(node) {
        if (!node || !node.baseGroupId) return node ? (node.name || node.id || '') : '';
        var groups = GT.datamodel.groups;
        var base = groups && groups.get ? groups.get(node.baseGroupId) : null;
        var baseAlias = _groupAlias(base) || node.baseGroupId || '';
        var allGroups = groups && groups.getAll ? groups.getAll() : [];
        var siblings = allGroups.filter(function(item) {
            return item && item.isDerived && item.baseGroupId === node.baseGroupId && item.parentId === node.parentId;
        });
        var pos = siblings.findIndex(function(item) { return item.id === node.id; });
        var suffix = pos >= 0 ? String(pos + 1) : (node.name || node.id || '?');
        if (node.parentId) {
            var parent = groups && groups.get ? groups.get(node.parentId) : null;
            return (_groupAlias(parent) || baseAlias) + ':' + suffix;
        }
        return baseAlias + ':' + suffix;
    }

    function _deriveShortAlias(config) {
        if (config.shortAlias && typeof config.shortAlias === 'string' && config.shortAlias.trim()) {
            return config.shortAlias.trim();
        }
        return _deriveLegShortAlias(config);
    }

    function _deriveLegShortAlias(config) {
        var groups = GT.datamodel.groups;
        var longGroup = groups && groups.get(config.longGroupId);
        var shortGroup = groups && groups.get(config.shortGroupId);
        var longAlias = _groupAlias(longGroup) || 'Long';
        var shortAlias = _groupAlias(shortGroup) || 'Short';
        return longAlias + '/' + shortAlias;
    }

    // ---------------------------------------------------------------------------
    // Validation
    // ---------------------------------------------------------------------------

    /**
     * Validate an LS config.
     * @param {object} config
     * @param {string} [excludeId] - id to exclude (for updates)
     * @returns {{valid: boolean, errors: string[]}}
     */
    function validate(config, excludeId) {
        var errors = [];

        if (!config || typeof config !== 'object') {
            return { valid: false, errors: ['config must be an object'] };
        }

        // Required: name
        if (!config.name || typeof config.name !== 'string' || !config.name.trim()) {
            errors.push('name is required (non-empty string)');
        }

        // Required: longGroupId
        if (!config.longGroupId || typeof config.longGroupId !== 'string') {
            errors.push('longGroupId is required (non-empty string)');
        } else if (GT.datamodel.groups && GT.datamodel.groups.get) {
            var longDg = GT.datamodel.groups.get(config.longGroupId);
            if (!longDg) {
                errors.push('longGroupId references a non-existent group: ' + config.longGroupId);
            }
        }

        // Required: shortGroupId
        if (!config.shortGroupId || typeof config.shortGroupId !== 'string') {
            errors.push('shortGroupId is required (non-empty string)');
        } else if (GT.datamodel.groups && GT.datamodel.groups.get) {
            var shortDg = GT.datamodel.groups.get(config.shortGroupId);
            if (!shortDg) {
                errors.push('shortGroupId references a non-existent group: ' + config.shortGroupId);
            }
        }

        // feeMode: optional, must be valid if provided
        if (config.feeMode !== undefined && VALID_FEE_MODES.indexOf(config.feeMode) === -1) {
            errors.push('feeMode must be one of: ' + VALID_FEE_MODES.join(', '));
        }

        // feeRate: optional, non-negative if provided
        if (config.feeRate !== undefined && config.feeRate !== null && (typeof config.feeRate !== 'number' || config.feeRate < 0)) {
            errors.push('feeRate must be a non-negative number or null');
        }

        // rebalanceMode: optional, must be valid if provided
        if (config.rebalanceMode !== undefined && config.rebalanceMode !== null && VALID_REBALANCE_MODES.indexOf(config.rebalanceMode) === -1) {
            errors.push('rebalanceMode must be one of: ' + VALID_REBALANCE_MODES.join(', ') + ' or null');
        }

        // metadata: optional, must be object if provided
        if (config.metadata !== undefined && (typeof config.metadata !== 'object' || config.metadata === null || Array.isArray(config.metadata))) {
            errors.push('metadata must be a plain object');
        }

        return { valid: errors.length === 0, errors: errors };
    }

    // ---------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------

    /**
     * Add a new LS config.
     * @param {object} config
     * @returns {object} created config (deep copy)
     * @throws {Error} if validation fails
     */
    function add(config) {
        var result = validate(config);
        if (!result.valid) {
            throw new Error('Validation failed: ' + result.errors.join('; '));
        }

        var item = {
            id: (typeof config.id === 'string' && config.id.trim()) ? config.id : _uuid(),
            name: config.name.trim(),
            shortAlias: _deriveShortAlias(config),
            longGroupId: config.longGroupId,
            shortGroupId: config.shortGroupId,
            feeMode: config.feeMode || 'inherit',
            feeRate: config.feeRate !== undefined ? config.feeRate : null,
            useCloseToday: config.useCloseToday !== undefined ? config.useCloseToday : null,
            rebalanceMode: config.rebalanceMode !== undefined ? config.rebalanceMode : null,
            needsRegenerate: true,
            metadata: config.metadata !== undefined ? _deepCopy(config.metadata) : {},
        };

        _items.push(item);
        _emit('lsConfigsChanged', { action: 'add', id: item.id });
        return _deepCopy(item);
    }

    /**
     * Get a deep copy of an LS config by id.
     * @param {string} id
     * @returns {object|null}
     */
    function get(id) {
        var idx = _findIndex(id);
        if (idx === -1) return null;
        return _deepCopy(_items[idx]);
    }

    /**
     * Get deep copies of all LS configs.
     * @returns {object[]}
     */
    function getAll() {
        return _deepCopy(_items);
    }

    /**
     * Partially update an LS config.
     * @param {string} id
     * @param {object} patch
     * @returns {object} updated config (deep copy)
     * @throws {Error} if not found or validation fails
     */
    function update(id, patch) {
        var idx = _findIndex(id);
        if (idx === -1) throw new Error('LS config not found: ' + id);

        var merged = _deepCopy(_items[idx]);
        Object.keys(patch).forEach(function(key) {
            merged[key] = patch[key];
        });
        var result = validate(merged, id);
        if (!result.valid) {
            throw new Error('Validation failed: ' + result.errors.join('; '));
        }

        Object.keys(patch).forEach(function(key) {
            _items[idx][key] = patch[key];
        });
        if ('longGroupId' in patch || 'shortGroupId' in patch || 'shortAlias' in patch) {
            _items[idx].shortAlias = ('shortAlias' in patch) ? _deriveShortAlias(_items[idx]) : _deriveLegShortAlias(_items[idx]);
        }

        _emit('lsConfigsChanged', { action: 'update', id: id });
        return _deepCopy(_items[idx]);
    }

    /**
     * Remove an LS config by id.
     * @param {string} id
     * @returns {object} removed config
     * @throws {Error} if not found
     */
    function remove(id) {
        var idx = _findIndex(id);
        if (idx === -1) throw new Error('LS config not found: ' + id);

        var removed = _items.splice(idx, 1)[0];
        _emit('lsConfigsChanged', { action: 'remove', id: id });
        return _deepCopy(removed);
    }

    /**
     * Mark an LS config as stale (needs regeneration).
     * @param {string} id
     * @returns {object} updated config
     * @throws {Error} if not found
     */
    function markStale(id) {
        var idx = _findIndex(id);
        if (idx === -1) throw new Error('LS config not found: ' + id);

        _items[idx].needsRegenerate = true;
        _emit('lsConfigsChanged', { action: 'markStale', id: id });
        return _deepCopy(_items[idx]);
    }

    /**
     * Get all LS configs that reference a given derived group.
     * @param {string} derivedGroupId
     * @returns {object[]} matching configs (deep copies)
     */
    function findByDerivedGroup(derivedGroupId) {
        return _items.filter(function(item) {
            return item.longGroupId === derivedGroupId || item.shortGroupId === derivedGroupId;
        }).map(function(item) {
            return _deepCopy(item);
        });
    }

    /**
     * Get a shallow summary list.
     * @returns {{id: string, name: string, longGroupId: string, shortGroupId: string}[]}
     */
    function list() {
        return _items.map(function(item) {
            return {
                id: item.id,
                name: item.name,
                longGroupId: item.longGroupId,
                shortGroupId: item.shortGroupId,
            };
        });
    }

    function parseCsvNumbers(value) {
        return String(value || '').split(',')
            .map(function(x) { return parseFloat(x.trim()); })
            .filter(function(x) { return !isNaN(x) && isFinite(x); });
    }

    function buildLegacyLegs(groupsValue, weightsValue, defaultGroups) {
        var groups = parseCsvNumbers(groupsValue);
        if (!groups.length) groups = defaultGroups || [];
        var weights = parseCsvNumbers(weightsValue);
        if (!weights.length) weights = groups.map(function() { return 1; });
        return groups.map(function(groupNo, idx) {
            return {
                group: Math.max(0, Math.floor(groupNo) - 1),
                weight: weights[idx] != null ? weights[idx] : weights[weights.length - 1]
            };
        }).filter(function(leg) { return leg.weight > 0; });
    }

    function defaultLegacyDefinition() {
        return { id: 'LS1', name: 'Long-Short', longGroups: '1', longWeights: '1', shortGroups: '', shortWeights: '1' };
    }

    function buildLegacyPayload(def, nGroups) {
        def = def || defaultLegacyDefinition();
        return {
            name: (def.name || '').trim() || 'Long-Short',
            long: buildLegacyLegs(def.longGroups || '1', def.longWeights || '1', [1]),
            short: buildLegacyLegs(def.shortGroups || '', def.shortWeights || '1', [nGroups])
        };
    }

    function buildLegacyPayloads(definitions, nGroups) {
        var defs = definitions && definitions.length ? definitions : [defaultLegacyDefinition()];
        return defs.map(function(def) {
            return buildLegacyPayload(def, nGroups);
        });
    }

    /**
     * Reset all internal state (for testing).
     */
    function _reset() {
        _items = [];
        _idCounter = 0;
    }

    // ---------------------------------------------------------------------------
    // Event emission
    // ---------------------------------------------------------------------------

    function _emit(event, data) {
        if (GT.state && typeof GT.state.emit === 'function') {
            GT.state.emit(event, data);
        }
    }

    // ---------------------------------------------------------------------------
    // Export
    // ---------------------------------------------------------------------------

    GT.datamodel.ls_configs = {
        add: add,
        get: get,
        getAll: getAll,
        update: update,
        remove: remove,
        markStale: markStale,
        findByDerivedGroup: findByDerivedGroup,
        list: list,
        parseCsvNumbers: parseCsvNumbers,
        buildLegacyLegs: buildLegacyLegs,
        defaultLegacyDefinition: defaultLegacyDefinition,
        buildLegacyPayload: buildLegacyPayload,
        buildLegacyPayloads: buildLegacyPayloads,
        validate: validate,
        _reset: _reset,
    };

    GT.log('datamodel.ls_configs loaded');
})();
