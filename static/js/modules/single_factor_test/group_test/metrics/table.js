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

    function isFiniteNumber(v) {
        return typeof v === 'number' && isFinite(v) && !isNaN(v);
    }

    var percentUnitMetrics = {
        'Total Return': true,
        'Annual Return': true,
        'Mean Return': true,
        'Win Rate': true,
        'Volatility': true,
        'Max Drawdown': true,
    };

    var decimalRatioMetrics = {
        'Avg Turnover': true,
        'Avg Turnover Accel': true,
        'Up Ratio': true,
    };

    function fmtPercentUnits(pct, metricName) {
        if (!isFiniteNumber(pct)) return '—';
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

    function fmtDecimalRatio(decimal, metricName) {
        if (!isFiniteNumber(decimal)) return '—';
        return fmtPercentUnits(decimal * 100, metricName);
    }

    function fmtNumber(v, decimals) {
        if (!isFiniteNumber(v)) return '—';
        return Number(v).toFixed(decimals == null ? 4 : decimals);
    }

    function metricDisplay(metricName, v) {
        if (v == null) return '—';
        if (!isFiniteNumber(v)) return '—';

        if (percentUnitMetrics[metricName] || metricName.indexOf('Return') >= 0 || metricName.indexOf('Drawdown') >= 0) {
            return fmtPercentUnits(v, metricName);
        }
        if (decimalRatioMetrics[metricName]) {
            return fmtDecimalRatio(v, metricName);
        }
        if (metricName === 'Avg Position Changes') {
            return fmtNumber(v, 1);
        }
        if (metricName.indexOf('Ratio') >= 0) return fmtNumber(v, 4);
        return fmtNumber(v, 4);
    }

    function metricLabel(metricName) {
        var meta = (GT.metrics && GT.metrics.meta) || {};
        return (meta.cn && meta.cn[metricName]) || metricName;
    }

    function escapeAttr(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function buildGroupIndexMap(groups) {
        var map = {};
        (groups || []).forEach(function(g, idx) {
            if (!g || g.is_ls || !g.key) return;
            var groupIndex = g.group_index != null ? g.group_index : idx;
            map[g.key] = { groupIndex: groupIndex, productPathSelectionId: g.product_path_selection_id || null };
        });
        return map;
    }

    function getGroupLabels(metricsByGroup) {
        var labels = [];
        for (var k in (metricsByGroup || {})) {
            if (!Object.prototype.hasOwnProperty.call(metricsByGroup, k)) continue;
            labels.push(k);
        }
        labels.sort(function(a, b) {
            var ai = parseInt(a, 10);
            var bi = parseInt(b, 10);
            var an = String(ai) === String(a);
            var bn = String(bi) === String(b);
            if (an && bn) return ai - bi;
            if (an) return -1;
            if (bn) return 1;
            return String(a).localeCompare(String(b));
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

    function build(metricsByGroup, groups) {
        var sections = (GT.metrics.sections && GT.metrics.sections.buildSections) ? GT.metrics.sections.buildSections() : [];
        var labels = getGroupLabels(metricsByGroup);
        if (!labels.length) return { headHtml: '', bodyHtml: '' };

        var groupIndexMap = buildGroupIndexMap(groups);
        function groupLabel(g) { return String(g); }
        function groupIndexDisplay(g) {
            var entry = groupIndexMap[g];
            return (entry && entry.groupIndex != null) ? String(entry.groupIndex) : '';
        }
        function groupProductPathSelectionId(g) {
            var entry = groupIndexMap[g];
            return entry ? (entry.productPathSelectionId || null) : null;
        }

        var headHtml = '<tr><th class="group-ranking-trigger" title="查看整体排序能力">指标</th>';
        labels.forEach(function(g) {
            var label = groupLabel(g);
            var indexDisplay = groupIndexDisplay(g);
            var productPathSelectionId = groupProductPathSelectionId(g);
            headHtml += '<th class="group-detail-trigger"'
                + ' data-group-key="' + escapeAttr(g) + '"'
                + ' data-group-index="' + escapeAttr(indexDisplay) + '"'
                + ' data-product-path-selection-id="' + escapeAttr(productPathSelectionId || '') + '"'
                + ' title="查看该组详情">' + label + '</th>';
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
                    + metricLabel(metricName) + '</td>';
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

    function bindHeaderActions(actions) {
        actions = actions || {};
        document.querySelectorAll('#metrics_head .group-detail-trigger').forEach(function(th) {
            th.addEventListener('click', function() {
                var groupKey = th.getAttribute('data-group-key');
                if (typeof actions.openResultGroupDetail === 'function') {
                    actions.openResultGroupDetail(groupKey, th.getAttribute('data-group-index'), th.getAttribute('data-product-path-selection-id'));
                } else if (typeof actions.openGroupDetail === 'function') {
                    actions.openGroupDetail(parseInt(th.getAttribute('data-group-index'), 10));
                }
            });
        });
        var rankingHead = document.querySelector('#metrics_head .group-ranking-trigger');
        if (rankingHead) {
            rankingHead.addEventListener('click', function() {
                if (typeof actions.openGroupRankingDetail === 'function') {
                    actions.openGroupRankingDetail();
                }
            });
        }
    }

    function render(metricsByGroup, groups, actions) {
        var out = build(metricsByGroup || {}, groups || []);
        var head = document.getElementById('metrics_head');
        var body = document.getElementById('metrics_body');
        if (head) head.innerHTML = out.headHtml || '';
        if (body) body.innerHTML = out.bodyHtml || '';
        bindHeaderActions(actions);
    }

    GT.metrics.table = {
        build: build,
        render: render,
        bindHeaderActions: bindHeaderActions,
        metricLabel: metricLabel,
        metricDisplay: metricDisplay,
    };
})();
