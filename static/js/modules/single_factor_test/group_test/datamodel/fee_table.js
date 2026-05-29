/**
 * fee_table.js — Fee table data management model
 *
 * Pure logic module. Zero DOM dependencies.
 * Part of Phase 1 datamodel layer for Issue #85.
 *
 * Simple key-value store for per-product fee rates.
 *
 * Data shape:
 *   _feeTable: { productPath: feeRate, ... }
 *   _original: { productPath: feeRate, ... }  — snapshot for diff/reset
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.datamodel) { GT.datamodel = {}; }

    var _feeTable = {};
    var _original = null;  // reference snapshot for getModifications/reset

    // ---------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------

    /**
     * Set the full fee table. Creates an original snapshot on first call.
     *
     * @param {object} table - { productPath: feeRate, ... }
     */
    function setTable(table) {
        _feeTable = {};
        if (table && typeof table === 'object') {
            Object.keys(table).forEach(function(key) {
                var rate = table[key];
                if (typeof rate === 'number' && rate >= 0) {
                    _feeTable[key] = rate;
                }
            });
        }
        if (_original === null) {
            _original = JSON.parse(JSON.stringify(_feeTable));
        }
        _emit('feeTableChanged', { action: 'setTable' });
    }

    /**
     * Get the full fee table (deep copy).
     * @returns {object} { productPath: feeRate, ... }
     */
    function getTable() {
        return JSON.parse(JSON.stringify(_feeTable));
    }

    /**
     * Update or set a single product's fee rate.
     *
     * @param {string} productPath
     * @param {number} feeRate - must be >= 0
     * @throws {Error} if invalid
     */
    function updateFee(productPath, feeRate) {
        if (!productPath || typeof productPath !== 'string') {
            throw new Error('productPath must be a non-empty string');
        }
        if (typeof feeRate !== 'number' || feeRate < 0) {
            throw new Error('feeRate must be a non-negative number');
        }
        // Ensure original exists
        if (_original === null) {
            _original = JSON.parse(JSON.stringify(_feeTable));
        }
        _feeTable[productPath] = feeRate;
        _emit('feeTableChanged', { action: 'updateFee', productPath: productPath, feeRate: feeRate });
    }

    /**
     * Get a single product's fee rate.
     *
     * @param {string} productPath
     * @returns {number|undefined} fee rate, or undefined if not in table
     */
    function getFee(productPath) {
        return _feeTable[productPath];
    }

    /**
     * Get modifications since the original snapshot.
     * Returns only products whose fee rate differs from the original.
     *
     * @returns {object} { modified: { productPath: { old: number|null, new: number } }, added: { productPath: number }, removed: { productPath: number } }
     */
    function getModifications() {
        var ref = _original || {};
        var current = _feeTable;
        var result = { modified: {}, added: {}, removed: {} };

        // Check modified and added
        Object.keys(current).forEach(function(key) {
            if (ref.hasOwnProperty(key)) {
                if (ref[key] !== current[key]) {
                    result.modified[key] = { old: ref[key], new: current[key] };
                }
            } else {
                result.added[key] = current[key];
            }
        });

        // Check removed
        Object.keys(ref).forEach(function(key) {
            if (!current.hasOwnProperty(key)) {
                result.removed[key] = ref[key];
            }
        });

        return result;
    }

    /**
     * Check if there are any modifications since the original snapshot.
     * @returns {boolean}
     */
    function hasModifications() {
        var mods = getModifications();
        return Object.keys(mods.modified).length > 0 ||
               Object.keys(mods.added).length > 0 ||
               Object.keys(mods.removed).length > 0;
    }

    /**
     * Reset to the original snapshot.
     * @returns {number} count of reverted entries
     */
    function resetToOriginal() {
        var mods = getModifications();
        var count = Object.keys(mods.modified).length + Object.keys(mods.added).length + Object.keys(mods.removed).length;
        _feeTable = _original ? JSON.parse(JSON.stringify(_original)) : {};
        _emit('feeTableChanged', { action: 'resetToOriginal', reverted: count });
        return count;
    }

    /**
     * Get all product paths in the fee table.
     * @returns {string[]}
     */
    function getProductPaths() {
        return Object.keys(_feeTable);
    }

    /**
     * Remove a product from the fee table.
     * @param {string} productPath
     */
    function removeProduct(productPath) {
        if (_original === null) {
            _original = JSON.parse(JSON.stringify(_feeTable));
        }
        delete _feeTable[productPath];
        _emit('feeTableChanged', { action: 'removeProduct', productPath: productPath });
    }

    /**
     * Reset all internal state (for testing).
     */
    function _reset() {
        _feeTable = {};
        _original = null;
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

    GT.datamodel.fee_table = {
        setTable: setTable,
        getTable: getTable,
        updateFee: updateFee,
        getFee: getFee,
        getModifications: getModifications,
        hasModifications: hasModifications,
        resetToOriginal: resetToOriginal,
        getProductPaths: getProductPaths,
        removeProduct: removeProduct,
        _reset: _reset,
    };

    GT.log('datamodel.fee_table loaded');
})();