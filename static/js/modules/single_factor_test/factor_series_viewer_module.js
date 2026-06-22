(function() {
    var APP = 'factor_evaluation';
    var LOCAL = 'local-settings';
    var state = {
        manifest: null,
        tabCache: Object.create(null),
        mountedTabs: [],
        activeTab: null,
        values: Object.create(null),
        factors: [],
        paths: [],
        currentProduct: null,
        currentContracts: [],
        lastSeries: [],
        activeProduct: '',
        treeReady: false,
        tree: null,
        allProductsMap: {},
        chart: null,
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

    function isFunction(value) {
        return typeof value === 'function';
    }

    function currentFactorFamilyAlias() {
        if (window.factorFamilyAlias) return window.factorFamilyAlias;
        if (window._sftCurrentFactorId) return window._sftCurrentFactorId;
        var module = document.getElementById('factor_series_viewer_module');
        if (module && module.dataset && module.dataset.factorFamilyAlias) return module.dataset.factorFamilyAlias;
        var section = document.querySelector('[data-factor-alias]');
        if (section && section.dataset && section.dataset.factorAlias) return section.dataset.factorAlias;
        var params = new URLSearchParams(window.location.search || '');
        return params.get('factor') || '';
    }

    function currentOwnerUsername() {
        if (window._sftCurrentOwner) return window._sftCurrentOwner;
        var params = new URLSearchParams(window.location.search || '');
        return params.get('owner_username') || '';
    }

    function bodyOpen() {
        var body = document.getElementById('factor-series-viewer-body');
        return body && body.style.display !== 'none';
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
    }

    function showProgress() {
        var ui = getProgressEls();
        setProgress(0, '0%');
        if (ui.wrapper) ui.wrapper.style.display = 'flex';
        if (ui.runBtn) ui.runBtn.disabled = true;
    }

    function hideProgress(successText) {
        var ui = getProgressEls();
        setProgress(100, successText || '完成');
        if (ui.runBtn) ui.runBtn.disabled = false;
        setTimeout(function() {
            if (ui.wrapper) ui.wrapper.style.display = 'none';
        }, 500);
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

    function requestJSON(url, options) {
        return fetch(url, options || {}).then(function(response) {
            return response.json().catch(function() { return {}; }).then(function(payload) {
                if (!response.ok || payload.success === false) {
                    throw new Error(payload.error || ('HTTP ' + response.status));
                }
                return payload;
            });
        });
    }

    function defaults() {
        return state.manifest && state.manifest.defaults ? state.manifest.defaults : {};
    }

    function settingMeta(key) {
        return defaults()[key] || null;
    }

    function tabMeta(tabKey) {
        var tabs = state.manifest && state.manifest.tab_lists ? (state.manifest.tab_lists[LOCAL] || []) : [];
        for (var i = 0; i < tabs.length; i++) {
            if (tabs[i].key === tabKey) return tabs[i];
        }
        return null;
    }

    function settingKeysForTab(tabKey) {
        var out = [];
        var defs = defaults();
        Object.keys(defs).forEach(function(key) {
            if (defs[key] && defs[key].tab_key === tabKey) out.push(key);
        });
        return out;
    }

    function effectiveValue(key) {
        if (Object.prototype.hasOwnProperty.call(state.values, key)) return state.values[key];
        var meta = settingMeta(key);
        return meta ? meta.value : '';
    }

    function displayValue(setting, value) {
        if (setting && Array.isArray(setting.options)) {
            for (var i = 0; i < setting.options.length; i++) {
                if (String(setting.options[i].value) === String(value)) return setting.options[i].label;
            }
        }
        if (setting && setting.key === 'product') {
            return productLabel();
        }
        if (setting && setting.key === 'factor') {
            var factor = selectedFactor();
            return factor ? factor.alias || factor.name || '' : '';
        }
        return value === undefined || value === null || value === '' ? '自动' : String(value);
    }

    function chipParts(labelOrText, value) {
        if (value !== undefined && value !== null && value !== '') {
            return { label: String(labelOrText || ''), value: String(value) };
        }
        var text = String(labelOrText == null ? '' : labelOrText).trim();
        var match = text.match(/^([^:：]{1,16})[:：]\s*(.*)$/);
        if (match && match[2]) return { label: match[1], value: match[2] };
        return { label: '', value: text };
    }

    function renderChipHtml(text, value) {
        var parts = chipParts(text, value);
        if (!parts.label) return '<span class="gt-backend-chip-value">' + escapeHtml(parts.value) + '</span>';
        return '<span class="gt-backend-chip-label">' + escapeHtml(parts.label) + '</span>'
            + '<span class="gt-backend-chip-value">' + escapeHtml(parts.value) + '</span>';
    }

    function chipText(setting, value) {
        var template = setting && setting.chip_template ? setting.chip_template : ((setting && setting.key || '') + ': {value}');
        return template.replace('{value}', displayValue(setting, value));
    }

    function makeChip(setting, value) {
        var node = document.createElement('span');
        node.className = 'gt-backend-chip factor-series-settings-chip';
        node.innerHTML = renderChipHtml(chipText(setting, value));
        return node;
    }

    function productLabel() {
        if (!state.currentProduct) return '';
        var name = state.currentProduct.name || state.activeProduct || '';
        var desc = state.currentProduct.desc || '';
        return desc && desc !== name ? name + ' · ' + desc : name;
    }

    function mountedSettingKeys() {
        var keys = {};
        state.mountedTabs.forEach(function(tabKey) {
            settingKeysForTab(tabKey).forEach(function(key) { keys[key] = true; });
        });
        return keys;
    }

    function renderSettingChips() {
        var row = document.getElementById('factor-series-settings-chip-row');
        if (!row || !state.manifest) return;
        row.innerHTML = '';
        state.mountedTabs.forEach(function(tabKey) {
            var manifest = state.tabCache[tabKey];
            if (!manifest) {
                loadTab(tabKey).then(renderSettingChips).catch(function() {});
                return;
            }
            (manifest.settings || []).forEach(function(setting) {
                var value = effectiveValue(setting.key);
                if (setting.key === 'product' && !state.currentProduct) return;
                if (setting.key === 'factor' && !selectedFactor()) return;
                row.appendChild(makeChip(setting, value));
            });
        });
    }

    function renderResultChips() {
        var row = document.getElementById('factor-series-result-chip-row');
        if (!row || !state.manifest) return;
        row.innerHTML = '';
        var mountedKeys = mountedSettingKeys();
        Object.keys(defaults()).forEach(function(key) {
            if (mountedKeys[key]) return;
            var setting = Object.assign({ key: key }, defaults()[key] || {});
            if (!setting.chip_template) return;
            row.appendChild(makeChip(setting, effectiveValue(key)));
        });
    }

    function loadManifest() {
        if (state.manifest) return Promise.resolve(state.manifest);
        var pageUuid = encodeURIComponent(window._pageUuid || '');
        return requestJSON('/api/backtest/settings/' + APP + '?page_uuid=' + pageUuid).then(function(manifest) {
            state.manifest = manifest;
            state.mountedTabs = (manifest.default_mounted_tabs && manifest.default_mounted_tabs[LOCAL] || []).slice();
            Object.keys(manifest.defaults || {}).forEach(function(key) {
                state.values[key] = manifest.defaults[key].value;
            });
            return manifest;
        });
    }

    function tabURL(tabKey) {
        return state.manifest.tab_url_template.replace('{tab_key}', encodeURIComponent(tabKey));
    }

    function factorsFromParamTable() {
        var tbody = document.getElementById('factor_table_body');
        if (!tbody) return [];
        return Array.from(tbody.querySelectorAll('tr')).filter(function(row) {
            return row.id !== 'add_row' && row.style.display !== 'none';
        }).map(function(row) {
            var firstCell = row.querySelector('td:first-child');
            var alias = firstCell ? (firstCell.textContent || '').trim() : '';
            if (!alias) return null;
            return { alias: alias, name: alias, source: 'params_table' };
        }).filter(Boolean);
    }

    function syncFactorsFromParamTable() {
        var rows = factorsFromParamTable();
        if (!rows.length) return false;
        state.factors = rows;
        window.factorList = rows;
        var current = effectiveValue('factor');
        var exists = rows.some(function(factor) {
            return String(factor.alias || factor.name || '') === String(current);
        });
        if (!exists) state.values.factor = rows[0].alias || rows[0].name || '';
        return true;
    }

    function loadTab(tabKey) {
        if (state.tabCache[tabKey]) return Promise.resolve(state.tabCache[tabKey]);
        return requestJSON(tabURL(tabKey)).then(function(manifest) {
            state.tabCache[tabKey] = manifest;
            return manifest;
        });
    }

    async function loadFactors() {
        if (syncFactorsFromParamTable()) return state.factors;
        if (state.factors.length || state.loadingFactors) return state.factors;
        state.loadingFactors = true;
        try {
            var alias = currentFactorFamilyAlias();
            if (!alias) return [];
            var params = new URLSearchParams();
            params.set('factor_family_alias', alias);
            if (window._pageUuid) params.set('page_uuid', window._pageUuid);
            var owner = currentOwnerUsername();
            if (owner) params.set('owner_username', owner);
            var data = await requestJSON('/api/factor_list?' + params.toString());
            state.factors = Array.isArray(data.factors) ? data.factors : [];
            window.factorList = state.factors;
            if (!effectiveValue('factor') && state.factors.length) {
                state.values.factor = state.factors[0].alias || state.factors[0].name || '';
            }
            return state.factors;
        } finally {
            state.loadingFactors = false;
        }
    }

    function selectedFactor() {
        syncFactorsFromParamTable();
        var alias = effectiveValue('factor');
        if (!alias) return null;
        return state.factors.find(function(factor) {
            return String(factor.alias || factor.name || '') === String(alias);
        }) || null;
    }

    function optionHtml(value, label, selected) {
        return '<option value="' + escapeHtml(value) + '"' + (String(value) === String(selected) ? ' selected' : '') + '>'
            + escapeHtml(label)
            + '</option>';
    }

    function renderTabBar() {
        var bar = document.getElementById('factor-series-settings-tab-bar');
        if (!bar || !state.manifest) return;
        bar.innerHTML = '';
        var tabs = state.manifest.tab_lists && state.manifest.tab_lists[LOCAL] || [];
        tabs.forEach(function(tab) {
            if (state.mountedTabs.indexOf(tab.key) < 0) return;
            var button = document.createElement('button');
            button.type = 'button';
            button.textContent = tab.label;
            button.className = state.activeTab === tab.key ? 'active' : '';
            button.addEventListener('click', function() { openTab(tab.key); });
            bar.appendChild(button);
        });
        var manage = document.createElement('button');
        manage.type = 'button';
        manage.textContent = '+ 设置';
        manage.className = state.activeTab === '__manage__' ? 'active' : '';
        manage.addEventListener('click', function() { openTab('__manage__'); });
        bar.appendChild(manage);
    }

    function writeValue(key, value) {
        state.values[key] = value;
        if (key === 'product') {
            renderPathSummary();
        }
        renderSettingChips();
        renderResultChips();
    }

    function renderManifestTab(manifest) {
        var host = document.getElementById('factor-series-settings-host');
        if (!host) return;
        host.innerHTML = '';
        (manifest.settings || []).forEach(function(setting) {
            var row = document.createElement('label');
            row.className = 'factor-series-setting-row';
            if (setting.key === 'product') row.className += ' factor-series-setting-row-wide';
            var label = document.createElement('span');
            label.className = 'factor-series-setting-label';
            label.textContent = setting.label;
            var controlWrap = document.createElement('span');
            controlWrap.className = 'factor-series-setting-control';
            controlWrap.appendChild(makeControl(setting));
            if (setting.key !== 'product') row.appendChild(label);
            row.appendChild(controlWrap);
            host.appendChild(row);
        });
    }

    function makeControl(setting) {
        if (setting.key === 'product') {
            var wrap = document.createElement('div');
            wrap.className = 'factor-series-product-tab';
            var summary = document.createElement('span');
            summary.id = 'factor-series-path-summary';
            summary.className = 'factor-series-path-summary';
            wrap.appendChild(summary);
            var treeWrap = document.createElement('div');
            treeWrap.className = 'factor-series-tab-tree-wrap product-tree-scrollbox';
            treeWrap.innerHTML = '<div id="factor-series-tree-container" class="factor-series-tab-tree"></div>';
            wrap.appendChild(treeWrap);
            setTimeout(renderPathSummary, 0);
            setTimeout(mountProductTree, 0);
            return wrap;
        }
        var control = document.createElement('select');
        if (setting.key === 'factor') {
            state.factors.forEach(function(factor) {
                var value = factor.alias || factor.name || '';
                var label = value + (factor.freq ? ' · ' + factor.freq : '');
                control.insertAdjacentHTML('beforeend', optionHtml(value, label, effectiveValue(setting.key)));
            });
        } else {
            (setting.options || []).forEach(function(option) {
                control.insertAdjacentHTML('beforeend', optionHtml(option.value, option.label, effectiveValue(setting.key)));
            });
        }
        control.addEventListener('change', function() {
            writeValue(setting.key, control.value);
            if (setting.key === 'data_source') writeValue('frequency', '');
            if (setting.key === 'frequency') writeValue('data_source', '');
            if (state.currentProduct && (setting.key === 'data_source' || setting.key === 'frequency' || setting.key === 'price_type')) {
                loadPriceDataForCurrentProduct().then(function(priceData) {
                    drawResultChart(priceData, selectedSeriesItem(), selectedFactor() || {});
                }).catch(showResultError);
            }
        });
        return control;
    }

    function renderChooser() {
        var host = document.getElementById('factor-series-settings-host');
        if (!host || !state.manifest) return;
        host.innerHTML = '';
        var tabs = state.manifest.tab_lists && state.manifest.tab_lists[LOCAL] || [];
        tabs.forEach(function(tab) {
            var row = document.createElement('label');
            row.className = 'factor-series-setting-row';
            var label = document.createElement('span');
            label.className = 'factor-series-setting-label';
            label.textContent = tab.label;
            var wrap = document.createElement('span');
            wrap.className = 'factor-series-setting-control';
            var input = document.createElement('input');
            input.type = 'checkbox';
            input.checked = state.mountedTabs.indexOf(tab.key) >= 0;
            input.addEventListener('change', function() {
                var idx = state.mountedTabs.indexOf(tab.key);
                if (input.checked && idx < 0) state.mountedTabs.push(tab.key);
                if (!input.checked && idx >= 0) {
                    state.mountedTabs.splice(idx, 1);
                    settingKeysForTab(tab.key).forEach(function(key) { delete state.values[key]; });
                }
                renderTabBar();
                renderSettingChips();
                renderResultChips();
            });
            wrap.appendChild(input);
            row.appendChild(label);
            row.appendChild(wrap);
            host.appendChild(row);
        });
    }

    function openTab(tabKey) {
        var host = document.getElementById('factor-series-settings-host');
        if (!host) return;
        if (state.activeTab === tabKey && host.style.display !== 'none') {
            state.activeTab = null;
            host.style.display = 'none';
            renderTabBar();
            return;
        }
        state.activeTab = tabKey;
        host.style.display = '';
        renderTabBar();
        if (tabKey === '__manage__') {
            renderChooser();
            return;
        }
        host.innerHTML = '<span style="color:#64748b;font-size:12px;">正在加载...</span>';
        if (tabKey === 'factor') syncFactorsFromParamTable();
        loadTab(tabKey).then(function(manifest) {
            if (tabKey === 'factor') syncFactorsFromParamTable();
            renderManifestTab(manifest);
            renderSettingChips();
        }).catch(function(error) {
            host.textContent = '加载失败：' + error.message;
        });
    }

    function renderPathSummary() {
        var summary = document.getElementById('factor-series-path-summary');
        if (!summary) return;
        if (!state.paths.length) {
            summary.innerHTML = '<span style="color:#94a3b8;">未选择产品</span>';
            return;
        }
        summary.innerHTML = state.paths.slice(0, 4).map(function(path) {
            return '<span class="gt-backend-chip factor-series-path-chip">' + renderChipHtml(path) + '</span>';
        }).join('');
    }

    function extractProductName(node) {
        if (!node || !node.key) return null;
        var data = node.data || {};
        if (data.product_name) return data.product_name;
        if (data.has_data === false) return null;
        var parts = String(node.key).split('/');
        var last = parts[parts.length - 1];
        if (last === '_products' || /^[0-9]+$/.test(last)) return null;
        return last;
    }

    function mountProductTree() {
        var container = document.getElementById('factor-series-tree-container');
        if (!container || !window.jQuery) return;
        if (container.dataset.ready === '1') return;
        container.dataset.ready = '1';
        container.textContent = '';
        var $container = window.jQuery(container);
        $container.fancytree({
            source: { url: '/api/product_tree' },
            checkbox: false,
            selectMode: 1,
            init: function(e, data) {
                state.tree = data.tree;
                state.treeReady = true;
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
                var productName = extractProductName(node);
                if (!productName || nodeData.has_data === false) return;
                selectProduct(productName, nodeData, node.key);
            },
        });
    }

    function loadOverlayProducts() {
        return fetch('/api/list_product_names')
            .then(function(res) { return res.json ? res.json() : {success:false}; })
            .then(function(data) {
                if (!data || !data.success || !Array.isArray(data.products)) return;
                data.products.forEach(function(p) { state.allProductsMap[p.name] = p; });
            })
            .catch(function() { state.allProductsMap = {}; });
    }

    function selectProduct(name, nodeData, path) {
        var data = Object.assign({}, state.allProductsMap[name] || {}, nodeData || {});
        if (!data || !data.name) data = { name: name, code: name };
        state.currentProduct = data;
        state.paths = [String(path || name)];
        state.activeProduct = String(name);
        writeValue('product', String(name));
        var title = document.getElementById('factor-series-chart-title');
        if (title) title.textContent = productLabel() || '— 请选择品种 —';
        var selectedSummary = document.getElementById('factor-series-product-selected-summary');
        if (selectedSummary) selectedSummary.textContent = productLabel();
        loadTermTable(data.name);
        loadPriceDataForCurrentProduct().then(function(priceData) {
            drawResultChart(priceData, selectedSeriesItem(), selectedFactor() || {});
        }).catch(showResultError);
    }

    function normalizeProductForContractApi(name) {
        return String(name == null ? '' : name);
    }

    function renderTermTableRows(container, tbody, contracts) {
        if (!container || !tbody) return;
        tbody.innerHTML = '';
        if (!contracts.length) {
            container.style.display = 'none';
            return;
        }
        contracts.forEach(function(c) {
            var tr = document.createElement('tr');
            var contractCell = c.has_data
                ? '<a href="/products?contract_uid=' + encodeURIComponent(c.uid) + '" title="查看合约信息">' + escapeHtml(c.contract) + '</a>'
                : '<span class="contract-name-muted" title="暂无价格数据，不能跳转">' + escapeHtml(c.contract || '') + '</span>';
            tr.innerHTML = '<td>' + contractCell + '</td>'
                + '<td>' + escapeHtml(c.start || c.start_ts || '') + '</td>'
                + '<td>' + escapeHtml(c.end || c.end_ts || '') + '</td>';
            tbody.appendChild(tr);
        });
        container.style.display = 'block';
    }

    async function loadTermTable(productName) {
        var container = document.getElementById('factor-series-term-table-container');
        var tbody = document.querySelector('#factor-series-term-table tbody');
        if (!container || !tbody) return;
        container.style.display = 'none';
        tbody.innerHTML = '';
        if (!productName) return;
        try {
            var data = await requestJSON('/api/get_contracts?product=' + encodeURIComponent(normalizeProductForContractApi(productName)));
            state.currentContracts = Array.isArray(data.contracts) ? data.contracts : [];
            renderTermTableRows(container, tbody, state.currentContracts);
        } catch (err) {
            state.currentContracts = [];
            container.style.display = 'none';
        }
    }

    function priceTypeAdjusted() {
        return effectiveValue('price_type') !== 'raw';
    }

    async function loadPriceDataForCurrentProduct() {
        if (!state.currentProduct) return null;
        var product = state.currentProduct;
        var reqBody = {
            product_name: product.name || product.code,
            adjusted: priceTypeAdjusted(),
            series_variant: product.series_variant || 'primary_raw',
            freq: effectiveValue('frequency') || '',
            data_source: effectiveValue('data_source') || null,
        };
        if (product.contract_uid || product.product_type === 'contract') {
            reqBody.contract_uid = product.contract_uid || product.name;
            reqBody.adjusted = false;
        }
        var data = await requestJSON('/api/get_price_data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(reqBody),
        });
        updateDynamicPriceOptions(data);
        return data;
    }

    function updateDynamicPriceOptions(data) {
        var freqMeta = settingMeta('frequency');
        if (freqMeta) {
            freqMeta.options = [{ value: '', label: '自动' }].concat((data.available_freqs || []).map(function(freq) {
                var labels = { MIN1: '1分钟', MIN5: '5分钟', MIN15: '15分钟', MIN30: '30分钟', HOUR1: '1小时', DAY1: '日线' };
                return { value: freq, label: labels[freq] || freq };
            }));
        }
        var sourceMeta = settingMeta('data_source');
        if (sourceMeta) {
            sourceMeta.options = [{ value: '', label: '自动' }].concat((data.available_sources || []).map(function(source) {
                var alias = source.alias || '';
                return { value: alias, label: alias + (source.freq ? ' · ' + source.freq : '') };
            }));
        }
        if (state.activeTab === 'frequency' || state.activeTab === 'data_source') refreshActiveTab();
        renderResultChips();
    }

    function refreshActiveTab() {
        if (!state.activeTab || state.activeTab === '__manage__') return;
        var manifest = state.tabCache[state.activeTab];
        if (manifest) renderManifestTab(manifest);
    }

    function selectedSeriesItem() {
        return state.lastSeries.find(function(series) { return series.product === state.activeProduct; }) || state.lastSeries[0] || null;
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
                loadTermTable(this.value);
                loadPriceDataForCurrentProduct().then(function(priceData) {
                    drawResultChart(priceData, selectedSeriesItem(), selectedFactor() || {});
                }).catch(showResultError);
            });
        }
    }

    function pointTime(ts) {
        if (typeof ts === 'number') return ts;
        var d = new Date(ts);
        return isNaN(d.getTime()) ? new Date(String(ts) + 'T00:00:00').getTime() : d.getTime();
    }

    function factorPoints(item) {
        if (!item || !Array.isArray(item.dates) || !Array.isArray(item.values)) return [];
        var rows = [];
        for (var i = 0; i < item.dates.length && i < item.values.length; i++) {
            var t = pointTime(item.dates[i]);
            var v = item.values[i];
            if (t != null && v != null && !Number.isNaN(Number(v))) rows.push([t, v]);
        }
        return rows;
    }

    function drawResultChart(priceData, item, factor) {
        var container = document.getElementById('factor-series-chart-container');
        if (!container) return;
        container.innerHTML = '';
        if (!window.Highcharts) {
            container.innerHTML = message('Highcharts 未加载，无法显示图表。', true);
            return;
        }
        var rows = priceData && Array.isArray(priceData.data) ? priceData.data.slice().sort(function(a, b) {
            return (a.timestamp || 0) - (b.timestamp || 0);
        }) : [];
        var factorData = factorPoints(item);
        if (!rows.length && !factorData.length) {
            container.innerHTML = message('没有可显示的价格或因子序列。', true);
            return;
        }
        var priceSeries = window.PriceDisplay && window.PriceDisplay.normalizePriceApi ? window.PriceDisplay.normalizePriceApi(priceData) : null;
        var ohlc = window.PriceDisplay && isFunction(window.PriceDisplay.toOhlc)
            ? window.PriceDisplay.toOhlc(rows)
            : rows.map(function(r) { return [r.timestamp, r.open, r.high, r.low, r.close]; });
        var volume = window.PriceDisplay && isFunction(window.PriceDisplay.toColumn)
            ? window.PriceDisplay.toColumn(rows, 'volume')
            : rows.map(function(r) { return [r.timestamp, r.volume]; });
        var hasOi = priceSeries ? priceSeries.has_open_interest : false;
        var oi = hasOi && window.PriceDisplay && isFunction(window.PriceDisplay.toColumn)
            ? window.PriceDisplay.toColumn(rows, 'open_interest')
            : [];
        var yAxis = [{
            labels: { align: 'right', x: -3 },
            title: { text: '价格' },
            height: hasOi ? '48%' : '54%',
            resize: { enabled: true },
            lineWidth: 2,
        }, {
            labels: { align: 'right', x: -3 },
            title: { text: '因子' },
            top: hasOi ? '52%' : '59%',
            height: hasOi ? '22%' : '23%',
            opposite: true,
        }, {
            labels: { align: 'right', x: -3 },
            title: { text: '成交量' },
            top: hasOi ? '77%' : '84%',
            height: hasOi ? '10%' : '15%',
            opposite: true,
        }];
        var series = [];
        if (ohlc.length) {
            series.push({ type: 'candlestick', name: priceData.product || '价格', data: ohlc, yAxis: 0, legendIndex: 10 });
        }
        if (factorData.length) {
            series.push({ type: 'line', name: factor.alias || factor.name || '因子值', data: factorData, yAxis: 1, color: '#2563eb', legendIndex: 20, dataGrouping: { enabled: false } });
        }
        if (volume.length) {
            series.push({ type: 'column', name: '成交量', data: volume, yAxis: 2, color: '#90CAF9', legendIndex: 30 });
        }
        if (hasOi) {
            yAxis.push({
                labels: { align: 'right', x: -3 },
                title: { text: '持仓量' },
                top: '90%',
                height: '10%',
                opposite: true,
            });
            series.push({ type: 'line', name: '持仓量', data: oi, yAxis: 3, color: '#E91E63', legendIndex: 40 });
        }
        var title = productLabel() || (priceData && priceData.product) || '因子评估';
        state.chart = window.Highcharts.stockChart(container, {
            chart: { animation: false, height: Math.max(520, Math.floor(container.getBoundingClientRect().height || 520)) },
            title: { text: title, style: { fontSize: '15px' } },
            subtitle: { text: (priceData ? ((priceData.adjusted ? '复权' : '原始') + ' · ' + priceData.freq + ' · ' + priceData.count + ' 条') : ''), style: { fontSize: '11px', color: '#888' } },
            rangeSelector: { enabled: true },
            navigator: { enabled: true },
            scrollbar: { enabled: true },
            legend: { enabled: true },
            xAxis: { type: 'datetime', ordinal: true },
            yAxis: yAxis,
            tooltip: { split: true, valueDecimals: 6 },
            series: series,
            credits: { enabled: false },
        });
    }

    function showResultError(error) {
        var chart = document.getElementById('factor-series-chart-container');
        if (chart) chart.innerHTML = message(error.message || String(error), true);
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
            setProgress(25, '计算因子');
            var data = await requestJSON('/api/factor_evaluation/evaluate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    paths: state.paths,
                    factor_family_alias: currentFactorFamilyAlias(),
                    factor_alias: factor.alias || factor.name,
                    page_uuid: window._pageUuid || '',
                    settings: Object.assign({}, state.values),
                }),
            });
            state.lastSeries = Array.isArray(data.series) ? data.series : [];
            state.activeProduct = state.lastSeries.length ? state.lastSeries[0].product : state.activeProduct;
            renderProductChooser();
            setProgress(70, '加载价格');
            var priceData = await loadPriceDataForCurrentProduct();
            drawResultChart(priceData, selectedSeriesItem(), data.factor || factor);
            renderResultChips();
            if (status) {
                var doneText = '完成：' + state.lastSeries.length + ' 个产品';
                if (data.meta && data.meta.elapsed_ms != null) doneText += '（' + data.meta.elapsed_ms + 'ms）';
                status.textContent = doneText;
            }
            hideProgress('100%');
        } catch (err) {
            chart.innerHTML = message(err.message || String(err), true);
            if (status) status.textContent = '失败';
            failProgress('失败');
        }
    }

    async function render() {
        await loadManifest();
        await loadFactors();
        renderTabBar();
        renderSettingChips();
        renderResultChips();
        var chart = document.getElementById('factor-series-chart-container');
        if (chart && !state.lastSeries.length) {
            chart.innerHTML = message('从产品树选择产品，再选择因子并运行。');
        }
    }

    function init() {
        var header = document.getElementById('factor-series-header');
        var body = document.getElementById('factor-series-viewer-body');
        var runBtn = document.getElementById('factor-series-run-btn');
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
                setViewerOpen(body.style.display === 'none');
            });
            setViewerOpen(false);
        }
        if (runBtn) {
            runBtn.addEventListener('click', function(event) {
                if (event && event.stopPropagation) event.stopPropagation();
                runEvaluate();
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
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
