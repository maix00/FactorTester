/**
 * Factor Series Charts
 * Shared rendering helpers for factor-series charts.
 */
(function() {
    'use strict';

    var namespace = window.FactorSeriesCharts = window.FactorSeriesCharts || {};

    function toTimestamp(ts) {
        if (ts === null || ts === undefined) return null;
        if (typeof ts === 'number' || typeof ts === 'bigint') {
            return Number(ts);
        }
        var date = new Date(ts);
        if (!isNaN(date.getTime())) {
            return date.getTime();
        }
        var fallback = new Date(String(ts) + 'T00:00:00');
        return isNaN(fallback.getTime()) ? null : fallback.getTime();
    }

    function ensureArray(value) {
        return Array.isArray(value) ? value : [];
    }

    function normalizePoints(dates, values) {
        var pointRows = [];
        if (!Array.isArray(dates) || !Array.isArray(values)) {
            return pointRows;
        }
        for (var i = 0; i < dates.length && i < values.length; i++) {
            var t = toTimestamp(dates[i]);
            if (t === null || t === undefined) {
                continue;
            }
            var v = values[i];
            if (typeof v === 'number' && isNaN(v)) continue;
            pointRows.push([t, v]);
        }
        return pointRows;
    }

    function message(text, isError) {
        return '<div style="padding:24px;text-align:center;color:' + (isError ? '#b91c1c' : '#94a3b8') + ';font-size:12px;">'
            + String(text == null ? '' : text)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/\'/g, '&#39;')
            + '</div>';
    }

    namespace.renderFactorSeriesChart = function(renderOptions) {
        var opts = renderOptions || {};
        var container = opts.container;
        if (!container) return;
        if (typeof Highcharts === 'undefined') {
            container.innerHTML = message('Highcharts 未加载，无法显示图表。', true);
            return;
        }
        container.style.height = opts.height || '520px';

        var data = normalizePoints(ensureArray(opts.dates), ensureArray(opts.values));
        if (!data.length) {
            container.innerHTML = message('没有可显示的因子序列。', true);
            return;
        }

        Highcharts.stockChart(container, {
            chart: {
                zoomType: 'x'
            },
            title: {
                text: opts.title || '因子序列'
            },
            xAxis: {
                type: 'datetime'
            },
            yAxis: {
                title: { text: opts.yAxisLabel || '因子值' },
                crosshair: true
            },
            tooltip: {
                shared: true,
                valueDecimals: 6
            },
            legend: {
                enabled: false
            },
            navigator: {
                enabled: true
            },
            scrollbar: {
                enabled: true
            },
            rangeSelector: {
                enabled: true
            },
            series: [{
                name: opts.seriesName || '因子值',
                type: 'line',
                data: data,
                dataGrouping: { enabled: false }
            }]
        });
    };

    namespace.renderDualSeriesChart = function(renderOptions) {
        var opts = renderOptions || {};
        var container = opts.container;
        if (!container) return;
        if (typeof Highcharts === 'undefined') {
            container.innerHTML = message('Highcharts 未加载，无法显示图表。', true);
            return;
        }

        container.style.height = opts.height || '520px';
        var factorData = normalizePoints(ensureArray(opts.factorDates), ensureArray(opts.factorValues));
        var returnData = normalizePoints(ensureArray(opts.returnDates), ensureArray(opts.returnValues));
        if (!factorData.length && !returnData.length) {
            container.innerHTML = message('没有可显示的序列。', true);
            return;
        }

        var hasReturns = returnData.length > 0;
        var series = [];

        if (factorData.length) {
            series.push({
                name: opts.factorName || '因子值',
                type: 'line',
                data: factorData,
                yAxis: 0,
                color: opts.factorColor || '#2563eb',
                dataGrouping: { enabled: false },
            });
        }
        if (hasReturns) {
            series.push({
                name: opts.returnName || '收益率',
                type: 'line',
                data: returnData,
                yAxis: 1,
                color: opts.returnColor || '#d97706',
                dataGrouping: { enabled: false },
                tooltip: {
                    valueDecimals: 6,
                }
            });
        }

        Highcharts.stockChart(container, {
            chart: {
                zoomType: 'x'
            },
            title: {
                text: opts.title || '因子序列'
            },
            xAxis: {
                type: 'datetime'
            },
            yAxis: [{
                title: { text: opts.factorAxisLabel || '因子值' },
                crosshair: true,
            }, {
                title: { text: opts.returnAxisLabel || '收益率' },
                opposite: true,
                visible: hasReturns,
            }],
            tooltip: {
                shared: true,
                valueDecimals: 6
            },
            legend: {
                enabled: false
            },
            navigator: {
                enabled: true
            },
            scrollbar: {
                enabled: true
            },
            rangeSelector: {
                enabled: true
            },
            series: series
        });
    };
})();
