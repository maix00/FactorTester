/**
 * registrations.js — Group registration CRUD data model
 *
 * Pure logic module. Zero DOM dependencies.
 * Part of Phase 1 datamodel layer for Issue #85.
 *
 * A registration maps an LS config to a set of (derivedGroup, side, weight) triples.
 *
 * Data shape:
 *   _registrations: { lsConfigId: [{ groupId, side, weight }], ... }
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.datamodel) { GT.datamodel = {}; }

    var _registrations = {};  // { lsConfigId: [{ groupId, side, weight }] }

    function _deepCopy(obj) {
        return JSON.parse(JSON.stringify(obj));
    }

    // ---------------------------------------------------------------------------
    // Validation
    // ---------------------------------------------------------------------------

    var VALID_SIDES = ['long', 'short'];

    // ---------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------

    /**
     * Register a derived group to an LS config side.
     *
     * @param {string} lsConfigId
     * @param {string} groupId    - derived group id
     * @param {string} side       - 'long' or 'short'
     * @param {number} [weight]   - default 1.0
     * @returns {object} the registration entry { groupId, side, weight }
     * @throws {Error} if invalid
     */
    function register(lsConfigId, groupId, side, weight) {
        if (!lsConfigId) throw new Error('lsConfigId is required');
        if (!groupId) throw new Error('groupId is required');
        if (VALID_SIDES.indexOf(side) === -1) {
            throw new Error('side must be "long" or "short", got: ' + side);
        }

        var w = (weight !== undefined) ? weight : 1.0;
        if (typeof w !== 'number' || w <= 0) {
            throw new Error('weight must be a positive number');
        }

        if (!_registrations[lsConfigId]) {
            _registrations[lsConfigId] = [];
        }

        // Check for duplicate (same group + side)
        var existingIdx = -1;
        for (var i = 0; i < _registrations[lsConfigId].length; i++) {
            if (_registrations[lsConfigId][i].groupId === groupId && _registrations[lsConfigId][i].side === side) {
                existingIdx = i;
                break;
            }
        }

        if (existingIdx !== -1) {
            // Update existing
            _registrations[lsConfigId][existingIdx].weight = w;
        } else {
            _registrations[lsConfigId].push({ groupId: groupId, side: side, weight: w });
        }

        _emit('registrationsChanged', { action: 'register', lsConfigId: lsConfigId, groupId: groupId, side: side });
        return { groupId: groupId, side: side, weight: w };
    }

    /**
     * Unregister a derived group from an LS config.
     *
     * @param {string} lsConfigId
     * @param {string} groupId
     * @param {string} [side] - if omitted, remove all sides for this group
     * @throws {Error} if not found
     */
    function unregister(lsConfigId, groupId, side) {
        if (!_registrations[lsConfigId]) {
            throw new Error('No registrations for LS config: ' + lsConfigId);
        }

        var before = _registrations[lsConfigId].length;

        _registrations[lsConfigId] = _registrations[lsConfigId].filter(function(reg) {
            if (reg.groupId !== groupId) return true;
            if (side && reg.side !== side) return true;
            return false;
        });

        if (_registrations[lsConfigId].length === before && !side) {
            throw new Error('Registration not found: ' + groupId + ' for ' + lsConfigId);
        }

        _emit('registrationsChanged', { action: 'unregister', lsConfigId: lsConfigId, groupId: groupId, side: side });
    }

    /**
     * Get all registrations for an LS config.
     * @param {string} lsConfigId
     * @returns {object[]} array of { groupId, side, weight } (deep copy)
     */
    function getRegistrations(lsConfigId) {
        return _deepCopy(_registrations[lsConfigId] || []);
    }

    /**
     * Find all LS configs that reference a given derived group.
     *
     * @param {string} groupId
     * @returns {object[]} array of { lsConfigId, side, weight }
     */
    function getRegistrationsForGroup(groupId) {
        var result = [];
        Object.keys(_registrations).forEach(function(lsId) {
            var regs = _registrations[lsId];
            for (var i = 0; i < regs.length; i++) {
                if (regs[i].groupId === groupId) {
                    result.push({
                        lsConfigId: lsId,
                        side: regs[i].side,
                        weight: regs[i].weight,
                    });
                }
            }
        });
        return result;
    }

    /**
     * Remove all registrations for a given LS config.
     * @param {string} lsConfigId
     */
    function removeAllForLs(lsConfigId) {
        delete _registrations[lsConfigId];
        _emit('registrationsChanged', { action: 'removeAllForLs', lsConfigId: lsConfigId });
    }

    /**
     * Remove all registrations that reference a given derived group.
     * @param {string} groupId
     * @returns {number} count of removed registrations
     */
    function removeAllForGroup(groupId) {
        var count = 0;
        Object.keys(_registrations).forEach(function(lsId) {
            var before = _registrations[lsId].length;
            _registrations[lsId] = _registrations[lsId].filter(function(reg) {
                return reg.groupId !== groupId;
            });
            count += before - _registrations[lsId].length;
        });
        if (count > 0) {
            _emit('registrationsChanged', { action: 'removeAllForGroup', groupId: groupId, count: count });
        }
        return count;
    }

    /**
     * Get all LS config IDs that have any registrations.
     * @returns {string[]}
     */
    function getRegisteredLsIds() {
        return Object.keys(_registrations);
    }

    /**
     * Get a summary of all registrations.
     * @returns {{lsConfigId: string, registrations: {groupId: string, side: string, weight: number}[]}[]}
     */
    function getAll() {
        return Object.keys(_registrations).map(function(lsId) {
            return {
                lsConfigId: lsId,
                registrations: _deepCopy(_registrations[lsId]),
            };
        });
    }

    /**
     * Reset all internal state (for testing).
     */
    function _reset() {
        _registrations = {};
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

    GT.datamodel.registrations = {
        register: register,
        unregister: unregister,
        getRegistrations: getRegistrations,
        getRegistrationsForGroup: getRegistrationsForGroup,
        removeAllForLs: removeAllForLs,
        removeAllForGroup: removeAllForGroup,
        getRegisteredLsIds: getRegisteredLsIds,
        getAll: getAll,
        _reset: _reset,
    };

    GT.log('datamodel.registrations loaded');
})();