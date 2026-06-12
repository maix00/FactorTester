/**
 * Highcharts chart renderers for group detail overlay and ranking.
 * Depends on GT.metrics.detailOverlay.format.* and GT.core.dateInputs.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    var F = GT.metrics.detailOverlay.format;
    if (!F) throw new Error('detailOverlay/format.js must be loaded first');

    function buildContinuousTimeAxis(rows, accessor) {
        return GT.core.dateInputs.buildContinuousTimeAxis(rows, accessor);
    }

    function getRobustAxisBounds(values) {
        var clean = (values || []).filter(function(v) { return Number.isFinite(v); }).sort(function(a, b) { return a - b; });
        if (!clean.length) return { min: -0.01, max: 0.01 };
        function quantile(q) {
            var pos = (clean.length - 1) * q;
            var base = Math.floor(pos);
            var rest = pos - base;
            return clean[base + 1] !== undefined ? clean[base] + rest * (clean[base + 1] - clean[base]) : clean[base];
        }
        var low = quantile(0.01);
        var high = quantile(0.99);
        if (low === high) {
            var pad = Math.max(Math.abs(low) * 0.2, 0.001);
            return { min: low - pad, max: high + pad };
        }
        var pad = (high - low) * 0.15;
        return {
            min: Math.min(0, low - pad),
            max: Math.max(0, high + pad),
        };
    }

    function renderGroupDetailHistogram(histogram) {
        var el = document.getElementById('group-detail-histogram');
        if (!el || typeof Highcharts === 'undefined') return;
        Highcharts.chart(el, {
            chart: { type: 'column', backgroundColor: 'transparent' },
            title: { text: null },
            xAxis: {
                categories: (histogram || []).map(function(bin) {
                    return (bin.left * 100).toFixed(2) + '% ~ ' + (bin.right * 100).toFixed(2) + '%';
                }),
                labels: { rotation: -35, style: { fontSize: '10px' } },
            },
            yAxis: { title: { text: '期数' } },
            legend: { enabled: false },
            series: [{ name: '期数', data: (histogram || []).map(function(bin) { return bin.count; }), color: '#4a90d9' }],
            credits: { enabled: false },
        });
    }

    function renderGroupDetailReturnChart(series) {
        var el = document.getElementById('group-detail-return-chart');
        if (!el || typeof Highcharts === 'undefined') return;
        var axis = buildContinuousTimeAxis(series || [], function(row) { return row.timestamp; });
        var returns = (series || []).map(function(row) { return Number(row.return); });
        var bounds = getRobustAxisBounds(returns);
        var outlierPoints = [];
        (series || []).forEach(function(row, idx) {
            if (row.return < bounds.min || row.return > bounds.max) {
                outlierPoints.push({
                    x: idx,
                    y: row.return < bounds.min ? bounds.min : bounds.max,
                    actualReturn: row.return,
                });
            }
        });
        Highcharts.stockChart(el, {
            chart: { backgroundColor: 'transparent', zoomType: 'x' },
            title: { text: null },
            legend: { enabled: true },
            xAxis: {
                ordinal: false,
                labels: {
                    step: axis.labelEvery,
                    formatter: function() {
                        var idx = Math.round(this.value);
                        return axis.labelAt(idx);
                    },
                },
            },
            yAxis: [{
                title: { text: '单期收益' },
                min: bounds.min,
                max: bounds.max,
                labels: { formatter: function() { return (this.value * 100).toFixed(2) + '%'; } },
            }, {
                title: { text: '累计净值' },
                opposite: true,
            }],
            tooltip: {
                shared: true,
                formatter: function() {
                    var idx = this.points && this.points.length ? this.points[0].point.x : this.point.x;
                    var row = series[idx];
                    return '<b>' + axis.labelAt(idx) + '</b><br/>'
                        + '单期收益: ' + F.fmtPct(row.return) + '<br/>'
                        + '累计净值: ' + Number(row.cumulative_return).toFixed(4);
                },
            },
            series: [{
                name: '单期收益',
                type: 'column',
                data: (series || []).map(function(row, idx) {
                    var clipped = Math.min(bounds.max, Math.max(bounds.min, row.return));
                    return { x: idx, y: clipped };
                }),
                color: '#7c9fe6',
            }, {
                name: '累计净值',
                type: 'line',
                yAxis: 1,
                data: (series || []).map(function(row, idx) { return [idx, row.cumulative_return]; }),
                color: '#0f4c81',
            }, {
                name: '离群值',
                type: 'scatter',
                data: outlierPoints,
                color: '#d14343',
                marker: { symbol: 'triangle', radius: 5 },
                enableMouseTracking: false,
                showInNavigator: false,
            }],
            navigator: {
                enabled: true,
                xAxis: {
                    labels: {
                        formatter: function() {
                            var idx = Math.round(this.value);
                            return axis.labelAt(idx);
                        },
                    },
                },
            },
            scrollbar: { enabled: true },
            rangeSelector: { enabled: false },
            credits: { enabled: false },
        });
    }

    function renderGroupRankingSpreadChart(series) {
        var el = document.getElementById('group-ranking-spread-chart');
        if (!el || typeof Highcharts === 'undefined') return;
        var axis = buildContinuousTimeAxis(series, function(row) { return row.timestamp; });
        Highcharts.chart(el, {
            chart: { backgroundColor: 'transparent' },
            title: { text: null },
            xAxis: {
                labels: {
                    step: axis.labelEvery,
                    formatter: function() { return axis.labelAt(this.value); },
                },
            },
            yAxis: [{
                title: { text: '单期组差' },
                labels: { formatter: function() { return (this.value * 100).toFixed(2) + '%'; } },
            }, {
                title: { text: '累计净值' },
                opposite: true,
            }],
            tooltip: {
                shared: true,
                formatter: function() {
                    var idx = this.points && this.points.length ? this.points[0].point.x : this.point.x;
                    var row = series[idx];
                    return '<b>' + axis.labelAt(idx) + '</b><br/>'
                        + '单期 Top-Bottom: ' + F.fmtPct(row.spread) + '<br/>'
                        + '累计净值: ' + Number(row.cumulative_return).toFixed(4);
                },
            },
            series: [{
                name: '单期 Top-Bottom',
                type: 'column',
                data: series.map(function(row, idx) { return [idx, row.spread]; }),
                color: '#7c9fe6',
                tooltip: { valueSuffix: '' },
            }, {
                name: '累计净值',
                type: 'line',
                yAxis: 1,
                data: series.map(function(row, idx) { return [idx, row.cumulative_return]; }),
                color: '#0f4c81',
            }],
            credits: { enabled: false },
        });
    }

    function renderGroupRankingMonotonicChart(series) {
        var el = document.getElementById('group-ranking-monotonic-chart');
        if (!el || typeof Highcharts === 'undefined') return;
        var axis = buildContinuousTimeAxis(series || [], function(row) { return row.timestamp; });
        Highcharts.chart(el, {
            chart: { type: 'column', backgroundColor: 'transparent' },
            title: { text: null },
            xAxis: {
                labels: {
                    step: axis.labelEvery,
                    formatter: function() { return axis.labelAt(this.value); },
                },
            },
            yAxis: {
                min: 0,
                max: 1,
                tickPositions: [0, 1],
                title: { text: null },
                labels: {
                    formatter: function() { return this.value === 1 ? '单调' : '非单调'; },
                },
            },
            legend: { enabled: false },
            tooltip: {
                formatter: function() {
                    var idx = Math.round(this.x);
                    var row = series[idx];
                    var state = row.is_descending ? '严格降序' : (row.is_monotonic ? '严格升序' : '非单调');
                    return '<b>' + axis.labelAt(idx) + '</b><br/>' + state;
                },
            },
            series: [{
                name: '单调性',
                data: (series || []).map(function(row, idx) {
                    return {
                        x: idx,
                        y: row.is_monotonic ? 1 : 0,
                        color: row.is_descending ? '#2f855a' : (row.is_monotonic ? '#7c9fe6' : '#d0d5dd'),
                    };
                }),
            }],
            credits: { enabled: false },
        });
    }

    /** Rolling analysis chart (inside detail tabs). */
    function renderRollingChart(rows) {
        var el = document.getElementById('group-detail-rolling-chart');
        if (!el || typeof Highcharts === 'undefined') return;
        var axis = buildContinuousTimeAxis(rows, function(row) { return row.timestamp; });
        Highcharts.chart(el, {
            chart: { backgroundColor: 'transparent', zoomType: 'x' },
            title: { text: null },
            xAxis: {
                labels: {
                    step: axis.labelEvery,
                    formatter: function() { return axis.labelAt(this.value); },
                },
            },
            yAxis: {
                title: { text: '窗口累计收益' },
                labels: { formatter: function() { return (this.value * 100).toFixed(2) + '%'; } },
            },
            tooltip: {
                formatter: function() {
                    return '<b>' + axis.labelAt(this.x) + '</b><br/>'
                        + this.series.name + ': ' + F.fmtPct(this.y);
                },
            },
            series: [{
                name: '滚动窗口收益',
                data: rows.map(function(row, idx) { return [idx, row.return]; }),
                color: '#0f4c81',
            }],
            credits: { enabled: false },
        });
    }

    GT.metrics.detailOverlay.charts = {
        getRobustAxisBounds: getRobustAxisBounds,
        renderGroupDetailHistogram: renderGroupDetailHistogram,
        renderGroupDetailReturnChart: renderGroupDetailReturnChart,
        renderGroupRankingSpreadChart: renderGroupRankingSpreadChart,
        renderGroupRankingMonotonicChart: renderGroupRankingMonotonicChart,
        renderRollingChart: renderRollingChart,
    };
})();
