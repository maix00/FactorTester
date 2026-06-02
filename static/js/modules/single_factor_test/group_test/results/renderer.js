/**
 * results/renderer.js — 分组测试结果渲染器
 *
 * 负责：
 *   - 接收 group-test 服务器原始响应，编排策略面板/图表/指标表
 *   - 托管 _lastGrossData / _lastMetrics 等状态（通过 GT.core.cache）
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
    var setLastGrossData = function(v) { GT.core.cache && GT.core.cache.setLastGrossData(v); };
    var setLastMetrics   = function(v) { GT.core.cache && GT.core.cache.setLastMetrics(v); };
    var getLastGrossData = function() { return GT.core.cache ? GT.core.cache.getLastGrossData() : null; };
    var getLastMetrics   = function() { return GT.core.cache ? GT.core.cache.getLastMetrics() : null; };


    // ════════════════════════════════════════════════════════════════
    //  图表
    // ════════════════════════════════════════════════════════════════

    /**
     * 画分组累计收益图。
     */
    renderer.drawGroupChart = function(groups) {
        if (GT.results && GT.results.chart && GT.results.chart.groups && typeof GT.results.chart.groups.draw === 'function') {
            GT.results.chart.groups.draw(groups, {
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

        // 1) 更新策略面板
        if (GT.results && GT.results.strategyPanel && typeof GT.results.strategyPanel.update === 'function') {
            GT.results.strategyPanel.update(data.multi_session_active, data.rebalance_mode, data.multi_session_batches);
        }

        // 2) 持久化到 cache
        setLastGrossData(data.groups);
        setLastMetrics(data.metrics);

        // 3) 画图 + 指标表
        renderer.drawGroupChart(data.groups);
        renderer.renderMetricsTable(data.metrics);
    };

    // ════════════════════════════════════════════════════════════════
    //  暴露
    // ════════════════════════════════════════════════════════════════

    GT.results.renderer = renderer;
})();
