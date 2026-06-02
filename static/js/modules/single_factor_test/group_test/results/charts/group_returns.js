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

    function formatDateLabel(ts, isIntraday) {
        var d = new Date(ts);
        var datePart = d.getFullYear() + '-' +
            String(d.getMonth() + 1).padStart(2, '0') + '-' +
            String(d.getDate()).padStart(2, '0');
        if (!isIntraday) return datePart;
        return datePart + ' ' +
            String(d.getHours()).padStart(2, '0') + ':' +
            String(d.getMinutes()).padStart(2, '0');
    }

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
            var vals = group.cumulative_returns || [];
            var valMap = {};

            for (var k = 0; k < Math.min(gts.length, vals.length); k++) {
                if (vals[k] !== null) valMap[gts[k]] = vals[k];
            }

            var data = [];
            for (var ti = 0; ti < timeline.length; ti++) {
                var ts = timeline[ti];
                data.push([ti, Object.prototype.hasOwnProperty.call(valMap, ts) ? valMap[ts] : null]);
            }

            var opts = {
                name: alias,
                type: 'line',
                data: data,
                tooltip: { valueDecimals: 4 },
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
        var labelEvery = Math.max(1, Math.floor(timeline.length / 12));

        function labelAt(idx) {
            return idx >= 0 && idx < timeline.length ? formatDateLabel(timeline[idx], isIntraday) : '';
        }

        function openSnapshotAt(idx) {
            console.log('[snapshot-debug] openSnapshotAt called: idx=', idx, 'timelineLen=', timeline.length, 'hasOnSnapshot=', typeof options.onSnapshot === 'function');
            if (idx < 0 || idx >= timeline.length) return;
            if (typeof options.onSnapshot === 'function') options.onSnapshot(timeline[idx]);
            else console.warn('[snapshot-debug] options.onSnapshot is not a function!');
        }

        _groupChart = Highcharts.stockChart(container, {
            chart: {
                zoomType: 'x',
                events: {
                    click: function(e) {
                        openSnapshotAt(Math.round(e.xAxis[0].value));
                    },
                },
            },
            title: { text: '分组累计收益（初始净值 = 1）' },
            legend: {
                enabled: true,
                align: 'center',
                verticalAlign: 'bottom',
                layout: 'horizontal',
                itemStyle: { fontSize: '11px' },
            },
            xAxis: {
                type: 'linear',
                labels: {
                    step: labelEvery,
                    formatter: function() { return labelAt(Math.round(this.value)); },
                },
            },
            yAxis: { title: { text: '净值' }, crosshair: false },
            plotOptions: {
                series: {
                    cursor: 'pointer',
                    connectNulls: true,
                    point: {
                        events: {
                            click: function() {
                                openSnapshotAt(Math.round(this.x));
                            },
                        },
                    },
                },
            },
            tooltip: {
                shared: true,
                valueDecimals: 4,
                useHTML: true,
                formatter: function() {
                    var idx = Math.round(this.x);
                    var s = '<b>' + labelAt(idx) + '</b>';
                    this.points.forEach(function(p) {
                        if (p.y === null || p.y === undefined) return;
                        var decimals = p.series.tooltipOptions.valueDecimals;
                        if (typeof decimals !== 'number') decimals = 4;
                        var val = typeof p.y === 'number' ? p.y.toFixed(decimals) : p.y;
                        s += '<br/>' + p.series.name + ': ' + val;
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
