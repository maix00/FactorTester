/** Factor series viewer: choose products from the product tree, choose a factor, run factor.evaluate, and display signals. */
(function() {
    var state = {
        paths: [],
        factors: [],
        lastSeries: [],
        activeProduct: '',
        treeReady: false,
        loadingFactors: false,
        progressValue: 0,
        productSelectorMounted: false,
        termTableLoading: false,
    };

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function bodyOpen() {
        var body = document.getElementById('factor-series-viewer-body');
        return body && body.style.display !== 'none';
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
            window.factorList = state.factors;
            return state.factors;
        } finally {
            state.loadingFactors = false;
        }
    }

    function renderFactorOptions() {
        var select = document.getElementById('factor-series-factor');
        if (!select) return;
        var previous = select.value;
        select.innerHTML = state.factors.map(function(factor) {
            var value = factor.alias || factor.name || '';
            var label = value + (factor.freq ? ' · ' + factor.freq : '');
            return '<option value="' + escapeHtml(value) + '"' + (value === previous ? ' selected' : '') + '>'
                + escapeHtml(label)
                + '</option>';
        }).join('') || '<option value="">暂无因子</option>';
    }

    function pathSummaryHtml() {
        if (!state.paths.length) {
            return '<span style="color:#94a3b8;">未选择产品路径</span>';
        }
        return state.paths.slice(0, 6).map(function(path) {
            return '<span class="factor-series-path-chip">' + escapeHtml(path) + '</span>';
        }).join('') + (state.paths.length > 6 ? '<span style="color:#64748b;">等 ' + state.paths.length + ' 条</span>' : '');
    }

    function renderPathSummary() {
        var html = pathSummaryHtml();
        var summary = document.getElementById('factor-series-path-summary');
        if (summary) summary.innerHTML = html;
    }

    function mountProductSelector() {
        if (state.productSelectorMounted) return;
        var root = document.getElementById('factor-series-product-selector-root');
        if (!root) return;
        if (!window.jQuery || !window.ProductSelector) {
            root.innerHTML = '<div style="padding:24px;text-align:center;color:#94a3b8;font-size:12px;">产品树组件未加载</div>';
            return;
        }
        if (typeof window.ProductSelector.render !== 'function' || typeof window.ProductSelector.initLeftTree !== 'function') {
            root.innerHTML = '<div style="padding:24px;text-align:center;color:#94a3b8;font-size:12px;">产品树能力不完整</div>';
            return;
        }

        var $root = window.jQuery(root);
        $root.html('');
        window.ProductSelector.render($root, {
            title: '选择产品',
            submitLabel: '完成',
            toolbar: '',
            headerBtns: '<button type="button" id="factor-series-products-close" style="background:none;border:none;font-size:20px;cursor:pointer;color:#888;">×</button>',
            onSubmit: function() {
                var overlay = document.getElementById('factor-series-products-overlay');
                if (overlay) overlay.style.display = 'none';
            },
        });

        window.ProductSelector.initLeftTree($root, {
            onlyLeaf: true,
            onInit: function(tree) {
                state.treeReady = true;
                window.ProductSelector.restoreChecks(tree, state.paths);
                state.paths = typeof window.ProductSelector.getLeafOnlyPaths === 'function'
                    ? window.ProductSelector.getLeafOnlyPaths(tree)
                    : [];
                renderPathSummary();
            },
            onSelect: function(paths) {
                state.paths = Array.isArray(paths) ? paths.slice() : [];
                renderPathSummary();
            },
        });

        state.productSelectorMounted = true;
    }

    function openProductTreeOverlay() {
        var overlay = document.getElementById('factor-series-products-overlay');
        if (!overlay) return;
        overlay.style.display = 'flex';
        mountProductSelector();
        renderPathSummary();
    }

    function message(text, isError) {
        return '<div style="padding:24px;text-align:center;color:' + (isError ? '#b91c1c' : '#94a3b8') + ';font-size:12px;">'
            + escapeHtml(text)
            + '</div>';
    }

    function getProgressEls() {
        return {
            wrapper: document.getElementById('factor-series-progress'),
            bar: document.getElementById('factor-series-progress-bar'),
            text: document.getElementById('factor-series-progress-text'),
            runBtn: document.getElementById('factor-series-run-btn'),
        };
    }

    function setProgress(value, text) {
        var ui = getProgressEls();
        var next = Math.max(0, Math.min(100, Math.floor(value)));
        if (ui.bar) {
            ui.bar.style.width = next + '%';
        }
        if (ui.text) {
            ui.text.textContent = text || (next + '%');
        }
        state.progressValue = next;
    }

    function showProgress() {
        var ui = getProgressEls();
        setProgress(0, '0%');
        if (ui.wrapper) {
            ui.wrapper.style.display = 'flex';
        }
        if (ui.runBtn) {
            ui.runBtn.disabled = true;
        }
    }

    function hideProgress(successText) {
        var ui = getProgressEls();
        setProgress(90, '计算中');
        if (ui.runBtn) {
            ui.runBtn.disabled = false;
        }
        setTimeout(function() {
            setProgress(100, successText || '完成');
            if (ui.wrapper) {
                ui.wrapper.style.display = 'none';
            }
        }, 800);
    }

    function failProgress(errorText) {
        var ui = getProgressEls();
        setProgress(0, errorText || '失败');
        if (ui.runBtn) {
            ui.runBtn.disabled = false;
        }
        if (ui.wrapper) {
            ui.wrapper.style.display = 'flex';
        }
        setTimeout(function() {
            if (ui.wrapper) {
                ui.wrapper.style.display = 'none';
            }
        }, 1200);
    }

    async function render() {
        await loadFactors();
        renderFactorOptions();
        renderPathSummary();
        var chart = document.getElementById('factor-series-chart-container');
        if (chart && !state.lastSeries.length) {
            chart.innerHTML = message('从产品树选择产品或路径，再选择因子并运行。');
        }
    }

    function selectedFactor() {
        var select = document.getElementById('factor-series-factor');
        if (!select) return null;
        var alias = select.value;
        return state.factors.find(function(factor) {
            return String(factor.alias || factor.name || '') === alias;
        }) || null;
    }

    async function runEvaluate() {
        var chart = document.getElementById('factor-series-chart-container');
        var status = document.getElementById('factor-series-status');
        var factor = selectedFactor();
        if (!chart) return;
        if (!state.paths.length) {
            chart.innerHTML = message('请先从产品树选择产品或路径。', true);
            return;
        }
        if (!factor) {
            chart.innerHTML = message('请先选择因子。', true);
            return;
        }
        if (status) status.textContent = '计算因子...';
        showProgress();
        chart.innerHTML = message('正在计算因子...');
        try {
            var res = await fetch('/api/factor_series_viewer/evaluate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    paths: state.paths,
                    factor_family_alias: window.factorFamilyAlias || '',
                    factor_alias: factor.alias || factor.name,
                    page_uuid: window._pageUuid || '',
                }),
            });
            var data = await res.json();
            if (!data.success) {
                throw new Error(data.error || ('HTTP ' + res.status));
            }
            state.lastSeries = Array.isArray(data.series) ? data.series : [];
            state.activeProduct = state.lastSeries.length ? state.lastSeries[0].product : '';
            renderProductChooser();
            drawActiveSeries(data.factor || factor);
            loadTermTable(state.activeProduct);
            var doneText = '完成：' + state.lastSeries.length + ' 个产品';
            if (data && data.meta && data.meta.elapsed_ms != null) {
                doneText += '（' + data.meta.elapsed_ms + 'ms）';
            }
            if (status) status.textContent = doneText;
            hideProgress('100%');
        } catch (err) {
            chart.innerHTML = message(err.message || String(err), true);
            if (status) status.textContent = '失败';
            failProgress('失败');
        }
    }

    function renderProductChooser() {
        var host = document.getElementById('factor-series-product-row');
        if (!host) return;
        if (!state.lastSeries.length) {
            host.innerHTML = '';
            return;
        }
        host.innerHTML = '<label class="factor-series-field"><span>显示产品</span><select id="factor-series-product">'
            + state.lastSeries.map(function(item) {
                var desc = item.desc && item.desc !== item.product ? ' · ' + item.desc : '';
                return '<option value="' + escapeHtml(item.product) + '"' + (item.product === state.activeProduct ? ' selected' : '') + '>'
                    + escapeHtml(item.product + desc)
                    + '</option>';
            }).join('')
            + '</select></label>';
        var select = document.getElementById('factor-series-product');
        if (select) {
            select.addEventListener('change', function() {
                state.activeProduct = this.value;
                drawActiveSeries(selectedFactor() || {});
                loadTermTable(state.activeProduct);
            });
        }
    }

    function normalizeProductForContractTable(productName) {
        if (!productName) return '';
        return String(productName);
    }

    function renderTermTableRows(contracts) {
        var container = document.getElementById('factor-series-term-table-container');
        var tbody = document.querySelector('#factor-series-term-table tbody');
        if (!container || !tbody) return;
        tbody.innerHTML = '';
        if (!contracts.length) {
            container.style.display = 'none';
            return;
        }
        for (var i = 0; i < contracts.length; i++) {
            var c = contracts[i];
            var tr = document.createElement('tr');
            var contractCell = c.has_data
                ? '<a href="/products?contract_uid=' + encodeURIComponent(c.uid) + '" title="查看合约信息">'
                    + escapeHtml(c.contract)
                    + '</a>'
                : '<span class="contract-name-muted" title="暂无价格数据，不能跳转">'
                    + escapeHtml(c.contract || '')
                    + '</span>';
            tr.innerHTML =
                '<td>' + contractCell + '</td>' +
                '<td>' + escapeHtml(c.start || c.start_ts || '') + '</td>' +
                '<td>' + escapeHtml(c.end || c.end_ts || '') + '</td>';
            tbody.appendChild(tr);
        }
        container.style.display = 'block';
    }

    async function loadTermTable(productName) {
        var container = document.getElementById('factor-series-term-table-container');
        var tbody = document.querySelector('#factor-series-term-table tbody');
        if (!container || !tbody) return;
        if (state.termTableLoading) return;
        if (!productName) {
            container.style.display = 'none';
            tbody.innerHTML = '';
            return;
        }

        state.termTableLoading = true;
        tbody.innerHTML = '<tr><td colspan="3" style="padding:12px 12px;color:#94a3b8;">加载期限信息...</td></tr>';
        container.style.display = 'block';

        try {
            var product = normalizeProductForContractTable(productName);
            var response = await fetch('/api/get_contracts?product=' + encodeURIComponent(product));
            var data = await response.json();
            if (!data.success || !data.contracts || data.contracts.length === 0) {
                container.style.display = 'none';
                return;
            }
            renderTermTableRows(data.contracts);
        } catch (err) {
            container.style.display = 'none';
        } finally {
            state.termTableLoading = false;
        }
    }

    function drawActiveSeries(factor) {
        var chart = document.getElementById('factor-series-chart-container');
        if (!chart) return;
        var item = state.lastSeries.find(function(series) { return series.product === state.activeProduct; }) || state.lastSeries[0];
        if (!item) {
            chart.innerHTML = message('没有可显示的因子序列。', true);
            return;
        }
        if (typeof window.FactorSeriesCharts === 'undefined' || typeof window.FactorSeriesCharts.renderDualSeriesChart !== 'function') {
            chart.innerHTML = message('图表渲染函数未加载，请刷新页面后重试。', true);
            return;
        }
        window.FactorSeriesCharts.renderDualSeriesChart({
            container: chart,
            title: item.product + ' · ' + (factor.alias || factor.name || '因子序列'),
            factorDates: item.dates,
            factorValues: item.values,
            factorName: factor.alias || factor.name || '因子值',
            factorAxisLabel: factor.alias || factor.name || '因子值',
            returnDates: item.returns ? item.returns.dates : [],
            returnValues: item.returns ? item.returns.values : [],
            returnName: '收益率',
            returnAxisLabel: '收益率',
        });
    }

    function init() {
        var header = document.getElementById('factor-series-header');
        var body = document.getElementById('factor-series-viewer-body');
        var runBtn = document.getElementById('factor-series-run-btn');
        var productsBtn = document.getElementById('factor-series-products-btn');
        var overlay = document.getElementById('factor-series-products-overlay');
        var closeBtn = document.getElementById('factor-series-products-close');
        var triangle = document.getElementById('factor-series-triangle');

        function setViewerOpen(open) {
            if (!body) return;
            var openState = !!open;
            body.style.display = openState ? '' : 'none';
            if (triangle) {
                triangle.style.transform = openState ? 'rotate(0deg)' : 'rotate(-90deg)';
            }
            if (openState) render();
        }

        if (header && body) {
            header.addEventListener('click', function() {
                var open = body.style.display !== 'none';
                setViewerOpen(!open);
            });
            setViewerOpen(false);
        }
        if (runBtn) {
            runBtn.addEventListener('click', function(event) {
                if (event && event.stopPropagation) {
                    event.stopPropagation();
                }
                runEvaluate();
            });
        }
        function closeOverlay() {
            if (overlay) overlay.style.display = 'none';
        }
        if (productsBtn && overlay) {
            productsBtn.addEventListener('click', function() {
                openProductTreeOverlay();
            });
        }
        if (closeBtn) closeBtn.addEventListener('click', closeOverlay);
        if (overlay) {
            overlay.addEventListener('click', function(event) {
                if (event.target === overlay) closeOverlay();
            });
        }
    }

    window.FactorSeriesViewer = {
        setSelections: function() {},
        getSelections: function() { return []; },
        render: function() { if (bodyOpen()) return render(); },
    };

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
