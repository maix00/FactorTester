/**
 * derived_graph.js — Derived group compatibility wrapper
 *
 * ALL storage is unified in GT.datamodel.groups.
 * This file is a thin forwarding layer:
 *   - add() → base_groups.add({...config, isDerived:true})
 *   - get/getAll/update/remove → delegate to base_groups
 *   - getTree/getDescendants/toggleExpanded → delegate to base_groups
 *   - Events: also emits derivedGraphChanged for backward compat
 *
 * All groups (base + derived) share one ID space (bg_*),
 * distinguished by isDerived:true and parentId.
 *
 * Depends on: GT.datamodel.groups (must load first).
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.datamodel) { GT.datamodel = {}; }

    var bg = GT.datamodel.groups;
    if (!bg) throw new Error('base_groups must be loaded before derived_graph');

    // ---------------------------------------------------------------------------
    // Validation (thin wrapper — base_groups.validate handles isDerived path)
    // ---------------------------------------------------------------------------

    function validate(config, excludeId) {
        // Forward to base_groups validate — derive config needs isDerived:true
        var derivedConfig = {};
        Object.keys(config || {}).forEach(function(k) { derivedConfig[k] = config[k]; });
        derivedConfig.isDerived = true;
        // If no baseGroupId from explicit config, try resolving from parent
        if (!derivedConfig.baseGroupId && config.parentId) {
            var pNode = bg.get(config.parentId);
            if (pNode) derivedConfig.baseGroupId = pNode.baseGroupId;
        }
        return bg.validate(derivedConfig);
    }

    // ---------------------------------------------------------------------------
    // Public API (all delegating to base_groups)
    // ---------------------------------------------------------------------------

    function add(config) {
        var derivedConfig = {};
        Object.keys(config || {}).forEach(function(k) { derivedConfig[k] = config[k]; });
        derivedConfig.isDerived = true;
        // Resolve baseGroupId from parent if not explicit
        if (!derivedConfig.baseGroupId && derivedConfig.parentId) {
            var pNode = bg.get(derivedConfig.parentId);
            if (pNode) derivedConfig.baseGroupId = pNode.baseGroupId;
        }
        var id = bg.add(derivedConfig);
        _emit('derivedGraphChanged', { action: 'add', id: id });
        return bg.get(id);
    }

    function get(id) {
        var node = bg.get(id);
        if (!node || !node.isDerived) return null;
        return node;
    }

    function getAll() {
        return bg.getAll().filter(function(n) { return n.isDerived; });
    }

    function getTree() {
        return bg.getTree(true);
    }

    function getDescendants(id) {
        return bg.getDescendants(id);
    }

    function toggleExpanded(id) {
        return bg.toggleExpanded(id);
    }

    function update(id, patch) {
        var result = bg.update(id, patch);
        _emit('derivedGraphChanged', { action: 'update', id: id });
        return result;
    }

    function remove(id) {
        var removed = bg.remove(id);
        _emit('derivedGraphChanged', { action: 'remove', id: id });
        return removed;
    }

    function list() {
        return bg.list().filter(function(n) { return n.isDerived; });
    }

    function _reset() {
        // Remove all derived nodes from base_groups
        var derivedIds = [];
        var all = bg.getAll();
        for (var i = 0; i < all.length; i++) {
            if (all[i].isDerived) derivedIds.push(all[i].id);
        }
        for (var j = 0; j < derivedIds.length; j++) {
            try { bg.remove(derivedIds[j]); } catch(e) { /* ignore */ }
        }
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
    // Export (same surface as before — no caller changes needed for now)
    // ---------------------------------------------------------------------------

    GT.datamodel.derived_graph = {
        add: add,
        get: get,
        getAll: getAll,
        getTree: getTree,
        getDescendants: getDescendants,
        toggleExpanded: toggleExpanded,
        update: update,
        remove: remove,
        list: list,
        validate: validate,
        _reset: _reset,
    };

    GT.log('datamodel.derived_graph loaded (compat layer → base_groups)');
})();