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
    var _lastGrossData = null;
    var _lastMetrics = null;
    var _lastTimestamps = [];
    var _lastNgroups = 0;
    var _currentGroupDetailIndex = null;
    var _longShortDefinitions = [];
    var _lastGroupStructureKey = null;

    var cache = {};

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

    cache.getCurrentGroupDetailIndex = function() { return _currentGroupDetailIndex; };
    cache.setCurrentGroupDetailIndex = function(v) { _currentGroupDetailIndex = v; };

    // ── Long-Short ──
    cache.getLongShortDefinitions = function() { return _longShortDefinitions; };
    cache.setLongShortDefinitions = function(v) { _longShortDefinitions = v; };

    GT.core.cache = cache;
})();
