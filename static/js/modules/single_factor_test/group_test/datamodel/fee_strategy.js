/**
 * fee_strategy.js — Fee/CloseToday/Rebalance resolution strategy
 *
 * Pure logic module. Zero DOM dependencies.
 * Part of Phase 1 datamodel layer for Issue #85.
 *
 * Resolution chain (4 levels):
 *   1. Node's own override (if set)
 *   2. Inherit from parent derived group (recursive)
 *   3. Fall back to base group
 *   4. Global default
 *
 * Dependencies:
 *   - GT.datamodel.derived_graph (get)
 *   - GT.datamodel.base_groups (get)
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.datamodel) { GT.datamodel = {}; }

    // ---------------------------------------------------------------------------
    // Utilities
    // ---------------------------------------------------------------------------

    function _deepCopy(obj) {
        return JSON.parse(JSON.stringify(obj));
    }

    function _getDG(id) {
        if (GT.datamodel.derived_graph && GT.datamodel.derived_graph.get) {
            return GT.datamodel.derived_graph.get(id);
        }
        return null;
    }

    function _getBG(id) {
        if (GT.datamodel.base_groups && GT.datamodel.base_groups.get) {
            return GT.datamodel.base_groups.get(id);
        }
        return null;
    }

    // ---------------------------------------------------------------------------
    // Field names
    // ---------------------------------------------------------------------------

    var FIELDS = {
        feeOverride:     { parentChain: true, baseField: null,      defaultValue: function() { return { mode: 'none', rate: null, feeMap: null }; } },
        closeTodayOverride: { parentChain: true, baseField: 'useCloseToday', defaultValue: false },
        rebalanceOverride:  { parentChain: true, baseField: 'rebalanceMode',  defaultValue: 'each_period' },
    };

    // ---------------------------------------------------------------------------
    // Core resolution
    // ---------------------------------------------------------------------------

    /**
     * Resolve a parameter for a derived group node by walking the chain.
     *
     * Chain:
     *   1. Check node's own override field (e.g., feeOverride)
     *   2. If not set, recurse to parent (if any)
     *   3. If no parent, fall back to base group
     *   4. If base group also not defined, use default
     *
     * @param {string} nodeId      - derived group id
     * @param {string} overrideField - e.g. 'feeOverride', 'closeTodayOverride', 'rebalanceOverride'
     * @returns {*} resolved value
     */
    function resolveParam(nodeId, overrideField) {
        var fieldInfo = FIELDS[overrideField];
        if (!fieldInfo) {
            throw new Error('Unknown param field: ' + overrideField);
        }

        var node = _getDG(nodeId);
        if (!node) {
            throw new Error('Derived group not found: ' + nodeId);
        }

        // Level 1: Check node's own override
        if (node[overrideField] !== null && node[overrideField] !== undefined) {
            return _deepCopy(node[overrideField]);
        }

        // Level 2: Recurse to parent
        if (fieldInfo.parentChain && node.parentId) {
            return resolveParam(node.parentId, overrideField);
        }

        // Level 3: Fall back to base group
        if (node.baseGroupId && fieldInfo.baseField) {
            var bg = _getBG(node.baseGroupId);
            if (bg && bg[fieldInfo.baseField] !== undefined && bg[fieldInfo.baseField] !== null) {
                return _deepCopy(bg[fieldInfo.baseField]);
            }
        }

        // Level 4: Default
        var defVal = fieldInfo.defaultValue;
        if (typeof defVal === 'function') {
            return defVal();
        }
        return defVal;
    }

    /**
     * Resolve the full fee configuration for a derived group.
     *
     * Returns { mode, rate, feeMap }:
     *   - If baseGroup is uniform mode: mode='uniform', rate=baseGroup.feeRate
     *   - If baseGroup is per_product: mode='per_product', feeMap=baseGroup.feeMap
     *   - If baseGroup is custom: mode='custom', feeMap=baseGroup.feeMap
     *   - If baseGroup is none: mode='none'
     *   - If the node has feeOverride set, it overrides the mode/rate/feeMap
     *
     * @param {string} nodeId
     * @returns {{mode: string, rate: number|null, feeMap: object|null}}
     */
    function resolveFee(nodeId) {
        // First check if there's a feeOverride
        var node = _getDG(nodeId);
        if (!node) throw new Error('Derived group not found: ' + nodeId);

        if (node.feeOverride !== null && node.feeOverride !== undefined) {
            return _deepCopy(node.feeOverride);
        }

        // Recurse parent
        if (node.parentId) {
            return resolveFee(node.parentId);
        }

        // Fall back to base group
        if (node.baseGroupId) {
            var bg = _getBG(node.baseGroupId);
            if (bg) {
                return _buildFeeFromBaseGroup(bg);
            }
        }

        // Default
        return { mode: 'none', rate: null, feeMap: null };
    }

    function _buildFeeFromBaseGroup(bg) {
        return {
            mode: bg.feeMode || 'none',
            rate: bg.feeRate !== undefined ? bg.feeRate : null,
            feeMap: bg.feeMap !== undefined ? _deepCopy(bg.feeMap) : null,
        };
    }

    /**
     * Resolve close-today for a derived group.
     * @param {string} nodeId
     * @returns {boolean}
     */
    function resolveCloseToday(nodeId) {
        return resolveParam(nodeId, 'closeTodayOverride');
    }

    /**
     * Resolve rebalance mode for a derived group.
     * @param {string} nodeId
     * @returns {string}
     */
    function resolveRebalance(nodeId) {
        return resolveParam(nodeId, 'rebalanceOverride');
    }

    // ---------------------------------------------------------------------------
    // uniform → per_product conversion
    // ---------------------------------------------------------------------------

    /**
     * Convert a uniform fee rate to per-product feeMap.
     *
     * If the base group is in 'uniform' mode, this expands the single rate
     * into a per-product map use the provided product list.
     *
     * @param {string} baseGroupId
     * @param {string[]} productPaths - list of product paths
     * @returns {object|null} feeMap { productPath: rate, ... } or null if not uniform
     */
    function uniformToCustom(baseGroupId, productPaths) {
        var bg = _getBG(baseGroupId);
        if (!bg) throw new Error('Base group not found: ' + baseGroupId);

        if (bg.feeMode !== 'uniform') {
            return null; // not uniform mode, no conversion needed
        }

        var feeMap = {};
        var rate = bg.feeRate || 0;
        (productPaths || []).forEach(function(path) {
            feeMap[path] = rate;
        });

        return feeMap;
    }

    // ---------------------------------------------------------------------------
    // Modification diff collection
    // ---------------------------------------------------------------------------

    /**
     * Collect fee modifications from root to a given node.
     * Walks the chain from root → target, collecting any override that differs
     * from what would be inherited.
     *
     * @param {string} nodeId
     * @returns {object[]} array of { nodeId, field, value } modifications
     */
    function collectFeeModifications(nodeId) {
        var mods = [];
        var node = _getDG(nodeId);
        if (!node) throw new Error('Derived group not found: ' + nodeId);

        _collectModsForNode(nodeId, mods);
        return mods;
    }

    function _collectModsForNode(nodeId, mods) {
        var node = _getDG(nodeId);
        if (!node) return;

        // Check feeOverride
        if (node.feeOverride !== null && node.feeOverride !== undefined) {
            mods.push({
                nodeId: node.id,
                field: 'feeOverride',
                value: _deepCopy(node.feeOverride),
            });
        }

        // Check closeTodayOverride
        if (node.closeTodayOverride !== null && node.closeTodayOverride !== undefined) {
            mods.push({
                nodeId: node.id,
                field: 'closeTodayOverride',
                value: node.closeTodayOverride,
            });
        }

        // Check rebalanceOverride
        if (node.rebalanceOverride !== null && node.rebalanceOverride !== undefined) {
            mods.push({
                nodeId: node.id,
                field: 'rebalanceOverride',
                value: node.rebalanceOverride,
            });
        }

        // Recurse to children that might have overrides
        var descendants = GT.datamodel.derived_graph.getDescendants ?
            GT.datamodel.derived_graph.getDescendants(node.id).slice(1) : [];

        descendants.forEach(function(childId) {
            _collectModsForNode(childId, mods);
        });
    }

    // ---------------------------------------------------------------------------
    // LS config fee resolution
    // ---------------------------------------------------------------------------

    /**
     * Resolve fee for an LS config.
     * If lsConfig.feeMode is 'override', use its own feeRate.
     * Otherwise inherit from the long-group (or short-group) resolved fee.
     *
     * @param {string} lsConfigId
     * @returns {{mode: string, rate: number|null, feeMap: object|null}}
     */
    function resolveLsFee(lsConfigId) {
        var lsc = GT.datamodel.ls_configs && GT.datamodel.ls_configs.get ?
            GT.datamodel.ls_configs.get(lsConfigId) : null;
        if (!lsc) throw new Error('LS config not found: ' + lsConfigId);

        if (lsc.feeMode === 'override') {
            return { mode: 'uniform', rate: lsc.feeRate, feeMap: null };
        }

        // Inherit from long group
        return resolveFee(lsc.longGroupId);
    }

    // ---------------------------------------------------------------------------
    // Export
    // ---------------------------------------------------------------------------

    GT.datamodel.fee_strategy = {
        resolveParam: resolveParam,
        resolveFee: resolveFee,
        resolveCloseToday: resolveCloseToday,
        resolveRebalance: resolveRebalance,
        resolveLsFee: resolveLsFee,
        uniformToCustom: uniformToCustom,
        collectFeeModifications: collectFeeModifications,
    };

    GT.log('datamodel.fee_strategy loaded');
})();