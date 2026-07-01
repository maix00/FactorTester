/**
 * Tab content renderers for group detail overlay.
 *
 * Each render*Analysis function reads DOM elements by ID and populates
 * them with content.  All depend on GT.metrics.detailOverlay.* modules.
 *
 * renderGroupDetail(detail, options) is the main entry that calls all
 * analysis renderers in sequence.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    var F = GT.metrics.detailOverlay.format;
    var T = GT.metrics.detailOverlay.tables;
    var C = GT.metrics.detailOverlay.charts;
    var IW = GT.metrics.detailOverlay.intraday;
    if (!F || !T || !C || !IW) throw new Error('detailOverlay sub-modules not fully loaded');
    var _productAnalysisLevel = 'products';

    /* ───── renderGroupSummaryCards ───── */

    function renderGroupSummaryCards(summary) {
        function formatPct(pct) {
            if (pct == null || isNaN(pct) || !isFinite(pct)) return '—';
            var abs = Math.abs(pct);
            var dec;
            if (abs >= 10) dec = 2;
            else if (abs >= 1) dec = 3;
            else if (abs >= 0.1) dec = 4;
            else if (abs >= 0.01) dec = 5;
            else dec = 6;
            return pct.toFixed(dec) + '%';
        }
        var items = [
            ['Total Return', '总收益率'],
            ['Mean Return', '均值收益率'],
            ['Win Rate', '胜率'],
            ['Volatility', '年化波动率'],
            ['Max Drawdown', '最大回撤'],
            ['Avg Turnover', '平均换手率'],
        ];
        return items.map(function(item) {
            var key = item[0];
            var value = summary[key];
            var display = '—';
            if (value != null && !isNaN(value) && isFinite(value)) {
                display = formatPct(value);
            }
            return '<div class="group-detail-summary-item"><div class="group-detail-summary-label">'
                + item[1] + '</div><div class="group-detail-summary-value">' + display + '</div></div>';
        }).join('');
    }

    /* ───── Analysis tab renderers ───── */

    function renderPositiveRunAnalysis(analysis, onRenderDerivedPanel) {
        var top1 = analysis.top1_positive_contribution_ratio;
        var top3 = analysis.top3_positive_contribution_ratio;
        var concentrated = !!analysis.is_concentrated;
        document.getElementById('group-detail-positive-run-summary').textContent =
            concentrated
                ? '疑似依赖少数正收益段'
                : '检查收益是否集中在少数连续正收益段';
        var overview = document.getElementById('group-detail-positive-run-overview');
        if (!analysis.run_count) {
            overview.textContent = '没有检测到连续正收益段。';
        } else {
            overview.textContent =
                '共 ' + analysis.run_count + ' 段连续正收益；最强 1 段贡献 ' + F.fmtPct(top1)
                + ' 的正收益，最强 3 段贡献 ' + F.fmtPct(top3)
                + '。去掉最强 1 段后累计收益 ' + F.fmtPct(analysis.return_without_top1_run)
                + '，去掉最强 3 段后累计收益 ' + F.fmtPct(analysis.return_without_top3_runs)
                + (concentrated ? '。当前表现明显依赖少数正收益段。' : '。');
        }
        document.getElementById('group-detail-positive-runs').innerHTML = T.renderPositiveRuns(analysis.top_runs);
    }

    function renderIntradayAnalysis(analysis) {
        var top = analysis.top_times || [];
        var bottom = analysis.bottom_times || [];
        var best = top[0];
        IW.setRows(analysis.rows || []);
        document.getElementById('group-detail-intraday-summary').textContent =
            best ? '哪些分钟真正贡献了收益 · 最高 ' + best.time + ' ' + F.fmtPct(best.sum) : '哪些分钟真正贡献了收益';
        IW.renderSelectedWindows();
        document.getElementById('group-detail-intraday-top').innerHTML = T.renderIntradayRows(top);
        document.getElementById('group-detail-intraday-bottom').innerHTML = T.renderIntradayRows(bottom);
    }

    function renderDailyAnalysis(analysis) {
        var top = analysis.top_days || [];
        var bottom = analysis.bottom_days || [];
        var best = top[0];
        document.getElementById('group-detail-daily-summary').textContent =
            best ? '哪些交易日主导了结果 · 最高 ' + best.date + ' ' + F.fmtPct(best.sum) : '哪些交易日主导了结果';
        document.getElementById('group-detail-daily-overview').textContent =
            '去掉贡献最高 1 日后累计收益 ' + F.fmtPct(analysis.return_without_top1_day)
            + '；去掉贡献最高 5 日后累计收益 ' + F.fmtPct(analysis.return_without_top5_days) + '。';
        document.getElementById('group-detail-daily-top').innerHTML = T.renderDailyRows(top);
        document.getElementById('group-detail-daily-bottom').innerHTML = T.renderDailyRows(bottom);
    }

    function renderProductAnalysis(analysis) {
        var byLevel = analysis.by_level || {};
        var level = byLevel[_productAnalysisLevel] ? _productAnalysisLevel : (analysis.default_level || 'products');
        if (!byLevel[level]) level = byLevel.products ? 'products' : byLevel.contracts ? 'contracts' : '';
        var active = level ? byLevel[level] : analysis;
        var top = active.top_products || [];
        var bottom = active.bottom_products || [];
        var best = top[0];
        document.getElementById('group-detail-product-summary').textContent =
            best ? '哪些' + (level === 'contracts' ? '合约' : '品种') + '真正贡献了毛收益 · 最高 ' + F.formatGroupProduct(best.product) : '哪些产品真正贡献了毛收益';
        var switchHtml = '';
        if (byLevel.products && byLevel.contracts) {
            switchHtml = '<div class="snapshot-matrix-switch snapshot-matrix-switch-paired" role="group" style="margin-bottom:8px;">'
                + '<button type="button" class="snapshot-matrix-switch-btn' + (level === 'products' ? ' active' : '') + '" data-product-analysis-level="products">品种</button>'
                + '<button type="button" class="snapshot-matrix-switch-btn' + (level === 'contracts' ? ' active' : '') + '" data-product-analysis-level="contracts">合约</button>'
                + '</div>';
        }
        document.getElementById('group-detail-product-overview').textContent =
            '以下为已实现持仓下的毛收益贡献，不含手续费分摊。'
            + '最强 1 个' + (level === 'contracts' ? '合约' : '品种') + '贡献正毛收益的 ' + F.fmtPct(active.top1_positive_contribution_ratio)
            + '，最强 3 个' + (level === 'contracts' ? '合约' : '品种') + '贡献 ' + F.fmtPct(active.top3_positive_contribution_ratio)
            + (active.is_concentrated ? '。当前毛收益对少数' + (level === 'contracts' ? '合约' : '品种') + '较集中。' : '。');
        document.getElementById('group-detail-product-top').innerHTML = switchHtml + T.renderProductContributionRows(top, { level: level, weighted: level === 'products' });
        document.getElementById('group-detail-product-bottom').innerHTML = T.renderProductContributionRows(bottom, { level: level, weighted: level === 'products' });
        var switchButtons = document.querySelectorAll('#group-detail-product-top [data-product-analysis-level]');
        for (var i = 0; i < switchButtons.length; i++) {
            switchButtons[i].addEventListener('click', function() {
                _productAnalysisLevel = this.getAttribute('data-product-analysis-level') || 'products';
                renderProductAnalysis(analysis);
            });
        }
    }

    function renderRobustnessSummary(summary, periodRobustness) {
        var top1 = periodRobustness.without_top1pct || {};
        var top5 = periodRobustness.without_top5pct || {};
        var issueLabels = {
            positive_runs: '少数连续正收益段',
            top_day: '单一交易日',
            top_periods: '头部时段',
            products: '少数产品',
            months: '少数月份',
            short_holding: '极短持有期',
            tiny_groups: '小样本组',
            unstable_windows: '滚动表现不稳',
        };
        var issues = (summary.issues || []).map(function(key) { return issueLabels[key] || key; });
        document.getElementById('group-detail-robustness-summary').textContent =
            summary.is_fragile ? '存在集中性风险' : '未见明显集中性风险';
        document.getElementById('group-detail-robustness-overview').textContent =
            '去掉最好 1% 时段后累计收益 ' + F.fmtPct(top1.remaining_return)
            + '；去掉最好 5% 时段后累计收益 ' + F.fmtPct(top5.remaining_return)
            + (issues.length ? '。当前主要风险来自：' + issues.join('、') + '。' : '。');
    }

    function renderCalendarAnalysis(analysis) {
        var topMonth = (analysis.month_rows || [])[0];
        document.getElementById('group-detail-calendar-summary').textContent =
            topMonth ? '按月、按月内日期、按年查看收益 · 最强月份 ' + topMonth.month : '按月、按月内日期、按年查看收益';
        document.getElementById('group-detail-calendar-month').innerHTML = T.renderCalendarRows(analysis.month_rows, 'month');
        document.getElementById('group-detail-calendar-day').innerHTML = T.renderCalendarRows(analysis.day_rows, 'day');
        document.getElementById('group-detail-calendar-year').innerHTML = T.renderCalendarRows(analysis.year_rows, 'year');
    }

    function renderHoldingAnalysis(analysis) {
        document.getElementById('group-detail-holding-summary').textContent =
            analysis.median_periods == null ? '组内成员通常停留多久' : '组内成员通常停留多久 · 中位数 ' + Number(analysis.median_periods).toFixed(1) + ' 期';
        var items = [
            ['run_count', '持有段数'],
            ['mean_periods', '平均持有期'],
            ['median_periods', '中位持有期'],
            ['p95_periods', 'P95 持有期'],
        ];
        document.getElementById('group-detail-holding').innerHTML = items.map(function(item) {
            var value = analysis[item[0]];
            var display = value == null ? '—' : Number(value).toFixed(item[0] === 'run_count' ? 0 : 2);
            return '<div class="group-detail-summary-item"><div class="group-detail-summary-label">'
                + item[1] + '</div><div class="group-detail-summary-value">' + display + '</div></div>';
        }).join('');
    }

    function renderExplanations(lines) {
        document.getElementById('group-detail-explanation-summary').textContent =
            lines && lines.length ? '系统归纳的主要风险 · ' + lines.length + ' 条' : '系统归纳的主要风险';
        document.getElementById('group-detail-explanations').innerHTML =
            lines && lines.length
                ? '<ul class="group-detail-explanation-list">' + lines.map(function(line) { return '<li>' + line + '</li>'; }).join('') + '</ul>'
                : '<div class="group-detail-muted">当前未识别到明显集中性风险。</div>';
    }

    function renderTradabilityAnalysis(analysis) {
        document.getElementById('group-detail-tradability-summary').textContent =
            analysis.break_even_fee == null
                ? '资金换手与成本承受力'
                : '资金换手与成本承受力 · break-even ' + F.fmtBp(analysis.break_even_fee);
        var items = [
            ['avg_trade_notional_ratio', '平均资金换手'],
            ['median_trade_notional_ratio', '中位资金换手'],
            ['avg_actual_fee_cost', '平均实际费率成本'],
            ['actual_fee_per_traded_notional', '成交额加权实际费率'],
            ['break_even_fee', 'Break-even 成本'],
        ];
        document.getElementById('group-detail-tradability-summary-grid').innerHTML = items.map(function(item) {
            var value = analysis[item[0]];
            var display = value == null ? '—' : (
                item[0] === 'break_even_fee' || item[0] === 'actual_fee_per_traded_notional'
                    ? F.fmtBp(value)
                    : F.fmtPct(value)
            );
            return '<div class="group-detail-summary-item"><div class="group-detail-summary-label">'
                + item[1] + '</div><div class="group-detail-summary-value">' + display + '</div></div>';
        }).join('');
        var rows = analysis.sensitivity || [];
        var html = '<table class="group-detail-table"><thead><tr><th>单边等比例成本</th><th>累计收益</th></tr></thead><tbody>';
        rows.forEach(function(row) {
            html += '<tr><td>' + F.fmtBp(row.fee) + '</td><td>' + F.fmtPct(row.total_return) + '</td></tr>';
        });
        document.getElementById('group-detail-fee-sensitivity').innerHTML = rows.length ? html + '</tbody></table>' : '<div class="group-detail-muted">暂无数据</div>';
    }

    function renderRollingAnalysis(analysis) {
        var rows = analysis.rows || [];
        document.getElementById('group-detail-rolling-summary').textContent =
            analysis.window_size == null
                ? '不同时间窗口里是否持续有效'
                : '不同时间窗口里是否持续有效 · ' + analysis.window_size + ' 期窗口';
        C.renderRollingChart(rows);
    }

    function renderCapacityAnalysis(analysis) {
        document.getElementById('group-detail-capacity-summary').textContent =
            analysis.tiny_group_ratio == null ? '组内样本是否经常过小' : '组内样本是否经常过小 · 小样本期 ' + F.fmtPct(analysis.tiny_group_ratio);
        var items = [
            ['mean_count', '平均成员数'],
            ['median_count', '中位成员数'],
            ['min_count', '最少成员数'],
            ['empty_ratio', '空组占比'],
            ['tiny_group_ratio', '成员数 <= 2 占比'],
        ];
        document.getElementById('group-detail-capacity').innerHTML = items.map(function(item) {
            var value = analysis[item[0]];
            var display = value == null ? '—' : (
                item[0].indexOf('ratio') >= 0 ? F.fmtPct(value) : Number(value).toFixed(item[0] === 'min_count' ? 0 : 2)
            );
            return '<div class="group-detail-summary-item"><div class="group-detail-summary-label">'
                + item[1] + '</div><div class="group-detail-summary-value">' + display + '</div></div>';
        }).join('');
    }

    /* ───── renderGroupDetail (orchestrator) ───── */

    /**
     * Main entry to render a group detail object into the overlay DOM.
     *
     * @param {Object} detail         - The detail payload from the server or buildPortfolioDetail.
     * @param {Object} options
     * @param {number} [options.groupIndex]  - Current group index (for derived panel).
     * @param {function} [options.onRenderDerivedPanel]  - Callback(groupIndex) to render derived groups panel.
     */
    function renderGroupDetail(detail, options) {
        options = options || {};
        var summaryEl = document.getElementById('group-detail-summary');
        if (summaryEl) {
            summaryEl.innerHTML = renderGroupSummaryCards(detail.summary || {});
        }
        var actions = GT.panels && GT.panels.actions;
        if (actions && typeof actions.renderGroupFrequency === 'function') {
            document.getElementById('group-detail-frequency').innerHTML = actions.renderGroupFrequency(detail.entry_frequency);
        } else {
            document.getElementById('group-detail-frequency').innerHTML = T.renderGroupFrequency(detail.entry_frequency);
        }
        if (typeof options.onRenderDerivedPanel === 'function') {
            options.onRenderDerivedPanel(options.groupIndex);
        } else {
            var derivedPanel = document.getElementById('group-derived-groups-panel');
            if (derivedPanel) derivedPanel.innerHTML = '';
        }
        document.getElementById('group-detail-top-periods').innerHTML = T.renderGroupDetailTable(detail.top_periods);
        document.getElementById('group-detail-bottom-periods').innerHTML = T.renderGroupDetailTable(detail.bottom_periods);
        var q = (detail.distribution || {}).quantiles || {};
        document.getElementById('group-detail-quantiles').textContent =
            'P05 ' + F.fmtPct(q.p05) + ' · P50 ' + F.fmtPct(q.p50) + ' · P95 ' + F.fmtPct(q.p95);
        document.getElementById('group-detail-frequency-summary').textContent =
            (detail.entry_frequency && detail.entry_frequency.length)
                ? '哪些产品最常进入该组 · ' + F.formatGroupProduct(detail.entry_frequency[0].product) + ' ' + (detail.entry_frequency[0].frequency * 100).toFixed(1) + '%'
                : '哪些产品最常进入该组';
        document.getElementById('group-detail-distribution-summary').textContent =
            '收益直方图与分位数 · P50 ' + F.fmtPct(q.p50) + ' · P95 ' + F.fmtPct(q.p95);
        renderPositiveRunAnalysis(detail.positive_run_analysis || {});
        renderIntradayAnalysis(detail.intraday_analysis || {});
        renderDailyAnalysis(detail.daily_analysis || {});
        renderProductAnalysis(detail.product_analysis || {});
        renderCalendarAnalysis(detail.calendar_analysis || {});
        renderHoldingAnalysis(detail.holding_analysis || {});
        renderTradabilityAnalysis(detail.tradability_analysis || {});
        renderRollingAnalysis(detail.rolling_analysis || {});
        renderCapacityAnalysis(detail.capacity_analysis || {});
        renderExplanations(detail.explanations || []);
        renderRobustnessSummary(detail.robustness_summary || {}, detail.period_robustness || {});
        C.renderGroupDetailReturnChart(detail.return_series || []);
        C.renderGroupDetailHistogram((detail.distribution || {}).histogram || []);
    }

    GT.metrics.detailOverlay.tabs = {
        renderGroupSummaryCards: renderGroupSummaryCards,
        renderPositiveRunAnalysis: renderPositiveRunAnalysis,
        renderIntradayAnalysis: renderIntradayAnalysis,
        renderDailyAnalysis: renderDailyAnalysis,
        renderProductAnalysis: renderProductAnalysis,
        renderRobustnessSummary: renderRobustnessSummary,
        renderCalendarAnalysis: renderCalendarAnalysis,
        renderHoldingAnalysis: renderHoldingAnalysis,
        renderExplanations: renderExplanations,
        renderTradabilityAnalysis: renderTradabilityAnalysis,
        renderRollingAnalysis: renderRollingAnalysis,
        renderCapacityAnalysis: renderCapacityAnalysis,
        renderGroupDetail: renderGroupDetail,
    };
})();
