/**
 * results/renderer.js — 分组测试结果渲染器
 *
 * 负责：
 *   - 接收 group-test 服务器原始响应，编排策略面板/图表/指标表
 *   - 托管 _lastGrossData / _lastMetrics 等状态（通过 GT.groupSettings.cache）
 *   - 画图/指标桥接
 *
 * 挂载到 GT.results.renderer。
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) { console.warn('[renderer] GroupTest bootstrap missing'); return; }

    GT.results = GT.results || {};
    if (GT.results.renderer) { console.warn('[renderer] already loaded'); return; }

    var renderer = {};

    // ── 本地桥接 ──
    function cache() { return GT.groupSettings && GT.groupSettings.cache ? GT.groupSettings.cache : null; }
    var setLastGrossData = function(v) { var c = cache(); if (c) c.setLastGrossData(v); };
    var setLastMetrics   = function(v) { var c = cache(); if (c) c.setLastMetrics(v); };
    var getLastGrossData = function() { var c = cache(); return c ? c.getLastGrossData() : null; };
    var getLastMetrics   = function() { var c = cache(); return c ? c.getLastMetrics() : null; };
    var _lastInitialCapital = 100000000;
    var _lastBaseCurrency = 'CNY';
    var _lastEvaluationWindow = null;
    var _showOutOfSample = false;
    function setLastInitialCapital(v) { if (typeof v === 'number' && v > 0) _lastInitialCapital = v; }
    function getLastInitialCapital() { return _lastInitialCapital; }
    function setLastBaseCurrency(v) { _lastBaseCurrency = String(v || 'CNY').toUpperCase(); }
    function getLastBaseCurrency() { return _lastBaseCurrency; }


    // ════════════════════════════════════════════════════════════════
    //  图表
    // ════════════════════════════════════════════════════════════════

    /**
     * 画分组累计收益图。
     */
    renderer.drawGroupChart = function(groups) {
        if (GT.results && GT.results.chart && GT.results.chart.groups && typeof GT.results.chart.groups.draw === 'function') {
            GT.results.chart.groups.draw(groups, {
                initialCapital: getLastInitialCapital(),
                baseCurrency: getLastBaseCurrency(),
                evaluationWindow: _lastEvaluationWindow,
                showOutOfSample: _showOutOfSample,
                onSnapshot: function(t) {
                    return GT.results.snapshot ? GT.results.snapshot.fetchGroupSnapshot(t) : null;
                },
            });
        }
    };

    // ════════════════════════════════════════════════════════════════
    //  指标表
    // ════════════════════════════════════════════════════════════════

    /**
     * 渲染统计指标表格。
     */
    renderer.renderMetricsTable = function(metrics) {
        var grossData = getLastGrossData();
        var container = document.getElementById('group_metrics_container');
        if (!container || !metrics || Object.keys(metrics).length === 0) {
            if (container) container.style.display = 'none';
            return;
        }
        container.style.display = 'block';
        if (GT.metrics && GT.metrics.table && typeof GT.metrics.table.render === 'function') {
            GT.metrics.table.render(metrics, grossData, {
                openResultGroupDetail: GT.metrics.detailOverlay.index.openResultGroupDetail,
                openGroupRankingDetail: GT.metrics.detailOverlay.index.openGroupRankingDetail,
            });
        }
    };

    // ════════════════════════════════════════════════════════════════
    //  应用测试结果（主入口）
    // ════════════════════════════════════════════════════════════════

    /**
     * 接收分组测试服务器原始响应，编排所有渲染。
     * 由 app.js 的 runGroupTest / restoreActiveGroupResult 调用。
     */
    renderer.applyGroupTestResult = function(data, statusText) {
        console.log('[GroupTest] applyGroupTestResult:', {
            submission_id: data.submission_id,
            factor_alias: data.factor_alias,
            tester_alias: data.tester_alias,
            tester_product_count: data.tester_product_count,
            n_groups: data.n_groups,
        });

        // 0) 注入后端 metrics_meta（替换前端硬编码）
        if (data.metrics_meta) {
            console.log('[GroupTest] metrics_meta from backend:', Object.keys(data.metrics_meta.cn || {}).length, 'metrics');
            GT.metrics = GT.metrics || {};
            GT.metrics.meta = data.metrics_meta;
        } else {
            console.warn('[GroupTest] No metrics_meta in result data');
        }

        // 1) 更新策略面板
        if (GT.results && GT.results.strategyPanel && typeof GT.results.strategyPanel.update === 'function') {
            GT.results.strategyPanel.update(
                data.multi_session_active,
                data.multi_session_entries,
                {
                    capital_warning: data.capital_warning,
                    capital_diagnostics: data.capital_diagnostics,
                    market_rule_warning: data.market_rule_warning,
                    market_rule_approximation_count: data.market_rule_approximation_count,
                    setting_fallback_warning: data.setting_fallback_warning,
                    setting_fallbacks: data.setting_fallbacks,
                    backtest_settings: data.backtest_settings,
                    engine_result: data.engine_result,
                }
            );
        }

        // 2) 持久化到 cache
        setLastGrossData(data.groups);
        setLastMetrics(data.metrics);
        setLastInitialCapital(data.initial_capital);
        setLastBaseCurrency(data.base_currency);
        _lastEvaluationWindow = data.evaluation_window || null;
        _showOutOfSample = false;

        var evaluationToolbar = document.getElementById('group-evaluation-toolbar');
        var oosToggle = document.getElementById('group-oos-toggle');
        if (evaluationToolbar) {
            evaluationToolbar.style.display = _lastEvaluationWindow && _lastEvaluationWindow.split_ms ? 'flex' : 'none';
        }
        if (oosToggle) {
            oosToggle.textContent = '显示样本外';
            oosToggle.onclick = function() {
                _showOutOfSample = !_showOutOfSample;
                oosToggle.textContent = _showOutOfSample ? '仅显示样本内' : '显示样本外';
                renderer.drawGroupChart(getLastGrossData());
            };
        }

        // 3) 画图 + 指标表
        renderer.drawGroupChart(data.groups);
        renderer.renderMetricsTable(data.metrics);
    };

    // ════════════════════════════════════════════════════════════════
    //  暴露
    // ════════════════════════════════════════════════════════════════

    GT.results.renderer = renderer;
})();
