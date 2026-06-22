/** Factor series viewer module: product-level factor/price/return diagnostics. */
(function() {
    var state = {
        selections: [],
        activeSelectionId: '',
    };

    function selectionId(selection) {
        var utils = window.ProductPathSelectionUtils;
        return utils && utils.selectionId ? utils.selectionId(selection)
            : (selection ? String(selection.product_path_selection_id || selection.selection_id || selection.id || '') : '');
    }

    function cloneList(list) {
        var utils = window.ProductPathSelectionUtils;
        return utils && utils.cloneList ? utils.cloneList(list) : (Array.isArray(list) ? list.slice() : []);
    }

    function render() {
        var body = document.getElementById('factor-series-viewer-body');
        var chart = document.getElementById('factor-series-chart-container');
        if (!body || !chart) return;
        if (!state.selections.length) {
            chart.innerHTML = '<div style="padding:24px;text-align:center;color:#94a3b8;font-size:12px;">请先在对应测试模块中选择产品路径。</div>';
            return;
        }
        chart.innerHTML = '<div style="padding:24px;text-align:center;color:#64748b;font-size:12px;">已接收 '
            + state.selections.length
            + ' 个产品路径选择。产品、合约/期限、因子序列和收益标签对比将在这里懒加载。</div>';
    }

    function setSelections(selections) {
        state.selections = cloneList(selections);
        if (!state.activeSelectionId && state.selections.length) {
            state.activeSelectionId = selectionId(state.selections[0]);
        }
        render();
    }

    function init() {
        var btn = document.getElementById('factor-series-open-btn');
        var body = document.getElementById('factor-series-viewer-body');
        if (!btn || !body) return;
        btn.addEventListener('click', function() {
            var open = body.style.display === 'none';
            body.style.display = open ? '' : 'none';
            btn.textContent = open ? '收起序列查看' : '打开序列查看';
            if (open) render();
        });
    }

    window.FactorSeriesViewer = {
        setSelections: setSelections,
        getSelections: function() { return cloneList(state.selections); },
    };

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
