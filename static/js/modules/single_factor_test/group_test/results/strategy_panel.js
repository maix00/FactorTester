/**
 * Strategy summary panel for group-test results.
 *
 * Renders MultiSession batch summaries and capital shortage diagnostics.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    GT.results = GT.results || {};

    var MODE_LABELS = {
        each_period: '每期等权再平衡',
        buy_and_hold: '组内持仓不动',
        recycle: '退出资金优先补新仓',
    };

    function hide(layer, status, notice, head, body) {
        layer.style.display = 'none';
        if (status) status.textContent = '';
        if (notice) notice.innerHTML = '';
        if (notice) notice.style.display = 'none';
        head.innerHTML = '';
        body.innerHTML = '';
    }

    function batchLabel(batch) {
        var batchIndex = Number.isFinite(Number(batch.index)) ? (Number(batch.index) + 1) : '';
        var testerAlias = batch.tester_alias || batch.testerAlias || batch.submission_id || '';
        var factorAlias = batch.factor_alias || batch.factorAlias || '';
        var groupText = batch.n_groups ? (' / ' + batch.n_groups + '组') : '';
        return (batchIndex ? ('Batch ' + batchIndex + ' · ') : '')
            + [testerAlias, factorAlias].filter(Boolean).join(' / ')
            + groupText;
    }

    function _formatCapitalNotice(data) {
        if (!data || !data.capital_warning) return '';
        var parts = [];
        parts.push('<div style="font-weight:600;margin-bottom:4px;">⚠️ ' + GT.escapeHTML(data.capital_warning) + '</div>');
        var diag = data.capital_diagnostics || {};
        if (diag.blocked_group_count !== undefined && diag.blocked_group_count !== null) {
            parts.push('<div>未开仓组数：' + GT.escapeHTML(String(diag.blocked_group_count)) + '</div>');
        }
        var blocked = Array.isArray(diag.blocked_groups) ? diag.blocked_groups : [];
        if (blocked.length > 0) {
            var sample = blocked[0];
            var sampleParts = [];
            if (sample.group_name) sampleParts.push('组 ' + GT.escapeHTML(String(sample.group_name)));
            if (sample.cheapest_product_name) sampleParts.push('最便宜品种 ' + GT.escapeHTML(String(sample.cheapest_product_name)));
            if (sample.cheapest_required_capital !== undefined) sampleParts.push('需求约 ' + GT.escapeHTML(String(Math.round(Number(sample.cheapest_required_capital)))));
            if (sample.budget_per_product !== undefined) sampleParts.push('预算约 ' + GT.escapeHTML(String(Math.round(Number(sample.budget_per_product)))));
            if (sampleParts.length) parts.push('<div>' + sampleParts.join('，') + '</div>');
        }
        return parts.join('');
    }

    function render(multiSessionActive, usedMode, multiSessionBatches, capitalWarningData) {
        var layer = document.getElementById('gt-layer-strategy');
        var status = document.getElementById('gt-strategy-status');
        var notice = document.getElementById('gt-strategy-notice');
        var head = document.getElementById('gt-strategy-head');
        var body = document.getElementById('gt-strategy-body');
        if (!layer || !head || !body) return;

        var capitalNoticeHtml = _formatCapitalNotice(capitalWarningData);
        if (!multiSessionActive && !capitalNoticeHtml) {
            hide(layer, status, notice, head, body);
            return;
        }

        var modeLabel = MODE_LABELS[usedMode] || usedMode || '当前再平衡模式';
        var batches = Array.isArray(multiSessionBatches) && multiSessionBatches.length > 0
            ? multiSessionBatches
            : [{ index: 0, tester_alias: '当前测试器', factor_alias: '当前因子', n_groups: null }];

        layer.style.display = '';
        if (status) status.textContent = '检测到 ' + batches.length + ' 个 MultiSession batch';
        if (notice) {
            if (capitalNoticeHtml) {
                notice.innerHTML = capitalNoticeHtml;
                notice.style.display = 'block';
            } else {
                notice.innerHTML = '';
                notice.style.display = 'none';
            }
        }
        head.innerHTML = '<tr><th>Batch</th><th>当前模式</th><th>处理方式</th></tr>';
        body.innerHTML = batches.map(function(batch) {
            return '<tr class="gt-strategy-row">'
                + '<td class="gt-strategy-cell-running">' + GT.escapeHTML(batchLabel(batch) || 'MultiSession batch') + '</td>'
                + '<td>' + GT.escapeHTML(modeLabel) + '</td>'
                + '<td>该 batch 含不同交易时段的品种；后端按 MultiSession 处理：仅对当期有信号的品种交易和再平衡，无信号品种持仓保持不动。</td>'
                + '</tr>';
        }).join('');
    }

    // 从 app.js 桥接：由 applyGroupTestResult 调用
    function updatePanel(multiSessionActive, usedMode, multiSessionBatches, capitalWarningData) {
        render(multiSessionActive, usedMode, multiSessionBatches, capitalWarningData);
    }

    GT.results.strategyPanel = {
        render: render,
        update: updatePanel,
    };
})();
