(function() {
    var state = {
        paths: [],
        factors: [],
        lastSeries: [],
        activeProduct: '',
        loadingFactors: false,
        progressValue: 0,
        termTableLoading: false,
        treeReady: false,
        tree: null,
        chart: null,
        allProductsMap: {},
        currentProduct: null,
        currentAdjusted: false,
    };

    var overlayProductReady = false;

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

    function isFunction(value) {
        return typeof value === 'function';
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
        if (ui.bar) ui.bar.style.width = next + '%';
        if (ui.text) ui.text.textContent = text || (next + '%');
        state.progressValue = next;
    }

    function showProgress() {
        var ui = getProgressEls();
        setProgress(0, '0%');
        if (ui.wrapper) ui.wrapper.style.display = 'flex';
        if (ui.runBtn) ui.runBtn.disabled = true;
    }

    function hideProgress(successText) {
        var ui = getProgressEls();
        setProgress(90, '计算中');
        if (ui.runBtn) ui.runBtn.disabled = false;
        setTimeout(function() {
            setProgress(100, successText || '完成');
            if (ui.wrapper) ui.wrapper.style.display = 'none';
        }, 600);
    }

    function failProgress(errorText) {
        var ui = getProgressEls();
        setProgress(0, errorText || '失败');
        if (ui.runBtn) ui.runBtn.disabled = false;
        if (ui.wrapper) ui.wrapper.style.display = 'flex';
        setTimeout(function() {
            if (ui.wrapper) ui.wrapper.style.display = 'none';
        }, 1000);
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
        } catch (err) {
            return [];
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
            return '<span style="color:#94a3b8;">未选择产品</span>';
        }
        return state.paths.slice(0, 6).map(function(path) {
            return '<span class="factor-series-path-chip">' + escapeHtml(path) + '</span>';
        }).join('') + (state.paths.length > 6 ? '<span style="color:#64748b;">等 ' + state.paths.length + ' 条</span>' : '');
    }

    function renderPathSummary() {
        var summary = document.getElementById('factor-series-path-summary');
        if (summary) summary.innerHTML = pathSummaryHtml();
    }

    function selectedFactor() {
        var select = document.getElementById('factor-series-factor');
        if (!select) return null;
        var alias = select.value;
        return state.factors.find(function(factor) {
            return String(factor.alias || factor.name || '') === alias;
        }) || null;
    }

    function extractProductName(node) {
        if (!node || !node.key) return null;
        var parts = String(node.key).split('/');
        var last = parts[parts.length - 1];
        if (last === '_products' || /^[0-9]+$/.test(last)) return null;
        return last;
    }

    function normalizeProductForContractApi(name) {
        return String(name == null ? '' : name);
    }

    function mountProductTree() {
        if (overlayProductReady) return;
        overlayProductReady = true;
        var container = document.getElementById('factor-series-tree-container');
        if (!container || !window.jQuery) return;
        container.innerHTML = '<div style="color:#888;text-align:center;padding:20px;">加载产品树...</div>';

        var $container = window.jQuery(container);
        $container.fancytree({
            source: { url: '/api/product_tree' },
            checkbox: false,
            selectMode: 1,
            init: function(e, data) {
                state.tree = data.tree;
                state.treeReady = true;
                var el = $container[0];
                if (el) {
                    el.addEventListener('wheel', function(ev) {
                        var scrollTop = el.scrollTop;
                        var maxScroll = el.scrollHeight - el.clientHeight;
                        var atTop = scrollTop <= 0;
                        var atBottom = scrollTop >= maxScroll - 1;
                        if ((ev.deltaY < 0 && atTop) || (ev.deltaY > 0 && atBottom)) return;
                        ev.preventDefault();
                        el.scrollTop = scrollTop + ev.deltaY;
                    }, {passive: false});
                }
            },
            lazyLoad: function(e, data) {
                var node = data.node;
                if (node.key && String(node.key).indexOf('CNFuturesContract') >= 0) {
                    data.result = { url: '/api/contract_tree', data: { path: node.key } };
                    return;
                }
                data.result = { url: '/get_products', data: { path: node.key, checkbox: 'false', series_variants: 'true' } };
            },
            renderNode: function(e, data) {
                var desc = data.node.data.desc;
                if (desc) {
                    var $title = window.jQuery(data.node.span).find('.fancytree-title');
                    $title.siblings('.node-description').remove();
                    $title.after('<span class="node-description" style="color:#888;margin-left:6px;font-size:12px;">' + escapeHtml(desc) + '</span>');
                }
            },
            activate: function(e, data) {
                var node = data.node;
                var nodeData = node ? node.data || {} : {};
                var productName = nodeData.product_name || extractProductName(node);
                if (!productName) return;
                if (nodeData.has_data === false) return;
                selectProduct(productName, nodeData);
            },
        });
    }

    function selectProduct(name, nodeData) {
        var data = Object.assign({}, state.allProductsMap[name] || {}, nodeData || {});
        if (!data || !data.name) {
            data = { name: name, code: name };
        }
        state.currentProduct = data;
        state.currentAdjusted = !!data.adjusted;
        state.paths = [String(name)];
        state.activeProduct = String(name);

        var infoTitle = (data.code || (String(data.name || '').split('.')[0] || String(data.name || ''))) + ' ' + (data.desc || data.name || '');
        var chartTitle = document.getElementById('factor-series-chart-title');
        if (chartTitle) chartTitle.textContent = infoTitle || '— 请选择品种 —';
        var selectedSummary = document.getElementById('factor-series-product-selected-summary');
        if (selectedSummary) selectedSummary.textContent = data.desc ? (data.name + ' · ' + data.desc) : data.name;

        renderPathSummary();

        var contractsWrap = document.getElementById('factor-series-contract-table-container');
        if (contractsWrap) contractsWrap.style.display = 'none';
        var tableBody = document.querySelector('#factor-series-contract-table tbody');
        if (tableBody) tableBody.innerHTML = '';

        var dsSelect = document.getElementById('factor-series-data-source');
        if (dsSelect) dsSelect.value = '';

        var contractUid = data.contract_uid;
        var isContract = data.product_type === 'contract' || contractUid;
        if (isContract) {
            factorSeriesUpdatePriceTypeControl(false, false);
            return factorSeriesLoadPriceData();
        }

        state.currentProduct = data;
        return loadTermTableForOverlay(data.name).then(function() {
            factorSeriesLoadPriceData();
        });
    }

    function loadOverlayProducts() {
        return fetch('/api/list_product_names')
            .then(function(res) { return res.json ? res.json() : {success:false}; })
            .then(function(data) {
                if (!data || !data.success || !Array.isArray(data.products)) return;
                for (var i = 0; i < data.products.length; i++) {
                    var p = data.products[i];
                    state.allProductsMap[p.name] = p;
                }
            })
            .catch(function() {
                state.allProductsMap = {};
            });
    }

    function updateTreeSelectionFromPaths() {
        if (!state.tree || !state.tree.findFirst) return;
        state.tree.visit(function(node) {
            if (!node || !node.key) return;
            var active = state.paths.indexOf(String(node.key)) >= 0;
            node.setSelected && node.setSelected(active);
        });
    }

    function openProductTreeOverlay() {
        var overlay = document.getElementById('factor-series-products-overlay');
        if (!overlay) return;
        overlay.style.display = 'flex';
        if (!overlayProductReady) {
            mountProductTree();
        }
        if (overlayProductReady) {
            updateTreeSelectionFromPaths();
        }
        renderPathSummary();
        var startDate = document.getElementById('factor-series-start-date');
        if (startDate && !startDate.value) startDate.value = '2024-01-01';
        var endDate = document.getElementById('factor-series-end-date');
        if (endDate && !endDate.value) endDate.value = new Date().toISOString().split('T')[0];
        if (!overlayProductReady) {
            loadOverlayProducts();
        }
    }

    function closeProductTreeOverlay() {
        var overlay = document.getElementById('factor-series-products-overlay');
        if (overlay) overlay.style.display = 'none';
    }

    async function render() {
        await loadFactors();
        renderFactorOptions();
        renderPathSummary();
        var chart = document.getElementById('factor-series-chart-container');
        if (chart && !state.lastSeries.length) {
            chart.innerHTML = message('从产品树选择产品，再选择因子并运行。');
        }
    }

    function renderProductChooser() {
        var host = document.getElementById('factor-series-product-row');
        if (!host) return;
        if (!state.lastSeries.length) {
            host.innerHTML = '';
            return;
        }
        host.innerHTML = '<label class="factor-series-field"><span>显示序列</span><select id="factor-series-product">'
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
                loadTermTable(this.value);
            });
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
        if (!window.FactorSeriesCharts || !isFunction(window.FactorSeriesCharts.renderDualSeriesChart)) {
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

    function renderTermTableRows(container, tbody, contracts) {
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
                ? '<a href="/products?contract_uid=' + encodeURIComponent(c.uid) + '" title="查看合约信息">' + escapeHtml(c.contract) + '</a>'
                : '<span class="contract-name-muted" title="暂无价格数据，不能跳转">' + escapeHtml(c.contract || '') + '</span>';
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
        container.style.display = 'block';
        tbody.innerHTML = '<tr><td colspan="3" style="padding:12px 12px;color:#94a3b8;">加载期限信息...</td></tr>';
        try {
            var response = await fetch('/api/get_contracts?product=' + encodeURIComponent(normalizeProductForContractApi(productName)));
            var data = await response.json();
            if (!data.success || !Array.isArray(data.contracts) || !data.contracts.length) {
                container.style.display = 'none';
                return;
            }
            renderTermTableRows(container, tbody, data.contracts);
        } catch (err) {
            container.style.display = 'none';
        } finally {
            state.termTableLoading = false;
        }
    }

    async function loadTermTableForOverlay(productName) {
        var container = document.getElementById('factor-series-contract-table-container');
        var tbody = document.querySelector('#factor-series-contract-table tbody');
        if (!container || !tbody) return;
        container.style.display = 'none';
        tbody.innerHTML = '';
        if (!productName) return;
        var resp = await fetch('/api/get_contracts?product=' + encodeURIComponent(normalizeProductForContractApi(productName)));
        var data = await resp.json();
        state.currentContracts = data && data.success ? (Array.isArray(data.contracts) ? data.contracts : []) : [];
        if (!state.currentContracts.length) return;
        renderTermTableRows(container, tbody, state.currentContracts);
        container.style.display = 'block';
    }

    async function runEvaluate() {
        var chart = document.getElementById('factor-series-chart-container');
        var status = document.getElementById('factor-series-status');
        var factor = selectedFactor();
        if (!chart) return;
        if (!state.paths.length) {
            chart.innerHTML = message('请先从产品树选择产品。', true);
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
            if (status) {
                var doneText = '完成：' + state.lastSeries.length + ' 个产品';
                if (data && data.meta && data.meta.elapsed_ms != null) {
                    doneText += '（' + data.meta.elapsed_ms + 'ms）';
                }
                status.textContent = doneText;
            }
            hideProgress('100%');
        } catch (err) {
            chart.innerHTML = message(err.message || String(err), true);
            if (status) status.textContent = '失败';
            failProgress('失败');
        }
    }

    function factorSeriesUpdatePriceTypeControl(supportsAdjusted, adjusted) {
        var wrap = document.getElementById('factor-series-price-type-wrap');
        var select = document.getElementById('factor-series-price-type');
        if (!wrap || !select) return;
        wrap.style.display = supportsAdjusted ? 'inline-flex' : 'none';
        wrap.style.alignItems = 'center';
        wrap.style.gap = '10px';
        state.currentAdjusted = Boolean(supportsAdjusted && adjusted);
        select.value = state.currentAdjusted ? 'adjusted' : 'raw';
    }

    function factorSeriesSetAdjusted(adjusted) {
        state.currentAdjusted = adjusted;
        var priceType = document.getElementById('factor-series-price-type');
        if (priceType) priceType.value = adjusted ? 'adjusted' : 'raw';
        if (state.currentProduct) factorSeriesLoadPriceData();
    }

    function factorSeriesUpdateFreqSelect(availableFreqs, currentFreq) {
        var select = document.getElementById('factor-series-freq');
        if (!select) return;
        var freqLabels = {
            'MIN1': '1分钟',
            'MIN5': '5分钟',
            'MIN15': '15分钟',
            'MIN30': '30分钟',
            'HOUR1': '1小时',
            'DAY1': '日线'
        };
        var freqs = availableFreqs || [];
        var oldValue = currentFreq || select.value;
        if (!freqs.length) {
            select.innerHTML = '<option value="">无可用频率</option>';
            select.disabled = true;
            return;
        }
        select.disabled = false;
        select.innerHTML = freqs.map(function(freq) {
            var label = freqLabels[freq] || freq;
            return '<option value="' + escapeHtml(freq) + '">' + escapeHtml(label) + '</option>';
        }).join('');
        if (oldValue && freqs.indexOf(oldValue) >= 0) select.value = oldValue;
    }

    function factorSeriesUpdateSourceSelect(availableSources, currentSource) {
        var select = document.getElementById('factor-series-data-source');
        if (!select) return;
        var selected = currentSource || select.value || '';
        var html = '<option value="">自动</option>';
        (availableSources || []).forEach(function(source) {
            var alias = source.alias || '';
            html += '<option value="' + escapeHtml(alias) + '">' + escapeHtml(alias + (source.freq ? ' · ' + source.freq : '')) + '</option>';
        });
        select.innerHTML = html;
        if (selected && Array.prototype.some.call(select.options, function(opt) { return opt.value === selected; })) {
            select.value = selected;
        }
    }

    function factorSeriesDrawChart(data) {
        var container = document.getElementById('factor-series-price-chart');
        if (!container) return;
        container.innerHTML = '';
        if (!window.Highcharts) return;

        var rows = data && Array.isArray(data.data) ? data.data : [];
        if (!rows.length) {
            container.innerHTML = '<div class="pv-empty" style="padding:80px 20px;color:#888;text-align:center;">'
                + (data && data.error ? escapeHtml(data.error) : '无价格数据')
                + '</div>';
            return;
        }
        rows = rows.slice().sort(function(a, b) {
            return (a.timestamp || 0) - (b.timestamp || 0);
        });

        var hasPriceNormalized = window.PriceDisplay && window.PriceDisplay.normalizePriceApi ? window.PriceDisplay.normalizePriceApi(data) : null;
        var ohlc = window.PriceDisplay && isFunction(window.PriceDisplay.toOhlc)
            ? window.PriceDisplay.toOhlc(rows)
            : rows.map(function(r) { return [r.timestamp, r.open, r.high, r.low, r.close]; });
        var volume = window.PriceDisplay && isFunction(window.PriceDisplay.toColumn)
            ? window.PriceDisplay.toColumn(rows, 'volume')
            : rows.map(function(r) { return [r.timestamp, r.volume]; });
        var hasOi = hasPriceNormalized ? hasPriceNormalized.has_open_interest : false;
        var oi = hasOi && (window.PriceDisplay && isFunction(window.PriceDisplay.toColumn))
            ? window.PriceDisplay.toColumn(rows, 'open_interest')
            : [];
        var freqStr = String(data.freq || '');
        var isIntraday = freqStr.indexOf('MIN') === 0 || freqStr.indexOf('HOUR') === 0 || freqStr.indexOf('SEC') === 0;
        var plotBands = [];
        if (data && data.supports_term_structure && data.contracts && data.contracts.length) {
            plotBands = data.contracts.map(function(item) {
                return { id: 'fs-contract-band', from: item.start_ts, to: item.end_ts, color: 'rgba(100,149,237,0.04)' };
            });
        }
        var yAxis = [{
            labels: { align: 'right', x: -3 },
            title: { text: '' },
            height: hasOi ? '50%' : '60%',
            lineWidth: 2,
            resize: { enabled: true },
            plotBands: plotBands
        }, {
            labels: { align: 'right', x: -3 },
            title: { text: '' },
            top: hasOi ? '55%' : '65%',
            height: hasOi ? '25%' : '35%',
            offset: 0,
            lineWidth: 2
        }];
        var series = [{
            type: 'candlestick',
            name: data.product || '价格',
            data: ohlc,
            tooltip: { pointFormat: '<span style="font-weight:bold">开盘</span> {point.open:.2f}<br/>'
                + '<span style="font-weight:bold">最高</span> {point.high:.2f}<br/>'
                + '<span style="font-weight:bold">最低</span> {point.low:.2f}<br/>'
                + '<span style="font-weight:bold">收盘</span> {point.close:.2f}'
            }
        }, {
            type: 'column',
            name: '成交量',
            data: volume,
            yAxis: 1,
            tooltip: { valueDecimals: 0 }
        }];
        if (hasOi) {
            yAxis.push({
                labels: { align: 'right', x: -3 },
                title: { text: '' },
                top: '82%',
                height: '18%',
                offset: 0,
                lineWidth: 2
            });
            series.push({
                type: 'line',
                name: '持仓量',
                data: oi,
                yAxis: 2,
                color: '#E91E63',
                tooltip: { valueDecimals: 0 }
            });
        }
        var title = data.product + (data.desc ? ' — ' + data.desc : '') + ' (' + (data.adjusted ? '复权' : '原始') + ')';
        var subtitle = (data.freq || 'Auto') + ' · ' + (data.count != null ? data.count : ohlc.length) + ' 条';
        state.chart = window.Highcharts.stockChart(container, {
            chart: { animation: false, height: Math.max(320, Math.floor(container.getBoundingClientRect().height || 420)) },
            title: { text: title, style: { fontSize: '15px' } },
            subtitle: { text: subtitle, style: { fontSize: '11px', color: '#888' } },
            rangeSelector: {
                buttons: [
                    { type: 'day', count: 3, text: '3天' },
                    { type: 'week', count: 1, text: '1周' },
                    { type: 'month', count: 1, text: '1月' },
                    { type: 'month', count: 3, text: '3月' },
                    { type: 'year', count: 1, text: '1年' },
                    { type: 'all', text: '全部' },
                ],
                selected: 4,
            },
            xAxis: {
                type: 'datetime',
                labels: {
                    rotation: -45,
                    align: 'right',
                    style: { fontSize: '10px', color: '#64748b' },
                    formatter: function() {
                        var d = new Date(this.value);
                        var hh = String(d.getHours()).padStart(2, '0');
                        var mm = String(d.getMinutes()).padStart(2, '0');
                        var M = String(d.getMonth() + 1).padStart(2, '0');
                        var dd = String(d.getDate()).padStart(2, '0');
                        return isIntraday ? hh + ':' + mm + '<br/>' + M + '-' + dd : M + '-' + dd;
                    }
                },
                ordinal: true,
            },
            yAxis: yAxis,
            tooltip: {
                shared: true,
                useHTML: true,
                formatter: function () {
                    var d = new Date(this.x);
                    var dateStr = isIntraday
                        ? d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0') + ' ' +
                            String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0')
                        : d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
                    var s = '<b>' + dateStr + '</b>';
                    this.points.forEach(function (p) {
                        if (p.series.type === 'candlestick') {
                            s += '<br/><span style="font-weight:bold">开盘</span> ' + p.point.open.toFixed(2) +
                                 '<br/><span style="font-weight:bold">最高</span> ' + p.point.high.toFixed(2) +
                                 '<br/><span style="font-weight:bold">最低</span> ' + p.point.low.toFixed(2) +
                                 '<br/><span style="font-weight:bold">收盘</span> ' + p.point.close.toFixed(2);
                        } else {
                            var decimals = typeof p.series.tooltipOptions.valueDecimals === 'number' ? p.series.tooltipOptions.valueDecimals : 2;
                            var val = typeof p.y === 'number' ? p.y.toFixed(decimals) : p.y;
                            s += '<br/>' + p.series.name + ': ' + val;
                        }
                    });
                    return s;
                }
            },
            series: series,
            credits: { enabled: false },
            navigator: { enabled: true },
            scrollbar: { enabled: false }
        });
    }

    window.factorSeriesLoadPriceData = factorSeriesLoadPriceData;
    window.factorSeriesSetAdjusted = factorSeriesSetAdjusted;

    async function factorSeriesLoadPriceData(freqOverride) {
        if (!state.currentProduct) return;
        var container = document.getElementById('factor-series-price-chart');
        if (!container) return;
        container.innerHTML = '<div class="pv-loading" style="padding:40px;text-align:center;color:#888;">加载中...</div>';
        var product = state.currentProduct;
        if (freqOverride) {
            var freqEl = document.getElementById('factor-series-freq');
            if (freqEl) freqEl.value = freqOverride;
        }
        var reqBody = {
            product_name: product.name || product.code,
            adjusted: !!state.currentAdjusted,
            series_variant: product.series_variant || 'primary_raw',
            freq: (document.getElementById('factor-series-freq') || {}).value || '',
            data_source: (document.getElementById('factor-series-data-source') || {}).value || null,
            start_date: (document.getElementById('factor-series-start-date') || {}).value || null,
            end_date: (document.getElementById('factor-series-end-date') || {}).value || null,
        };
        if (product.contract_uid || product.product_type === 'contract') {
            reqBody.contract_uid = product.contract_uid || product.name;
            reqBody.adjusted = false;
        }
        try {
            var resp = await fetch('/api/get_price_data', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(reqBody),
            });
            var data = await resp.json();
            if (data.success && data.data && data.data.length > 0) {
                var chartTitle = document.getElementById('factor-series-chart-info');
                if (chartTitle) chartTitle.textContent = data.product + ' | ' + (data.adjusted ? '复权' : '原始') + ' | ' + data.freq + ' | ' + data.count + ' 条';
                factorSeriesUpdatePriceTypeControl(data.supports_adjusted, data.adjusted);
                factorSeriesUpdateFreqSelect(data.available_freqs || [], data.freq);
                factorSeriesUpdateSourceSelect(data.available_sources || [], data.data_source);
                factorSeriesDrawChart(data);
                var tableWrap = document.getElementById('factor-series-contract-table-container');
                if (tableWrap && data.supports_term_structure && !reqBody.contract_uid && Array.isArray(state.currentContracts) && state.currentContracts.length > 0) {
                    tableWrap.style.display = 'block';
                } else if (tableWrap) {
                    tableWrap.style.display = 'none';
                }
                return;
            }
            container.innerHTML = '<div style="padding:40px 10px;color:#888;text-align:center;">' + escapeHtml((data && data.error) ? data.error : '无价格数据') + '</div>';
        } catch (e) {
            container.innerHTML = '<div style="padding:40px 10px;color:#888;text-align:center;">网络错误</div>';
        }
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
            if (triangle) triangle.style.transform = openState ? 'rotate(0deg)' : 'rotate(-90deg)';
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
                if (event && event.stopPropagation) event.stopPropagation();
                runEvaluate();
            });
        }
        if (productsBtn && overlay) {
            productsBtn.addEventListener('click', function() {
                openProductTreeOverlay();
            });
        }
        if (closeBtn) {
            closeBtn.addEventListener('click', closeProductTreeOverlay);
        }
        if (overlay) {
            overlay.addEventListener('click', function(event) {
                if (event.target === overlay) closeProductTreeOverlay();
            });
        }
    }

    window.FactorSeriesViewer = {
        setSelections: function() {},
        getSelections: function() { return []; },
        render: function() {
            if (bodyOpen()) return render();
        },
    };

    loadOverlayProducts();
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
