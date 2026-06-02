/**
 * Group ranking overlay renderers.
 * Depends on GT.metrics.detailOverlay.*
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    var F = GT.metrics.detailOverlay.format;
    var T = GT.metrics.detailOverlay.tables;
    var C = GT.metrics.detailOverlay.charts;
    if (!F || !T || !C) throw new Error('detailOverlay sub-modules not fully loaded');

    function renderGroupRankingDetail(detail) {
        var topBottom = detail.top_bottom || {};
        var labels = [
            ['monotonic_period_ratio', '单调期占比', true],
            ['descending_period_ratio', '严格降序占比', true],
            ['mean_rank_correlation', '平均秩相关', false],
            ['mean_non_empty_group_count', '平均有效组数', false],
            ['full_group_period_ratio', '全组可比期占比', true],
            ['top_bottom_mean', '首尾组平均差', true],
            ['top_bottom_positive', '首尾差为正占比', true],
        ];
        var values = {
            monotonic_period_ratio: detail.monotonic_period_ratio,
            descending_period_ratio: detail.descending_period_ratio,
            mean_rank_correlation: detail.mean_rank_correlation,
            mean_non_empty_group_count: detail.mean_non_empty_group_count,
            full_group_period_ratio: detail.full_group_period_ratio,
            top_bottom_mean: topBottom.mean_spread,
            top_bottom_positive: topBottom.positive_ratio,
        };
        document.getElementById('group-ranking-summary').innerHTML = labels.map(function(item) {
            var value = values[item[0]];
            var display = value == null ? '—' : (item[2] ? F.fmtPct(value) : Number(value).toFixed(4));
            return '<div class="group-detail-summary-item"><div class="group-detail-summary-label">'
                + item[1] + '</div><div class="group-detail-summary-value">' + display + '</div></div>';
        }).join('');
        document.getElementById('group-ranking-adjacent').innerHTML = T.renderGroupRankingAdjacent(detail.adjacent_spreads);
        document.getElementById('group-ranking-overview-summary').textContent =
            '整体排序质量 · 单调 ' + F.fmtPct(detail.monotonic_period_ratio) + ' · 首尾为正 ' + F.fmtPct(topBottom.positive_ratio);
        document.getElementById('group-ranking-spread-summary').textContent =
            '最高组减最低组的逐期表现 · 均值 ' + F.fmtPct(topBottom.mean_spread) + ' · 为正 ' + F.fmtPct(topBottom.positive_ratio);
        C.renderGroupRankingSpreadChart(topBottom.series || []);
        C.renderGroupRankingMonotonicChart(detail.monotonic_series || []);
    }

    GT.metrics.detailOverlay.ranking = {
        renderGroupRankingDetail: renderGroupRankingDetail,
    };
})();
