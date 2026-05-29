/**
 * GroupTest state & caches.
 *
 * Central state hub: selected context, event system, lookup helpers.
 * Datamodel modules own their data; state.js provides cross-cutting services.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    // -----------------------------------------------------------------------
    // Legacy active tracking (kept for backward compat)
    // -----------------------------------------------------------------------
    var _active = {
        submissionId: null,
        factorAliasBySubmission: {},
    };

    var _resultCache = {}; // { [submissionId]: { [factorAlias]: result } }

    function setActiveSubmission(submissionId) { _active.submissionId = submissionId; }
    function setActiveFactor(submissionId, factorAlias) {
        if (!submissionId) return;
        _active.factorAliasBySubmission[submissionId] = factorAlias;
    }
    function getActiveFactor(submissionId) { return _active.factorAliasBySubmission[submissionId] || null; }

    function cacheResult(submissionId, factorAlias, result) {
        if (!submissionId || !factorAlias) return;
        if (!_resultCache[submissionId]) _resultCache[submissionId] = {};
        _resultCache[submissionId][factorAlias] = result;
    }
    function getCachedResult(submissionId, factorAlias) {
        return (_resultCache[submissionId] || {})[factorAlias] || null;
    }

    // -----------------------------------------------------------------------
    // Event system: emit / on
    // Datamodel modules call GT.state.emit(...) defensively — we implement it.
    // -----------------------------------------------------------------------
    var _listeners = {};

    function emit(event, data) {
        var cbs = _listeners[event] || [];
        for (var i = 0; i < cbs.length; i++) {
            try { cbs[i](data); } catch (_) {}
        }
    }

    function on(event, callback) {
        if (!_listeners[event]) { _listeners[event] = []; }
        _listeners[event].push(callback);
    }

    function off(event, callback) {
        if (!_listeners[event]) return;
        if (!callback) { delete _listeners[event]; return; }
        _listeners[event] = _listeners[event].filter(function(cb) { return cb !== callback; });
    }

    // -----------------------------------------------------------------------
    // Selection state
    // -----------------------------------------------------------------------
    var _activeMainTab = 'base';   // 'base' | 'derived' | 'ls'
    var _activeBaseGroupId = null;
    var _activeDerivedNodeId = null;
    var _activeLsConfigId = null;

    function setActiveMainTab(tab) {
        _activeMainTab = tab;
        emit('mainTabChanged', { tab: tab });
    }
    function getActiveMainTab() { return _activeMainTab; }

    function setActiveBaseGroupId(id) {
        _activeBaseGroupId = id;
        emit('activeBaseGroupChanged', { id: id });
    }
    function getActiveBaseGroupId() { return _activeBaseGroupId; }

    function setActiveDerivedNodeId(id) {
        _activeDerivedNodeId = id;
        emit('activeDerivedNodeChanged', { id: id });
    }
    function getActiveDerivedNodeId() { return _activeDerivedNodeId; }

    function setActiveLsConfigId(id) {
        _activeLsConfigId = id;
        emit('activeLsConfigChanged', { id: id });
    }
    function getActiveLsConfigId() { return _activeLsConfigId; }

    // -----------------------------------------------------------------------
    // Convenience lookup (delegate to datamodel)
    // -----------------------------------------------------------------------
    function getBaseGroup(id) {
        if (!GT.datamodel || !GT.datamodel.base_groups) return null;
        return GT.datamodel.base_groups.get(id);
    }
    function getDerivedNode(id) {
        if (!GT.datamodel || !GT.datamodel.derived_graph) return null;
        return GT.datamodel.derived_graph.get(id);
    }
    function getLsConfig(id) {
        if (!GT.datamodel || !GT.datamodel.ls_configs) return null;
        return GT.datamodel.ls_configs.get(id);
    }

    // -----------------------------------------------------------------------
    // Reset (testing only)
    // -----------------------------------------------------------------------
    function _resetAll() {
        _active.submissionId = null;
        _active.factorAliasBySubmission = {};
        _resultCache = {};
        _listeners = {};
        _activeMainTab = 'base';
        _activeBaseGroupId = null;
        _activeDerivedNodeId = null;
        _activeLsConfigId = null;
    }

    // -----------------------------------------------------------------------
    // Export
    // -----------------------------------------------------------------------
    GT.state = {
        // Legacy
        active: _active,
        setActiveSubmission: setActiveSubmission,
        setActiveFactor: setActiveFactor,
        getActiveFactor: getActiveFactor,
        cacheResult: cacheResult,
        getCachedResult: getCachedResult,

        // Events
        emit: emit,
        on: on,
        off: off,

        // Selection
        setActiveMainTab: setActiveMainTab,
        getActiveMainTab: getActiveMainTab,
        setActiveBaseGroupId: setActiveBaseGroupId,
        getActiveBaseGroupId: getActiveBaseGroupId,
        setActiveDerivedNodeId: setActiveDerivedNodeId,
        getActiveDerivedNodeId: getActiveDerivedNodeId,
        setActiveLsConfigId: setActiveLsConfigId,
        getActiveLsConfigId: getActiveLsConfigId,

        // Lookup
        getBaseGroup: getBaseGroup,
        getDerivedNode: getDerivedNode,
        getLsConfig: getLsConfig,

        // Testing
        _resetAll: _resetAll,
    };
})();
