/**
 * Sectioned metrics table renderer.
 *
 * Input:
 * - metricsByGroup: { [groupLabel]: { [metricName]: number|null } }
 *   groupLabel: "0","1",...,"LS"
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    GT.metrics = GT.metrics || {};

    var metricNamesCN = {
        'Total Return': '总收益率',
        'Annual Return': '年化收益率',
        'Mean Return': '均值收益率',
        'Win Rate': '胜率',
        'Volatility': '年化波动率',
        'Max Drawdown': '最大回撤',
        'Sharpe Ratio': '夏普比率',
        'Calmar Ratio': 'Calmar比率',
        'Skewness': '偏度',
        'Kurtosis': '峰度',
        'Avg Turnover': '平均换手率',
        'Avg Turnover Accel': '换手加速度',
        'Avg Position Changes': '平均持仓变化数',
        'Up Ratio': '上涨占比',
    };

    function isFiniteNumber(v) {
        return typeof v === 'number' && isFinite(v) && !isNaN(v);
    }

    function fmtPctAdaptive(decimal, metricName) {
        if (!isFiniteNumber(decimal)) return '—';
        var pct = decimal * 100;
        var abs = Math.abs(pct);

        if (metricName === 'Mean Return' && abs < 0.1) {
            var bp = pct * 100; // 1% = 100 bp
            var decBp = Math.abs(bp) >= 1 ? 2 : 3;
            return bp.toFixed(decBp) + ' bp';
        }

        var dec;
        if (abs >= 10) dec = 2;
        else if (abs >= 1) dec = 3;
        else if (abs >= 0.1) dec = 4;
        else if (abs >= 0.01) dec = 5;
        else dec = 6;
        return pct.toFixed(dec) + '%';
    }

    function fmtNumber(v, decimals) {
        if (!isFiniteNumber(v)) return '—';
        return Number(v).toFixed(decimals == null ? 4 : decimals);
    }

    function metricDisplay(metricName, v) {
        if (v == null) return '—';
        if (!isFiniteNumber(v)) return '—';

        if (metricName.indexOf('Return') >= 0 || metricName.indexOf('Rate') >= 0 || metricName.indexOf('Drawdown') >= 0 || metricName === 'Win Rate') {
            return fmtPctAdaptive(v, metricName);
        }
        if (metricName === 'Avg Turnover' || metricName === 'Avg Turnover Accel' || metricName === 'Up Ratio') {
            return fmtPctAdaptive(v, metricName);
        }
        if (metricName === 'Avg Position Changes') {
            return fmtNumber(v, 1);
        }
        if (metricName.indexOf('Ratio') >= 0) return fmtNumber(v, 4);
        return fmtNumber(v, 4);
    }

    function getGroupLabels(metricsByGroup) {
        var labels = [];
        for (var k in (metricsByGroup || {})) {
            if (!Object.prototype.hasOwnProperty.call(metricsByGroup, k)) continue;
            labels.push(k);
        }
        labels.sort(function(a, b) {
            // Long-Short column should be the first group column
            if (a === 'LS') return -1;
            if (b === 'LS') return 1;
            return parseInt(a, 10) - parseInt(b, 10);
        });
        return labels;
    }

    function buildAssignedMetricSet(sections) {
        var set = {};
        (sections || []).forEach(function(sec) {
            (sec.metrics || []).forEach(function(m) { set[m] = true; });
        });
        return set;
    }

    function computeUnknownMetrics(metricsByGroup, assignedSet) {
        var unknown = [];
        var labels = getGroupLabels(metricsByGroup);
        if (!labels.length) return unknown;
        var sample = metricsByGroup[labels[0]] || {};
        Object.keys(sample).forEach(function(metric) {
            if (!assignedSet[metric]) unknown.push(metric);
        });
        unknown.sort();
        return unknown;
    }

    // Best-value direction: 1 = higher is better, -1 = lower is better, 0/undefined = no highlight.
    var METRIC_DIR = {
        'Total Return': 1,
        'Annual Return': 1,
        'Sharpe Ratio': 1,
        'Calmar Ratio': 1,
        'Win Rate': 1,
        'Mean Return': 1,
        'Skewness': 1,
        'Volatility': -1,
        'Max Drawdown': -1,
        'Kurtosis': -1,
        'Avg Turnover': -1,
        'Avg Turnover Accel': -1,
        'Avg Position Changes': -1,
        'Up Ratio': 1,
    };

    function getBestIdx(values, metricName) {
        var dir = METRIC_DIR[metricName] || 0;
        if (!dir) return null;
        var bestIdx = null;
        var bestVal = null;
        for (var i = 0; i < values.length; i++) {
            var v = values[i];
            if (v === null || v === undefined || (typeof v === 'number' && isNaN(v))) continue;
            var num = typeof v === 'number' ? v : parseFloat(v);
            if (!isFinite(num)) continue;
            if (bestIdx === null || (dir > 0 ? num > bestVal : num < bestVal)) {
                bestIdx = i;
                bestVal = num;
            }
        }
        return bestIdx;
    }

    function render(metricsByGroup) {
        var sections = (GT.metrics.sections && GT.metrics.sections.buildSections) ? GT.metrics.sections.buildSections() : [];
        var labels = getGroupLabels(metricsByGroup);
        if (!labels.length) return { headHtml: '', bodyHtml: '' };

        // Header triggers are used by group_test/app.js bindGroupDetailHeaders():
        // - click "指标" to open ranking detail
        // - click "第k组" to open group detail
        var headHtml = '<tr><th class="group-ranking-trigger" title="查看整体排序能力">指标</th>';
        labels.forEach(function(g) {
            if (g === 'LS') {
                headHtml += '<th style="background:#f0f0f0;">Long-Short</th>';
            } else {
                headHtml += '<th class="group-detail-trigger" data-group-index="' + String(g) + '" title="查看该组详情">第'
                    + (parseInt(g, 10) + 1) + '组</th>';
            }
        });
        headHtml += '</tr>';

        var assigned = buildAssignedMetricSet(sections);
        var unknown = computeUnknownMetrics(metricsByGroup, assigned);
        if (unknown.length) sections = sections.concat([{ id: 'others', title: '其他', metrics: unknown }]);

        function sectionRow(title) {
            return '<tr class="metric-section-row"><td colspan="' + (labels.length + 1) + '" style="background:#f8fafc;font-weight:700;color:#0f4c81;border-top:2px solid #e5e7eb;">' + title + '</td></tr>';
        }

        var bodyHtml = '';
        sections.forEach(function(sec) {
            bodyHtml += sectionRow(sec.title);
            (sec.metrics || []).forEach(function(metricName) {
                var rawVals = labels.map(function(g) { return (metricsByGroup[g] || {})[metricName]; });
                var bestIdx = getBestIdx(rawVals, metricName);
                bodyHtml += '<tr>';
                bodyHtml += '<td class="metric-name-cell" data-metric="' + metricName.replace(/"/g, '&quot;') + '" style="font-weight:600;">'
                    + (metricNamesCN[metricName] || metricName) + '</td>';
                labels.forEach(function(g, gi) {
                    var v = (metricsByGroup[g] || {})[metricName];
                    var cls = (bestIdx !== null && gi === bestIdx) ? ' class="group-best-cell"' : '';
                    bodyHtml += '<td' + cls + '>' + metricDisplay(metricName, v) + '</td>';
                });
                bodyHtml += '</tr>';
            });
        });

        return { headHtml: headHtml, bodyHtml: bodyHtml };
    }

    GT.metrics.table = {
        render: render,
        metricNamesCN: metricNamesCN,
        metricDisplay: metricDisplay,
    };
})();
