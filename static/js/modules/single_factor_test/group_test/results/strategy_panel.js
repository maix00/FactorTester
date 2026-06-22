/**
 * Strategy summary panel for group-test results.
 *
 * Renders MultiSession batch summaries and capital shortage diagnostics.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    GT.results = GT.results || {};

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

    function _formatMissingProducts(batch) {
        var products = Array.isArray(batch && batch.missing_products)
            ? batch.missing_products.filter(Boolean)
            : [];
        if (!products.length) return '';
        var total = Number(batch.missing_product_count || products.length);
        var sample = products.slice(0, 8).join('、');
        if (total > products.length || products.length > 8) sample += ' 等';
        return '触发品种：' + sample + '（' + total + ' 个品种存在非头部缺 bar/交易时段差异）';
    }

    function _pushCapitalRows(rows, data) {
        if (!data) return;
        if (data.capital_warning) {
            rows.push({
                type: '资金约束',
                status: '提示',
                detail: data.capital_warning,
            });
        }
        if (data.market_rule_warning) {
            rows.push({
                type: '市场规则',
                status: '近似',
                detail: data.market_rule_warning,
            });
        }
        var diag = data.capital_diagnostics || {};
        var details = [];
        if (diag.blocked_group_count !== undefined && diag.blocked_group_count !== null) {
            details.push('未开仓组数：' + String(diag.blocked_group_count));
        }
        var blocked = Array.isArray(diag.blocked_groups) ? diag.blocked_groups : [];
        if (blocked.length > 0) {
            var sample = blocked[0];
            var sampleParts = [];
            if (sample.group_name) sampleParts.push('组 ' + String(sample.group_name));
            if (sample.cheapest_product_name) sampleParts.push('最便宜品种 ' + String(sample.cheapest_product_name));
            if (sample.cheapest_required_capital !== undefined) sampleParts.push('需求约 ' + String(Math.round(Number(sample.cheapest_required_capital))));
            if (sample.budget_per_product !== undefined) sampleParts.push('预算约 ' + String(Math.round(Number(sample.budget_per_product))));
            if (sampleParts.length) details.push(sampleParts.join('，'));
        }
        if (details.length) {
            rows.push({
                type: '资金约束',
                status: '诊断',
                detail: details.join('；'),
            });
        }
    }

    function _rowHtml(row) {
        return '<tr class="gt-strategy-row">'
            + '<td>' + GT.escapeHTML(row.type || '') + '</td>'
            + '<td>' + GT.escapeHTML(row.status || '') + '</td>'
            + '<td>' + (row.detailHtml || GT.escapeHTML(row.detail || '')) + '</td>'
            + '</tr>';
    }

    function render(multiSessionActive, multiSessionBatches, capitalWarningData) {
        var layer = document.getElementById('gt-layer-strategy');
        var status = document.getElementById('gt-strategy-status');
        var notice = document.getElementById('gt-strategy-notice');
        var head = document.getElementById('gt-strategy-head');
        var body = document.getElementById('gt-strategy-body');
        if (!layer || !head || !body) return;

        var rows = [];
        var hasMultiSession = !!multiSessionActive;
        var batches = Array.isArray(multiSessionBatches) && multiSessionBatches.length > 0
            ? multiSessionBatches
            : [{ index: 0, tester_alias: '当前测试器', factor_alias: '当前因子', n_groups: null }];
        if (hasMultiSession) {
            for (var bi = 0; bi < batches.length; bi++) {
                var batch = batches[bi];
                var productText = _formatMissingProducts(batch);
                var detail = '后端按 MultiSession 处理：仅对当期有信号的品种交易和再平衡，无信号品种持仓保持不动。';
                if (productText) detail += ' ' + productText;
                rows.push({
                    type: batches.length > 1 ? (batchLabel(batch) || 'MultiSession 批次') : '多交易时段',
                    status: '按策略设置',
                    detail: detail,
                });
            }
        }
        _pushCapitalRows(rows, capitalWarningData);
        if (!rows.length) {
            hide(layer, status, notice, head, body);
            return;
        }

        layer.style.display = '';
        if (status) {
            status.textContent = !hasMultiSession
                ? ''
                : batches.length > 1
                ? ('检测到 ' + batches.length + ' 个 MultiSession 批次')
                : '多交易时段处理已启用';
        }
        if (notice) {
            notice.innerHTML = '';
            notice.style.display = 'none';
        }
        head.innerHTML = '<tr><th>类型</th><th>状态</th><th>说明</th></tr>';
        body.innerHTML = rows.map(_rowHtml).join('');
    }

    // 从 app.js 桥接：由 applyGroupTestResult 调用
    function updatePanel(multiSessionActive, multiSessionBatches, capitalWarningData) {
        render(multiSessionActive, multiSessionBatches, capitalWarningData);
    }

    GT.results.strategyPanel = {
        render: render,
        update: updatePanel,
    };
})();
