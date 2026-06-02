/**
 * Group detail overlay entry point.
 *
 * Provides openResultGroupDetail, openGroupRankingDetail,
 * loadBaseGroupDetail, findResultGroup, and buildPortfolioDetail.
 *
 * Reads rendered result cache and derives submission context from the
 * currently selected group.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    var F = GT.metrics.detailOverlay.format;
    var Tabs = GT.metrics.detailOverlay.tabs;
    var Rank = GT.metrics.detailOverlay.ranking;
    if (!F || !Tabs || !Rank) throw new Error('detailOverlay sub-modules not fully loaded');

    function cache() {
        return GT.groupSettings && GT.groupSettings.cache ? GT.groupSettings.cache : null;
    }

    /* ───── buildPortfolioDetail ───── */

    function buildPortfolioDetail(group, metric) {
        var timestamps = group.timestamps || [];
        var returns = group.gross_returns || [];
        if ((!returns || !returns.length) && group.cumulative_returns) {
            returns = [];
            var prev = 1.0;
            (group.cumulative_returns || []).forEach(function(value) {
                var cur = Number(value);
                if (!isFinite(cur) || prev === 0) {
                    returns.push(0);
                    return;
                }
                returns.push(cur / prev - 1.0);
                prev = cur;
            });
        }
        var wealth = 1.0;
        var returnSeries = returns.map(function(value, idx) {
            var ret = Number(value);
            if (!isFinite(ret)) ret = 0;
            wealth *= (1 + ret);
            return {
                timestamp: new Date(timestamps[idx]).toISOString(),
                return: ret,
                cumulative_return: wealth
            };
        });
        var periods = returnSeries.map(function(row) {
            return { timestamp: row.timestamp, return: row.return, products: [] };
        }).sort(function(a, b) { return b.return - a.return; });
        var cleanReturns = returns.map(Number).filter(function(v) { return isFinite(v); });
        var quantiles = {};
        if (cleanReturns.length) {
            var sorted = cleanReturns.slice().sort(function(a, b) { return a - b; });
            var qv = function(p) { return sorted[Math.min(sorted.length - 1, Math.max(0, Math.floor((sorted.length - 1) * p)))]; };
            quantiles = { p05: qv(0.05), p25: qv(0.25), p50: qv(0.50), p75: qv(0.75), p95: qv(0.95) };
        }
        var entryFrequency = [];
        if (group.derived && group.derived.config) {
            var config = group.derived.config;
            (config.long || []).forEach(function(leg) {
                entryFrequency.push({ product: { name: 'Long 第' + (leg.group + 1) + '组', desc: '权重 ' + leg.weight.toFixed(3) }, count: null, frequency: 0, mean_return: null });
            });
            (config.short || []).forEach(function(leg) {
                entryFrequency.push({ product: { name: 'Short 第' + (leg.group + 1) + '组', desc: '权重 ' + leg.weight.toFixed(3) }, count: null, frequency: 0, mean_return: null });
            });
        }
        return {
            summary: metric || {},
            entry_frequency: entryFrequency,
            top_periods: periods.slice(0, 10),
            bottom_periods: periods.slice(-10).reverse(),
            distribution: { histogram: [], quantiles: quantiles, period_count: cleanReturns.length },
            return_series: returnSeries,
            positive_run_analysis: {},
            intraday_analysis: {},
            daily_analysis: {},
            calendar_analysis: {},
            holding_analysis: {},
            capacity_analysis: {},
            rolling_analysis: {},
            tradability_analysis: {},
            period_robustness: {},
            robustness_summary: {},
            product_analysis: {},
            explanations: [],
        };
    }

    /* ───── Data loading ───── */

    function _getActiveSubmissionId() {
        var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
        if (sel && typeof sel.getFirstSubmissionId === 'function') {
            return sel.getFirstSubmissionId();
        }
        return null;
    }

    async function loadBaseGroupDetail(groupIndex) {
        var submissionId = _getActiveSubmissionId();
        if (!submissionId) return;
        var resp = await fetch('/get_group_detail', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ submission_id: submissionId, group_index: groupIndex }),
        });
        var data = await resp.json();
        if (!data.success) throw new Error(data.error || '加载失败');
        return data.detail || {};
    }

    function findResultGroup(key) {
        var c = cache();
        var grossData = c ? c.getLastGrossData() : null;
        if (!grossData) return null;
        return grossData.find(function(group) {
            if (!group) return false;
            if (String(group.group_index) === String(key)) return true;
            if (group.key === key) return true;
            if (group.name === key) return true;
            if (group.derived && group.derived.key === key) return true;
            if (group.derived && group.derived.id === key) return true;
            return false;
        });
    }

    /* ───── openResultGroupDetail ───── */

    async function openResultGroupDetail(key, groupIndexHint) {
        var group = findResultGroup(key);
        if (!group) {
            alert('未找到该组的已生成结果。');
            return;
        }
        var groupIndex = group.group_index != null
            ? Number(group.group_index)
            : (groupIndexHint !== '' && groupIndexHint != null ? Number(groupIndexHint) : NaN);
        var c = cache();
        if (c) c.setCurrentGroupDetailIndex(isFinite(groupIndex) ? groupIndex : null);
        var overlay = document.getElementById('group-detail-overlay');
        var loading = document.getElementById('group-detail-loading');
        var content = document.getElementById('group-detail-content');
        var title = group.name || group.key || key || '分组';
        document.getElementById('group-detail-title').textContent = title + '详情';
        overlay.classList.add('open');
        loading.style.display = '';
        loading.textContent = '加载中...';
        content.style.display = 'none';
        try {
            var lastMetrics = c ? c.getLastMetrics() : null;
            var metric = (lastMetrics || {})[group.key]
                || (lastMetrics || {})[key] || {};
            var isLsGroup = !!group.is_ls;
            var detail = isLsGroup ? buildPortfolioDetail(group, metric) : await loadBaseGroupDetail(groupIndex);
            Tabs.renderGroupDetail(detail, {
                groupIndex: isFinite(groupIndex) ? groupIndex : undefined,
                onRenderDerivedPanel: function(detailGroupIndex) {
                    if (GT.panels && GT.panels.actions && typeof GT.panels.actions.renderDerivedGroupsPanel === 'function') {
                        GT.panels.actions.renderDerivedGroupsPanel(detailGroupIndex);
                    }
                },
            });
            if (isLsGroup) {
                var summary = document.getElementById('group-detail-frequency-summary');
                if (summary) summary.textContent = 'Long-Short 组合腿配置';
            }
            loading.style.display = 'none';
            content.style.display = '';
        } catch (err) {
            loading.textContent = '加载失败: ' + (err.message || err);
        }
    }

    /* ───── openGroupRankingDetail ───── */

    async function openGroupRankingDetail() {
        var submissionId = _getActiveSubmissionId();
        if (!submissionId) return;
        var overlay = document.getElementById('group-ranking-overlay');
        var loading = document.getElementById('group-ranking-loading');
        var content = document.getElementById('group-ranking-content');
        overlay.classList.add('open');
        loading.style.display = '';
        loading.textContent = '加载中...';
        content.style.display = 'none';
        try {
            var resp = await fetch('/get_group_ranking_detail', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ submission_id: submissionId }),
            });
            var data = await resp.json();
            if (!data.success) throw new Error(data.error || '加载失败');
            Rank.renderGroupRankingDetail(data.detail || {});
            loading.style.display = 'none';
            content.style.display = '';
        } catch (err) {
            loading.textContent = '加载失败: ' + (err.message || err);
        }
    }

    /* ───── Exports ───── */

    GT.metrics.detailOverlay.index = {
        buildPortfolioDetail: buildPortfolioDetail,
        loadBaseGroupDetail: loadBaseGroupDetail,
        findResultGroup: findResultGroup,
        openResultGroupDetail: openResultGroupDetail,
        openGroupRankingDetail: openGroupRankingDetail,
    };
})();
