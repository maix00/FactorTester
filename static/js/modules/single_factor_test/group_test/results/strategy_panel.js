/**
 * Strategy summary panel for group-test results.
 *
 * Currently only renders MultiSession batch warnings. Non-MultiSession results
 * deliberately hide the panel to avoid noisy success banners.
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

    function hide(layer, status, head, body) {
        layer.style.display = 'none';
        if (status) status.textContent = '';
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

    function render(multiSessionActive, usedMode, multiSessionBatches) {
        var layer = document.getElementById('gt-layer-strategy');
        var status = document.getElementById('gt-strategy-status');
        var head = document.getElementById('gt-strategy-head');
        var body = document.getElementById('gt-strategy-body');
        if (!layer || !head || !body) return;

        if (!multiSessionActive) {
            hide(layer, status, head, body);
            return;
        }

        var modeLabel = MODE_LABELS[usedMode] || usedMode || '当前再平衡模式';
        var batches = Array.isArray(multiSessionBatches) && multiSessionBatches.length > 0
            ? multiSessionBatches
            : [{ index: 0, tester_alias: '当前测试器', factor_alias: '当前因子', n_groups: null }];

        layer.style.display = '';
        if (status) status.textContent = '检测到 ' + batches.length + ' 个 MultiSession batch';
        head.innerHTML = '<tr><th>Batch</th><th>当前模式</th><th>处理方式</th></tr>';
        body.innerHTML = batches.map(function(batch) {
            return '<tr class="gt-strategy-row">'
                + '<td class="gt-strategy-cell-running">' + GT.escapeHTML(batchLabel(batch) || 'MultiSession batch') + '</td>'
                + '<td>' + GT.escapeHTML(modeLabel) + '</td>'
                + '<td>该 batch 含不同交易时段的品种；后端按 MultiSession 处理：仅对当期有信号的品种交易和再平衡，无信号品种持仓保持不动。</td>'
                + '</tr>';
        }).join('');
    }

    GT.results.strategyPanel = {
        render: render,
    };
})();
