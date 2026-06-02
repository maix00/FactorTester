/**
 * core/cache.js — 分组测试结果缓存管理
 * 
 * 从 app.js 解耦提取。管理 _groupResultsBySubmission 等共享缓存状态。
 * 挂载到 GT.core.cache 命名空间。
 */
(function(){
    var GT = window.GroupTest;
    if (!GT) { console.warn('[GT core/cache] bootstrap missing'); return; }
    GT.core = GT.core || {};
    if (GT.core.cache) { console.warn('[GT core/cache] already loaded'); return; }

    // ---------- 成本敏感性：缓存数据（共享状态） ----------
    var _lastGrossData = null;   // 上次返回的 groups（含 gross_returns / fee_costs）
    var _lastMetrics = null;
    var _lastTimestamps = [];
    var _lastNgroups = 0;
    var _groupResultsBySubmission = {};
    var _activeGroupSubmissionId = null;
    var _activeGroupFactorBySubmission = {};
    var _derivedGroups = [];
    var _derivedGroupSeq = 1;
    var _derivedGeneration = 0;      // 每次 run_group_test 递增，废弃旧的 refreshAllDerivedGroups
    var _currentGroupDetailIndex = null;
    var _longShortDefinitions = [];
    var _lastGroupStructureKey = null;

    var cache = {};

    // ── 缓存核心操作 ──

    cache.cacheGroupResult = function(submissionId, factorAlias, data) {
        if (!submissionId || !factorAlias || !data) return;
        if (!_groupResultsBySubmission[submissionId]) _groupResultsBySubmission[submissionId] = {};
        _groupResultsBySubmission[submissionId][factorAlias] = data;
    };

    cache.getCachedGroupResult = function(submissionId, factorAlias) {
        return _groupResultsBySubmission[submissionId] && _groupResultsBySubmission[submissionId][factorAlias];
    };

    cache.clearCachedGroupResultsForSubmission = function(submissionId) {
        if (!submissionId) return;
        _groupResultsBySubmission[submissionId] = {};
    };

    // ── 成本敏感性数据 getter/setter ──

    cache.getLastGrossData = function() { return _lastGrossData; };
    cache.setLastGrossData = function(v) { _lastGrossData = v; };
    cache.getLastMetrics = function() { return _lastMetrics; };
    cache.setLastMetrics = function(v) { _lastMetrics = v; };
    cache.getLastTimestamps = function() { return _lastTimestamps; };
    cache.setLastTimestamps = function(v) { _lastTimestamps = v; };
    cache.getLastNgroups = function() { return _lastNgroups; };
    cache.setLastNgroups = function(v) { _lastNgroups = v; };
    cache.getLastGroupStructureKey = function() { return _lastGroupStructureKey; };
    cache.setLastGroupStructureKey = function(v) { _lastGroupStructureKey = v; };

    // ── 活跃提交/因子 ──
    cache.getActiveGroupSubmissionId = function() { return _activeGroupSubmissionId; };
    cache.setActiveGroupSubmissionId = function(v) { _activeGroupSubmissionId = v; };
    cache.getActiveGroupFactorBySubmission = function() { return _activeGroupFactorBySubmission; };
    cache.getGroupResultsBySubmission = function() { return _groupResultsBySubmission; };

    // ── 派生组 ──
    cache.getDerivedGroups = function() { return _derivedGroups; };
    cache.setDerivedGroups = function(v) { _derivedGroups = v; };
    cache.getDerivedGroupSeq = function() { return _derivedGroupSeq; };
    cache.setDerivedGroupSeq = function(v) { _derivedGroupSeq = v; };
    cache.getDerivedGeneration = function() { return _derivedGeneration; };
    cache.setDerivedGeneration = function(v) { _derivedGeneration = v; };
    cache.getCurrentGroupDetailIndex = function() { return _currentGroupDetailIndex; };
    cache.setCurrentGroupDetailIndex = function(v) { _currentGroupDetailIndex = v; };

    // ── Long-Short ──
    cache.getLongShortDefinitions = function() { return _longShortDefinitions; };
    cache.setLongShortDefinitions = function(v) { _longShortDefinitions = v; };

    GT.core.cache = cache;
})();
