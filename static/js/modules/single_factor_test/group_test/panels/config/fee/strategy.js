/**
 * panels/config/fee/strategy.js — Fee/CloseToday/Rebalance resolution strategy
 *
 * Pure logic module. Zero DOM dependencies.
 *
 * Resolution chain (3 levels):
 *   1. Group's own top-level field (feeMode/rebalanceMode/useCloseToday — same for base & derived)
 *   2. Fall back to baseGroup (for derived groups via baseGroupId)
 *   3. Global default
 *
 * Derived groups use the exact same fields as base groups (feeMode, feeRate, feeMap,
 * useCloseToday, rebalanceMode). The only difference is that derived groups have an
 * `overrides` array tracking which fields differ from their baseGroup.
 *
 * Dependencies:
 *   - GT.datamodel.groups (get)
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
        if (GT.datamodel.groups && GT.datamodel.groups.get) {
            return GT.datamodel.groups.get(id);
        }
        return null;
    }

    function _getBG(id) {
        if (GT.datamodel.groups && GT.datamodel.groups.get) {
            return GT.datamodel.groups.get(id);
        }
        return null;
    }

    // ---------------------------------------------------------------------------
    // Config field names that derive can differ on (compared to base group)
    // ---------------------------------------------------------------------------

    var DIFFABLE_KEYS = ['feeMode', 'feeRate', 'feeMap', 'feeSensitivity', 'useCloseToday', 'rebalanceMode'];

    // ---------------------------------------------------------------------------
    // Core resolution
    // ---------------------------------------------------------------------------

    /**
     * Resolve a config value for a derived node by walking the chain.
     *
     * Chain:
     *   1. Check node's own field — if it differs from default, use it
     *   2. Recurse to parent derived group (if any)
     *   3. Fall back to base group
     *   4. Default value
     *
     * @param {string} nodeId    - derived group id
     * @param {string} fieldKey  - e.g. 'useCloseToday', 'rebalanceMode'
     * @param {*}      defaultValue
     * @returns {*} resolved value
     */
    function resolveParam(nodeId, fieldKey, defaultValue) {
        var node = _getDG(nodeId);
        if (!node) throw new Error('Derived group not found: ' + nodeId);

        // Level 1: Check node's own field (truthy or explicitly set)
        var val = node[fieldKey];
        if (val !== undefined && val !== null) {
            return _deepCopy(val);
        }

        // Level 2: Recurse to parent (skip batch organisational nodes)
        if (node.parentId) {
            var parentNode = _getDG(node.parentId);
            if (!parentNode || parentNode.baseGroupId !== '__batch__') {
                return resolveParam(node.parentId, fieldKey, defaultValue);
            }
        }

        // Level 3: Fall back to base group
        if (node.baseGroupId && node.baseGroupId !== '__batch__') {
            var bg = _getBG(node.baseGroupId);
            if (bg && bg[fieldKey] !== undefined && bg[fieldKey] !== null) {
                return _deepCopy(bg[fieldKey]);
            }
        }

        // Level 4: Default
        return defaultValue;
    }

    /**
     * Resolve the full fee configuration for a derived group.
     * Derived groups store feeMode/feeRate/feeMap directly — same as base groups.
     * @param {string} nodeId
     * @returns {{mode: string, rate: number|null, feeMap: object|null}}
     */
    function resolveFee(nodeId) {
        var node = _getDG(nodeId);
        if (!node) throw new Error('Derived group not found: ' + nodeId);

        // Node's own fee config takes priority (if set to something other than 'none')
        if (node.feeMode && node.feeMode !== 'none') {
            return {
                mode: node.feeMode,
                rate: node.feeRate !== undefined ? node.feeRate : null,
                feeMap: node.feeMap !== undefined ? _deepCopy(node.feeMap) : null,
                sensitivity: node.feeSensitivity !== undefined ? node.feeSensitivity : 1,
            };
        }

        // Recurse parent (skip batch organisational nodes)
        if (node.parentId) {
            var parentNode = _getDG(node.parentId);
            if (parentNode && parentNode.baseGroupId !== '__batch__') {
                return resolveFee(node.parentId);
            }
        }

        // Fall back to base group
        if (node.baseGroupId && node.baseGroupId !== '__batch__') {
            var bg = _getBG(node.baseGroupId);
            if (bg) {
                return {
                    mode: bg.feeMode || 'none',
                    rate: bg.feeRate !== undefined ? bg.feeRate : null,
                    feeMap: bg.feeMap !== undefined ? _deepCopy(bg.feeMap) : null,
                    sensitivity: bg.feeSensitivity !== undefined ? bg.feeSensitivity : 1,
                };
            }
        }

        // Default
        return { mode: 'none', rate: null, feeMap: null, sensitivity: 1 };
    }

    /**
     * Resolve close-today for a derived group.
     * @param {string} nodeId
     * @returns {boolean}
     */
    function resolveCloseToday(nodeId) {
        return resolveParam(nodeId, 'useCloseToday', false);
    }

    /**
     * Resolve rebalance mode for a derived group.
     * @param {string} nodeId
     * @returns {string}
     */
    function resolveRebalance(nodeId) {
        return resolveParam(nodeId, 'rebalanceMode', 'each_period');
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
        if (!node || !node.isDerived) return;

        // Compare node's config fields against base group; collect differing keys
        if (node.baseGroupId && node.baseGroupId !== '__batch__') {
            var bg = _getBG(node.baseGroupId);
            if (bg) {
                DIFFABLE_KEYS.forEach(function(key) {
                    var nodeVal = node[key];
                    var bgVal = bg[key];
                    if (JSON.stringify(nodeVal) !== JSON.stringify(bgVal)) {
                        mods.push({
                            nodeId: node.id,
                            field: key,
                            value: nodeVal !== undefined ? _deepCopy(nodeVal) : undefined,
                        });
                    }
                });
            }
        }

        // Recurse to children
        var descendants = GT.datamodel.groups.getDescendants ?
            GT.datamodel.groups.getDescendants(node.id).slice(1) : [];

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
