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
        var overlaySummary = document.getElementById('factor-series-overlay-summary');
        if (summary) summary.innerHTML = html;
        if (overlaySummary) overlaySummary.innerHTML = html;
    }

    function normalizeTreeSelections(tree) {
        var paths = [];
        if (!tree || !tree.visit) return paths;
        tree.visit(function(node) {
            if (!node || !node.selected) return;
            if (!node) return false;
            if (typeof node.isFolder === 'function') {
                if (node.isFolder()) {
                    node.setSelected(false);
                    return;
                }
            } else if (node.folder) {
                node.setSelected(false);
                return;
            }
            paths.push(node.key);
        });
        return paths;
    }

    function initTree() {
        var treeHost = document.getElementById('factor-series-tree');
        var chart = document.getElementById('factor-series-chart-container');
        if (!treeHost || state.treeReady) return;
        if (!window.ProductSelector || !window.jQuery || !jQuery.fn || !jQuery.fn.fancytree) {
            if (chart) chart.innerHTML = message('产品树依赖未加载，请刷新页面后重试。', true);
            return;
        }
        state.treeReady = true;
        window.ProductSelector.createTree(jQuery(treeHost), {
            onlyLeaf: true,
            onInit: function(tree) {
                window.ProductSelector.restoreChecks(tree, state.paths);
                state.paths = normalizeTreeSelections(tree);
                renderPathSummary();
            },
            onSelect: function(paths) {
                state.paths = Array.isArray(paths) ? paths.slice() : [];
                renderPathSummary();
            },
        });
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
        if (status) status.textContent = '运行 factor.evaluate...';
        showProgress();
        chart.innerHTML = message('正在运行 factor.evaluate...');
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
            });
        }
    }

    function drawActiveSeries(factor) {
        var chart = document.getElementById('factor-series-chart-container');
        var returnChart = document.getElementById('factor-series-return-chart-container');
        if (!chart) return;
        var item = state.lastSeries.find(function(series) { return series.product === state.activeProduct; }) || state.lastSeries[0];
        if (!item) {
            chart.innerHTML = message('没有可显示的因子序列。', true);
            if (returnChart) returnChart.innerHTML = '';
            return;
        }
        if (typeof window.FactorSeriesCharts === 'undefined' || typeof window.FactorSeriesCharts.renderFactorSeriesChart !== 'function') {
            chart.innerHTML = message('图表渲染函数未加载，请刷新页面后重试。', true);
            if (returnChart) returnChart.innerHTML = '';
            return;
        }
        window.FactorSeriesCharts.renderFactorSeriesChart({
            container: chart,
            title: item.product + ' · ' + (factor.alias || factor.name || '因子序列'),
            dates: item.dates,
            values: item.values,
            seriesName: factor.alias || factor.name || '因子值'
        });

        if (!returnChart) return;
        if (!item.returns || !Array.isArray(item.returns.dates) || !Array.isArray(item.returns.values) || item.returns.values.length === 0) {
            returnChart.innerHTML = '<div style="padding:24px;text-align:center;color:#94a3b8;font-size:12px;">收益序列不可用，请先确认当前因子在当前区间可计算收益。</div>';
            return;
        }
        window.FactorSeriesCharts.renderFactorSeriesChart({
            container: returnChart,
            title: item.product + ' · 收益序列',
            dates: item.returns.dates,
            values: item.returns.values,
            seriesName: '收益率',
            yAxisLabel: '收益'
        });
    }

    function init() {
        var btn = document.getElementById('factor-series-open-btn');
        var body = document.getElementById('factor-series-viewer-body');
        var runBtn = document.getElementById('factor-series-run-btn');
        var productsBtn = document.getElementById('factor-series-products-btn');
        var overlay = document.getElementById('factor-series-products-overlay');
        var closeBtn = document.getElementById('factor-series-products-close');
        var doneBtn = document.getElementById('factor-series-products-done');
        if (btn && body) {
            btn.addEventListener('click', function() {
                var open = body.style.display === 'none';
                body.style.display = open ? '' : 'none';
                btn.textContent = open ? '收起序列查看' : '打开序列查看';
                if (open) render();
            });
        }
        if (runBtn) runBtn.addEventListener('click', runEvaluate);
        function closeOverlay() {
            if (overlay) overlay.style.display = 'none';
        }
        if (productsBtn && overlay) {
            productsBtn.addEventListener('click', function() {
                overlay.style.display = 'flex';
                initTree();
                renderPathSummary();
            });
        }
        if (closeBtn) closeBtn.addEventListener('click', closeOverlay);
        if (doneBtn) doneBtn.addEventListener('click', closeOverlay);
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
