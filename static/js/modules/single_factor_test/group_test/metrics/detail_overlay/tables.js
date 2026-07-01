/**
 * Table-row renderers for group detail overlay.
 * Each returns an HTML string.
 * Depends on GT.metrics.detailOverlay.format.*
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    var F = GT.metrics.detailOverlay.format;
    if (!F) throw new Error('detailOverlay/format.js must be loaded first');

    function renderPositiveRuns(rows) {
        if (!rows || !rows.length) return '<div class="group-detail-muted">暂无连续正收益段</div>';
        var html = '<table class="group-detail-table"><thead><tr><th>开始</th><th>结束</th><th>期数</th><th>区段收益</th></tr></thead><tbody>';
        rows.forEach(function(row) {
            html += '<tr><td>' + F.formatCompactTime(row.start) + '</td><td>' + F.formatCompactTime(row.end) + '</td><td>'
                + row.period_count + '</td><td>' + F.fmtPct(row.return) + '</td></tr>';
        });
        return html + '</tbody></table>';
    }

    function renderIntradayRows(rows) {
        if (!rows || !rows.length) return '<div class="group-detail-muted">暂无数据</div>';
        var html = '<table class="group-detail-table"><thead><tr><th>时间</th><th>样本</th><th>均值</th><th>累计</th><th>t-like</th></tr></thead><tbody>';
        rows.forEach(function(row) {
            html += '<tr><td>' + row.time + '</td><td>' + row.count + '</td><td>' + F.fmtPct(row.mean) + '</td><td>'
                + F.fmtPct(row.sum) + '</td><td>' + (row.t_like == null ? '—' : Number(row.t_like).toFixed(3)) + '</td></tr>';
        });
        return html + '</tbody></table>';
    }

    function renderDailyRows(rows) {
        if (!rows || !rows.length) return '<div class="group-detail-muted">暂无数据</div>';
        var html = '<table class="group-detail-table"><thead><tr><th>日期</th><th>样本</th><th>累计</th><th>均值</th></tr></thead><tbody>';
        rows.forEach(function(row) {
            html += '<tr><td>' + row.date + '</td><td>' + row.count + '</td><td>' + F.fmtPct(row.sum)
                + '</td><td>' + F.fmtPct(row.mean) + '</td></tr>';
        });
        return html + '</tbody></table>';
    }

    function renderProductContributionRows(rows, options) {
        options = options || {};
        if (!rows || !rows.length) return '<div class="group-detail-muted">暂无数据</div>';
        var feeLabel = F.isRealFee(rows[0]) ? ' (原始费率)' : '';
        if ((rows[0].product && rows[0].product.fee && rows[0].product.fee._is_weighted) || options.weighted) {
            feeLabel = feeLabel || ' (加权)';
        }
        var entityLabel = options.level === 'contracts' ? '合约' : '品种';
        var html = '<table class="group-detail-table"><thead><tr><th>' + entityLabel + '</th><th>描述</th><th>均值收益</th><th>开仓费率' + feeLabel + '</th><th>平今费率' + feeLabel + '</th><th>平昨费率' + feeLabel + '</th><th>合约乘数</th><th>最小手数</th><th>保证金率</th><th>活跃期</th><th>毛贡献</th><th>活跃期均值</th></tr></thead><tbody>';
        rows.forEach(function(row) {
            var meanAct = row.mean_active_contribution;
            var fee = (row.product && row.product.fee) || {};
            var totalFee = (fee.total != null && isFinite(fee.total)) ? fee.total : 0;
            var highlight = (meanAct != null && isFinite(meanAct) && meanAct > totalFee) ? ' style="background:rgba(144,238,144,0.25)"' : '';
            html += '<tr' + highlight + '>' + renderProductFeeCells(row.product, row)
                + renderMarketRuleCells(row.market_rule)
                + '<td>' + row.active_period_count + '</td><td>'
                + F.fmtPct(row.gross_contribution) + '</td><td>' + F.fmtFeeRate(meanAct) + '</td></tr>';
        });
        return html + '</tbody></table>';
    }

    function renderProductFeeCells(product, row) {
        row = row || {};
        if (!product || typeof product === 'string') {
            return '<td>' + (product || '—') + '</td><td style="max-width:120px;white-space:normal;word-break:break-all">—</td><td>—</td><td>—</td><td>—</td><td>—</td>';
        }
        var name = product.name || '—';
        var desc = product.desc && product.desc !== name ? product.desc : '—';
        var fee = product.fee || {};
        var source = product.source_names && product.source_names.length ? '<div style="color:#98a2b3;font-size:10px;">' + product.source_names.join('、') + '</div>' : '';
        return '<td>' + name + source + '</td><td style="max-width:120px;white-space:normal;word-break:break-all">' + desc + '</td><td>' + F.fmtFeeRate(row.mean_return)
            + '</td><td>' + F.fmtFeeRate(fee.open)
            + '</td><td>' + F.fmtFeeRate(fee.close_today) + '</td><td>' + F.fmtFeeRate(fee.close_yesterday != null ? fee.close_yesterday : fee.close) + '</td>';
    }

    function renderMarketRuleCells(rule) {
        rule = rule || {};
        function fmtNumber(value, digits) {
            if (value == null || isNaN(value) || !isFinite(value)) return '—';
            return Number(value).toFixed(digits);
        }
        return '<td>' + fmtNumber(rule.multiplier, 4) + '</td><td>' + fmtNumber(rule.lot_size, 4)
            + '</td><td>' + F.fmtPct(rule.margin_ratio) + '</td>';
    }

    function renderCalendarRows(rows, key) {
        if (!rows || !rows.length) return '<div class="group-detail-muted">暂无数据</div>';
        var html = '<table class="group-detail-table"><thead><tr><th>' + key + '</th><th>样本</th><th>累计</th><th>均值</th></tr></thead><tbody>';
        rows.forEach(function(row) {
            html += '<tr><td>' + row[key] + '</td><td>' + row.count + '</td><td>' + F.fmtPct(row.sum)
                + '</td><td>' + F.fmtPct(row.mean) + '</td></tr>';
        });
        return html + '</tbody></table>';
    }

    function renderIntradayWindows(rows) {
        if (!rows || !rows.length) return '<div class="group-detail-muted">尚未添加时间窗口</div>';
        var html = '<table class="group-detail-table"><thead><tr><th>窗口</th><th>样本</th><th>累计贡献</th><th>占总收益</th></tr></thead><tbody>';
        rows.forEach(function(row) {
            html += '<tr><td>' + row.label + '</td><td>' + row.count + '</td><td>' + F.fmtPct(row.sum) + '</td><td>'
                + F.fmtPct(row.share_of_total_sum) + '</td></tr>';
        });
        return html + '</tbody></table>';
    }

    function renderGroupDetailTable(periods) {
        if (!periods || !periods.length) return '<div class="group-detail-muted">暂无数据</div>';
        var html = '<table class="group-detail-table"><thead><tr><th>时段</th><th>收益</th><th>成员</th></tr></thead><tbody>';
        periods.forEach(function(p) {
            html += '<tr><td>' + F.formatCompactTime(p.timestamp) + '</td><td>'
                + F.fmtPct(p.return) + '</td><td>' + F.formatGroupProducts(p.products) + '</td></tr>';
        });
        return html + '</tbody></table>';
    }

    function renderGroupFrequency(entries) {
        if (!entries || !entries.length) return '<div class="group-detail-muted">暂无入组记录</div>';
        var html = '<table class="group-detail-table"><thead><tr><th>产品</th><th>入组频次</th><th>入组期数</th><th>入组期均值收益</th></tr></thead><tbody>';
        entries.forEach(function(entry) {
            html += '<tr><td>' + F.formatGroupProduct(entry.product) + '</td><td>'
                + F.fmtPct(entry.frequency) + '</td><td>' + (entry.count != null ? entry.count : '—') + '</td><td>'
                + F.fmtPct(entry.mean_return) + '</td></tr>';
        });
        return html + '</tbody></table>';
    }

    function renderGroupRankingAdjacent(rows) {
        if (!rows || !rows.length) return '<div class="group-detail-muted">暂无数据</div>';
        var html = '<table class="group-detail-table"><thead><tr><th>组间</th><th>平均差</th><th>为正占比</th></tr></thead><tbody>';
        rows.forEach(function(row) {
            html += '<tr><td>第' + (row.from_group + 1) + '组 - 第' + (row.to_group + 1) + '组</td><td>'
                + F.fmtPct(row.mean_spread) + '</td><td>' + F.fmtPct(row.positive_ratio) + '</td></tr>';
        });
        return html + '</tbody></table>';
    }

    GT.metrics.detailOverlay.tables = {
        renderPositiveRuns: renderPositiveRuns,
        renderIntradayRows: renderIntradayRows,
        renderDailyRows: renderDailyRows,
        renderProductContributionRows: renderProductContributionRows,
        renderProductFeeCells: renderProductFeeCells,
        renderMarketRuleCells: renderMarketRuleCells,
        renderCalendarRows: renderCalendarRows,
        renderIntradayWindows: renderIntradayWindows,
        renderGroupDetailTable: renderGroupDetailTable,
        renderGroupFrequency: renderGroupFrequency,
        renderGroupRankingAdjacent: renderGroupRankingAdjacent,
    };
})();
