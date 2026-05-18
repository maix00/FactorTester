/**
 * GroupTest state & caches.
 *
 * Minimal initial structure; will be expanded as legacy code migrates.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

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

    GT.state = {
        active: _active,
        setActiveSubmission: setActiveSubmission,
        setActiveFactor: setActiveFactor,
        getActiveFactor: getActiveFactor,
        cacheResult: cacheResult,
        getCachedResult: getCachedResult,
    };
})();

