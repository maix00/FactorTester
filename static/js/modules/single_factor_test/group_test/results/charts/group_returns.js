/**
 * results/charts/group_returns.js — Group cumulative-return chart.
 *
 * Owns Highcharts rendering for result groups. Callers only provide result-group
 * rows and a snapshot callback; chart timeline construction stays local here.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    GT.results = GT.results || {};
    GT.results.chart = GT.results.chart || {};

    var _groupChart = null;

    function gcd(a, b) {
        a = Math.abs(a);
        b = Math.abs(b);
        while (b) {
            var t = b;
            b = a % b;
            a = t;
        }
        return a || 1;
    }

    function buildTimeline(groups) {
        var allDiffs = [];
        var globalMin = Infinity;
        var globalMax = -Infinity;
        var groupRanges = [];
        var i, j;

        for (i = 0; i < groups.length; i++) {
            var gts = groups[i].timestamps || [];
            if (gts.length === 0) continue;
            for (j = 1; j < gts.length; j++) {
                var d = gts[j] - gts[j - 1];
                if (d > 0) allDiffs.push(d);
            }
            groupRanges.push({ min: gts[0], max: gts[gts.length - 1] });
            if (gts[0] < globalMin) globalMin = gts[0];
            if (gts[gts.length - 1] > globalMax) globalMax = gts[gts.length - 1];
        }

        var step = null;
        for (i = 0; i < allDiffs.length; i++) {
            step = (step === null) ? allDiffs[i] : gcd(step, allDiffs[i]);
        }
        if (!step || step <= 0 || globalMin >= globalMax) step = null;

        function isCovered(ts) {
            for (var r = 0; r < groupRanges.length; r++) {
                if (ts >= groupRanges[r].min && ts <= groupRanges[r].max) return true;
            }
            return false;
        }

        var timeline = [];
        if (step) {
            for (var t = globalMin; t <= globalMax; t += step) {
                if (isCovered(t)) timeline.push(t);
            }
            return timeline;
        }

        var tset = {};
        for (i = 0; i < groups.length; i++) {
            var tts = groups[i].timestamps || [];
            for (j = 0; j < tts.length; j++) tset[tts[j]] = true;
        }
        return Object.keys(tset).map(Number).sort(function(a, b) { return a - b; });
    }

    function buildSeries(groups, timeline) {
        return groups.map(function(group) {
            var alias = group.key || group.name;
            var gts = group.timestamps || [];
            var vals = group.total_equity || [];
            var valMap = {};

            for (var k = 0; k < Math.min(gts.length, vals.length); k++) {
                if (vals[k] !== null) valMap[gts[k]] = vals[k];
            }

            // Data points: [timestamp_ms, value] — datetime xAxis
            var data = [];
            for (var ti = 0; ti < timeline.length; ti++) {
                var ts = timeline[ti];
                data.push([ts, Object.prototype.hasOwnProperty.call(valMap, ts) ? valMap[ts] : null]);
            }

            var opts = {
                name: alias,
                type: 'line',
                data: data,
                tooltip: { valueDecimals: 2 },
                visible: true,
                showInLegend: true,
                connectNulls: true,
            };
            if (group.is_ls) {
                opts.color = '#000';
                opts.dashStyle = 'Dash';
                opts.lineWidth = 2;
            }
            return opts;
        });
    }

    function draw(groups, options) {
        options = options || {};
        var container = document.getElementById(options.containerId || 'group_chart_container');
        if (!container || !groups || groups.length === 0) {
            if (container) container.style.display = 'none';
            return;
        }
        if (typeof Highcharts === 'undefined') return;
        container.style.display = 'block';

        var timeline = buildTimeline(groups);
        var isIntraday = timeline.length >= 2 && (timeline[1] - timeline[0]) < 86400000;
        var series = buildSeries(groups, timeline);
        var initialCapital = options.initialCapital || 100000000;
        var baseCurrency = String(options.baseCurrency || 'CNY').toUpperCase();
        var evaluationWindow = options.evaluationWindow || {};
        var splitMs = evaluationWindow.split_ms || null;
        var showOutOfSample = options.showOutOfSample === true;
        function formatMoney(value) {
            if (window.MoneyDisplay && window.MoneyDisplay.formatMajor) {
                return window.MoneyDisplay.formatMajor(value, { currency: baseCurrency, decimals: 2 });
            }
            return Number(value).toFixed(2) + ' ' + baseCurrency;
        }

        function openSnapshotAt(ts) {
            if (typeof options.onSnapshot === 'function') options.onSnapshot(ts);
        }

        function nearestTimelineMs(value) {
            if (!timeline.length || !isFinite(value)) return null;
            var best = timeline[0];
            var bestDist = Math.abs(best - value);
            for (var ti = 1; ti < timeline.length; ti++) {
                var dist = Math.abs(timeline[ti] - value);
                if (dist < bestDist) {
                    best = timeline[ti];
                    bestDist = dist;
                }
            }
            return best;
        }

        _groupChart = Highcharts.stockChart(container, {
            chart: {
                zoomType: 'x',
                events: {
                    click: function(event) {
                        if (!event || !event.chartX || !this.xAxis || !this.xAxis.length) return;
                        var plotX = event.chartX - this.plotLeft;
                        if (plotX < 0 || plotX > this.plotWidth) return;
                        var ts = nearestTimelineMs(this.xAxis[0].toValue(plotX));
                        if (ts !== null) openSnapshotAt(ts);
                    },
                },
            },
            title: { text: '分组累计收益' },
            legend: {
                enabled: true,
                align: 'center',
                verticalAlign: 'bottom',
                layout: 'horizontal',
                itemStyle: { fontSize: '11px' },
            },
            xAxis: {
                type: 'datetime',
                max: (!showOutOfSample && splitMs) ? splitMs : null,
                plotBands: (showOutOfSample && splitMs) ? [{
                    from: splitMs,
                    to: evaluationWindow.end_ms || globalThis.Number.MAX_SAFE_INTEGER,
                    color: 'rgba(217, 119, 6, 0.12)',
                    label: { text: '样本外', style: { color: '#92400e', fontWeight: '600' } },
                }] : [],
                dateTimeLabelFormats: isIntraday
                    ? { day: '%m-%d', week: '%m-%d', month: '%Y-%m' }
                    : { day: '%Y-%m-%d', week: '%Y-%m-%d', month: '%Y-%m' },
            },
            yAxis: [{
                title: { text: '总权益 (' + baseCurrency + ')' },
                crosshair: false,
                labels: {
                    formatter: function() {
                        return (this.value / 10000).toFixed(0) + '万';
                    },
                },
            }, {
                // Right axis: percentage return vs initial capital
                title: { text: '累计收益率 (%)' },
                opposite: true,
                linkedTo: 0,
                labels: {
                    formatter: function() {
                        return (((this.value / initialCapital) - 1) * 100).toFixed(2) + '%';
                    },
                },
            }],
            plotOptions: {
                series: {
                    cursor: 'pointer',
                    connectNulls: true,
                    point: {
                        events: {
                            click: function() {
                                openSnapshotAt(this.x);
                            },
                        },
                    },
                },
            },
            tooltip: {
                shared: true,
                useHTML: true,
                formatter: function() {
                    var ts = this.x;
                    var dateStr = Highcharts.dateFormat('%Y-%m-%d %H:%M', ts);
                    var s = '<b>' + dateStr + '</b>';
                    this.points.forEach(function(p) {
                        if (p.y === null || p.y === undefined) return;
                        var pct = (((p.y / initialCapital) - 1) * 100).toFixed(2);
                        s += '<br/>' + p.series.name + ': ' + formatMoney(p.y) + ' &nbsp;(' + pct + '%)';
                    });
                    return s;
                },
            },
            series: series,
            navigator: { enabled: true },
            scrollbar: { enabled: true },
            rangeSelector: { enabled: false },
        });
    }

    GT.results.chart.groups = {
        draw: draw,
        getChart: function() { return _groupChart; },
    };
})();
