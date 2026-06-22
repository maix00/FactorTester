/** Factor series viewer module: product-level factor/price/return diagnostics. */
(function() {
    var state = {
        selections: [],
        activeSelectionId: '',
        factors: [],
        loadingFactors: false,
    };

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function selectionId(selection) {
        var utils = window.ProductPathSelectionUtils;
        return utils && utils.selectionId ? utils.selectionId(selection)
            : (selection ? String(selection.product_path_selection_id || selection.selection_id || selection.id || '') : '');
    }

    function selectionLabel(selection) {
        var utils = window.ProductPathSelectionUtils;
        return utils && utils.selectionLabel ? utils.selectionLabel(selection)
            : (selection ? (selection.product_group || selection.label || selection.name || selectionId(selection)) : '');
    }

    function selectionProducts(selection) {
        var utils = window.ProductPathSelectionUtils;
        if (utils && utils.selectionProducts) return utils.selectionProducts(selection);
        var raw = selection && (selection.products || selection.product_groups || []);
        return (raw || []).map(function(item) {
            if (typeof item === 'string') return { name: item, desc: '' };
            return item && item.name ? { name: item.name, desc: item.desc || '' } : null;
        }).filter(Boolean);
    }

    function cloneList(list) {
        var utils = window.ProductPathSelectionUtils;
        return utils && utils.cloneList ? utils.cloneList(list) : (Array.isArray(list) ? list.slice() : []);
    }

    function currentSelection() {
        var target = state.activeSelectionId;
        return state.selections.find(function(item) { return selectionId(item) === target; }) || state.selections[0] || null;
    }

    async function loadFactors() {
        if (state.factors.length || state.loadingFactors) return state.factors;
        state.loadingFactors = true;
        try {
            var alias = window.factorFamilyAlias || '';
            if (!alias) return [];
            var res = await fetch('/api/factor_list?factor_family_alias=' + encodeURIComponent(alias));
            var data = await res.json();
            state.factors = data && data.success && Array.isArray(data.factors) ? data.factors : [];
            return state.factors;
        } finally {
            state.loadingFactors = false;
        }
    }

    function renderControls() {
        var controls = document.getElementById('factor-series-controls');
        if (!controls) return;
        if (!state.selections.length) {
            controls.innerHTML = '';
            return;
        }
        var selection = currentSelection();
        var products = selectionProducts(selection);
        var factors = state.factors.length ? state.factors : (Array.isArray(window.factorList) ? window.factorList : []);
        var selectionOptions = state.selections.map(function(item) {
            var id = selectionId(item);
            return '<option value="' + escapeHtml(id) + '"' + (id === selectionId(selection) ? ' selected' : '') + '>'
                + escapeHtml(selectionLabel(item) || id)
                + '</option>';
        }).join('');
        var factorOptions = factors.map(function(factor) {
            var label = (factor.alias || factor.name || '') + (factor.freq ? ' · ' + factor.freq : '');
            return '<option value="' + escapeHtml(factor.alias || factor.name || '') + '" data-name="' + escapeHtml(factor.name || '') + '">'
                + escapeHtml(label)
                + '</option>';
        }).join('');
        var productOptions = products.map(function(product) {
            var desc = product.desc && product.desc !== product.name ? ' · ' + product.desc : '';
            return '<option value="' + escapeHtml(product.name) + '">'
                + escapeHtml(product.name + desc)
                + '</option>';
        }).join('');
        controls.innerHTML = ''
            + '<label class="factor-series-field"><span>产品路径</span><select id="factor-series-selection">' + selectionOptions + '</select></label>'
            + '<label class="factor-series-field"><span>因子</span><select id="factor-series-factor">' + (factorOptions || '<option value="">暂无因子</option>') + '</select></label>'
            + '<label class="factor-series-field"><span>品种</span><select id="factor-series-product">' + (productOptions || '<option value="">暂无品种</option>') + '</select></label>'
            + '<button type="button" id="factor-series-load-btn" class="factor-series-action">加载序列</button>';
        var selectionEl = document.getElementById('factor-series-selection');
        if (selectionEl) {
            selectionEl.addEventListener('change', function() {
                state.activeSelectionId = this.value;
                render();
            });
        }
        var loadBtn = document.getElementById('factor-series-load-btn');
        if (loadBtn) loadBtn.addEventListener('click', loadSeries);
    }

    function emptyMessage(text) {
        return '<div style="padding:24px;text-align:center;color:#94a3b8;font-size:12px;">' + escapeHtml(text) + '</div>';
    }

    async function render() {
        var chart = document.getElementById('factor-series-chart-container');
        if (!chart) return;
        if (!state.selections.length) {
            chart.innerHTML = emptyMessage('请先在对应测试模块中选择产品路径。');
            renderControls();
            return;
        }
        await loadFactors();
        renderControls();
        chart.innerHTML = emptyMessage('选择产品路径、因子和品种后加载序列。');
    }

    function parseTs(ts) {
        return typeof ts === 'string' ? new Date(ts + 'T00:00:00').getTime() : ts;
    }

    async function safeJson(response, label) {
        var text = await response.text();
        try { return JSON.parse(text); }
        catch (err) { throw new Error(label + ' 返回非 JSON (HTTP ' + response.status + '): ' + text.slice(0, 300)); }
    }

    function selectedFactor() {
        var select = document.getElementById('factor-series-factor');
        if (!select) return null;
        var alias = select.value;
        return state.factors.find(function(item) { return String(item.alias || item.name || '') === alias; })
            || (Array.isArray(window.factorList) ? window.factorList.find(function(item) { return String(item.alias || item.name || '') === alias; }) : null)
            || null;
    }

    async function loadSeries() {
        var chart = document.getElementById('factor-series-chart-container');
        if (!chart) return;
        var selection = currentSelection();
        var productEl = document.getElementById('factor-series-product');
        var product = productEl ? productEl.value : '';
        var factor = selectedFactor();
        if (!selection || !product || !factor) {
            chart.innerHTML = emptyMessage('请选择完整的产品路径、因子和品种。');
            return;
        }
        chart.innerHTML = emptyMessage('正在加载价格、因子值和收益标签...');
        var bodyBase = {
            product_path_selection_id: selectionId(selection),
            product_path_selection: selection,
            factor_family_alias: window.factorFamilyAlias || '',
            factor_name: factor.name || factor.alias,
            factor_alias: factor.alias || factor.name,
            product: product,
            page_uuid: window._pageUuid || '',
        };
        try {
            var factorData = await fetch('/get_factor_series', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(bodyBase),
            }).then(function(r) { return safeJson(r, 'get_factor_series'); });
            if (factorData.error) throw new Error('get_factor_series 错误: ' + factorData.error);

            var returnData = await fetch('/get_return_series', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(bodyBase),
            }).then(function(r) { return safeJson(r, 'get_return_series'); });
            if (returnData.error) throw new Error('get_return_series 错误: ' + returnData.error);

            var priceData = await fetch('/get_price_series', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(Object.assign({}, bodyBase, { factor_dates: factorData.dates })),
            }).then(function(r) { return safeJson(r, 'get_price_series'); });
            if (priceData.error) throw new Error('get_price_series 错误: ' + priceData.error);
            drawChart(chart, selection, product, factor, priceData, factorData, returnData);
        } catch (err) {
            chart.innerHTML = '<div style="padding:18px;color:#b91c1c;font-size:12px;">' + escapeHtml(err.message) + '</div>';
        }
    }

    function drawChart(container, selection, product, factor, priceData, factorData, returnData) {
        if (typeof Highcharts === 'undefined') {
            container.innerHTML = emptyMessage('Highcharts 未加载，无法显示序列。');
            return;
        }
        var dates = (factorData.dates || []).map(parseTs);
        var priceSeries = dates.map(function(ts, i) {
            return [ts, priceData.OPEN[i], priceData.HIGH[i], priceData.LOW[i], priceData.CLOSE[i]];
        });
        var factorSeries = dates.map(function(ts, i) { return [ts, factorData.values[i]]; });
        var returnSeries = (returnData.dates || []).map(function(ts, i) { return [parseTs(ts), returnData.values[i]]; });
        container.style.height = '620px';
        Highcharts.stockChart(container, {
            chart: { zoomType: 'x' },
            title: { text: (selectionLabel(selection) || selectionId(selection)) + ' · ' + product + ' · ' + (factor.alias || factor.name) },
            legend: { enabled: true },
            xAxis: { type: 'datetime' },
            yAxis: [
                { title: { text: '价格' }, height: '52%', resize: { enabled: true } },
                { title: { text: '因子值' }, top: '55%', height: '20%', opposite: true },
                { title: { text: '下一期收益率' }, top: '78%', height: '20%', opposite: true,
                  labels: { formatter: function() { return (this.value * 100).toFixed(2) + '%'; } } },
            ],
            tooltip: { split: true },
            series: [
                { name: '价格', type: 'candlestick', data: priceSeries, yAxis: 0 },
                { name: '因子值', type: 'line', data: factorSeries, yAxis: 1, color: '#f97316' },
                { name: '下一期收益率', type: 'line', data: returnSeries, yAxis: 2, color: '#16a34a' },
            ],
            navigator: { enabled: true },
            scrollbar: { enabled: true },
            rangeSelector: { enabled: true },
        });
    }

    function setSelections(selections) {
        state.selections = cloneList(selections);
        if (!state.selections.some(function(item) { return selectionId(item) === state.activeSelectionId; })) {
            state.activeSelectionId = state.selections.length ? selectionId(state.selections[0]) : '';
        }
        var body = document.getElementById('factor-series-viewer-body');
        if (body && body.style.display !== 'none') render();
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
        render: render,
    };

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
