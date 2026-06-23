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
        selectionKind: '',
        currentPathLabel: '',
        currentPathDesc: '',
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

    function failProgress(errorText, value) {
        var ui = getProgressEls();
        setProgress(value == null ? 0 : value, errorText || '失败');
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

    function orderedMountedTabs() {
        var tabs = state.manifest && state.manifest.tab_lists ? (state.manifest.tab_lists[LOCAL] || []) : [];
        return window.BackendSettingsPanel.sortTabsByOrder(state.mountedTabs, tabs);
    }

    function settingKeysForTab(tabKey) {
        var out = [];
        var defs = defaults();
        Object.keys(defs).forEach(function(key) {
            if (defs[key] && defs[key].tab_key === tabKey) out.push(key);
        });
        return window.BackendSettingsPanel.sortSettingKeysByDisplayOrder(out, defs);
    }

    function effectiveValue(key) {
        if (Object.prototype.hasOwnProperty.call(state.values, key)) return state.values[key];
        var meta = settingMeta(key);
        return meta ? meta.value : '';
    }

    function settingVisibleForValues(setting, values) {
        return window.BackendSettingsPanel.settingVisibleForValues(setting, values);
    }

    function displayValue(setting, value) {
        if (setting && setting.key === 'product') {
            return productLabel() || '无';
        }
        if (setting && setting.key === 'factor') {
            var factor = selectedFactor();
            return factor ? factor.alias || factor.name || '' : '无';
        }
        return window.BackendSettingsPanel.displaySettingValue(setting, value);
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
        var template = setting && setting.chip_template ? setting.chip_template : ((setting && (setting.label || setting.key) || '') + ': {value}');
        return template.replace('{value}', displayValue(setting, value));
    }

    function makeChip(setting, value, explicitTabKey, muted) {
        var tabKey = explicitTabKey || setting.tab_key || setting.tab || '';
        var node = document.createElement('span');
        node.className = 'gt-backend-chip factor-series-settings-chip' + (muted ? ' is-muted' : '');
        node.innerHTML = renderChipHtml(chipText(setting, value));
        node.setAttribute('data-factor-series-tab-key', tabKey);
        if (tabKey && !muted) {
            node.title = '打开' + (tabMeta(tabKey) && tabMeta(tabKey).label || tabKey);
            node.style.cursor = 'pointer';
            node.addEventListener('click', function() {
                openTab(tabKey);
            });
        }
        return node;
    }

    function productLabel() {
        if (state.selectionKind === 'path') {
            var label = state.currentPathLabel || state.paths[0] || '';
            var desc = state.currentPathDesc || '';
            return desc && desc !== label ? label + ' · ' + desc : label;
        }
        if (!state.currentProduct) return '';
        var name = state.currentProduct.name || state.activeProduct || '';
        var desc = state.currentProduct.desc || '';
        return desc && desc !== name ? name + ' · ' + desc : name;
    }

    function displayProductLabel() {
        if (!state.currentProduct) return productLabel();
        var name = state.currentProduct.name || state.activeProduct || '';
        var desc = state.currentProduct.desc || '';
        return desc && desc !== name ? name + ' · ' + desc : name;
    }

    function runWindowValues() {
        return {
            start_date: effectiveValue('start_date') || '',
            end_date: effectiveValue('end_date') || '',
            start_time: effectiveValue('start_time') || '',
            end_time: effectiveValue('end_time') || '',
            time_precision: effectiveValue('time_precision') || 'exact',
            timezone: effectiveValue('timezone') || '',
        };
    }

    function runWindowPayload() {
        if (window.BacktestTimeWindowSettings) {
            return window.BacktestTimeWindowSettings.payloadFromValues(runWindowValues());
        }
        var precision = effectiveValue('time_precision') || 'exact';
        var tradingDayMode = precision === 'trading_day';
        return {
            start_date: effectiveValue('start_date') || '',
            end_date: effectiveValue('end_date') || '',
            start_time: tradingDayMode ? '' : (effectiveValue('start_time') || '00:00'),
            end_time: tradingDayMode ? '' : (effectiveValue('end_time') || '23:59'),
            time_precision: precision,
            timezone: tradingDayMode ? '' : (effectiveValue('timezone') || 'Asia/Shanghai'),
        };
    }

    function runWindowBoundsMs() {
        if (window.BacktestTimeWindowSettings) {
            return window.BacktestTimeWindowSettings.boundsMs(runWindowValues());
        }
        var payload = runWindowPayload();
        if (!payload.start_date || !payload.end_date) return { start: null, end: null };
        var startText = payload.start_date + (payload.time_precision === 'trading_day' ? 'T00:00:00' : ('T' + (payload.start_time || '00:00')));
        var endText = payload.end_date + (payload.time_precision === 'trading_day' ? 'T23:59:59.999' : ('T' + (payload.end_time || '23:59')));
        var start = new Date(startText).getTime();
        var end = new Date(endText).getTime();
        return {
            start: Number.isFinite(start) ? start : null,
            end: Number.isFinite(end) ? end : null,
        };
    }

    function filterRowsByRunWindow(rows) {
        var bounds = runWindowBoundsMs();
        if (bounds.start == null && bounds.end == null) return rows || [];
        return (rows || []).filter(function(row) {
            var ts = row && row.timestamp;
            return ts != null
                && (bounds.start == null || ts >= bounds.start)
                && (bounds.end == null || ts <= bounds.end);
        });
    }

    function filterPointsByRunWindow(points) {
        var bounds = runWindowBoundsMs();
        if (bounds.start == null && bounds.end == null) return points || [];
        return (points || []).filter(function(point) {
            var ts = point && point[0];
            return ts != null
                && (bounds.start == null || ts >= bounds.start)
                && (bounds.end == null || ts <= bounds.end);
        });
    }

    function contractOverlapsRunWindow(contract) {
        var bounds = runWindowBoundsMs();
        var start = contract && (contract.start_ts || pointTime(contract.start));
        var end = contract && (contract.end_ts || pointTime(contract.end));
        if (bounds.start == null && bounds.end == null) return true;
        if (start == null || end == null) return true;
        return (bounds.start == null || end >= bounds.start) && (bounds.end == null || start <= bounds.end);
    }

    function showChartLoading(text) {
        var chart = document.getElementById('factor-series-chart-container');
        if (chart) chart.innerHTML = message(text || '正在加载...');
    }

    function mountedSettingKeys() {
        var keys = {};
        orderedMountedTabs().forEach(function(tabKey) {
            settingKeysForTab(tabKey).forEach(function(key) { keys[key] = true; });
        });
        return keys;
    }

    function applyPageTimeDefaults(options) {
        if (!window.SingleFactorGlobalSettings || typeof window.SingleFactorGlobalSettings.getDefaultValues !== 'function') return false;
        options = options || {};
        var timeKeys = ['start_date', 'end_date', 'start_time', 'end_time', 'timezone', 'time_precision'];
        var values = window.SingleFactorGlobalSettings.getDefaultValues(timeKeys);
        if (!values) return false;
        if (options.blockOnAnyTimeValue && timeKeys.some(function(key) {
            return Object.prototype.hasOwnProperty.call(state.values, key) && state.values[key] !== '';
        })) {
            return false;
        }
        var changed = false;
        timeKeys.forEach(function(key) {
            if (!Object.prototype.hasOwnProperty.call(defaults(), key)) return;
            var value = values[key];
            if (value === undefined || value === null || value === '') return;
            if (state.values[key] === value) return;
            state.values[key] = value;
            changed = true;
        });
        return changed;
    }

    function effectiveSettingsForRun() {
        var out = {};
        Object.keys(defaults()).forEach(function(key) {
            out[key] = effectiveValue(key);
        });
        Object.assign(out, runWindowPayload());
        return out;
    }

    function renderSettingChips() {
        var row = document.getElementById('factor-series-settings-chip-row');
        if (!row || !state.manifest) return;
        row.innerHTML = '';
        orderedMountedTabs().forEach(function(tabKey) {
            var manifest = state.tabCache[tabKey];
            if (!manifest) {
                loadTab(tabKey).then(renderSettingChips).catch(function() {});
                return;
            }
            (manifest.settings || []).forEach(function(setting) {
                var value = effectiveValue(setting.key);
                if (setting.key === 'product' && !state.paths.length) return;
                if (setting.key === 'factor' && !selectedFactor()) return;
                row.appendChild(makeChip(setting, value, tabKey));
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
            if (key === 'product' && !state.paths.length) return;
            if (key === 'factor' && !selectedFactor()) return;
            row.appendChild(makeChip(setting, effectiveValue(key), setting.tab_key));
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

    function loadTab(tabKey) {
        if (state.tabCache[tabKey]) return Promise.resolve(state.tabCache[tabKey]);
        return requestJSON(tabURL(tabKey)).then(function(manifest) {
            state.tabCache[tabKey] = manifest;
            return manifest;
        });
    }

    async function loadFactors() {
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
            button.setAttribute('data-factor-series-tab-key', tab.key);
            button.className = state.activeTab === tab.key ? 'active' : '';
            button.addEventListener('click', function() { openTab(tab.key); });
            bar.appendChild(button);
        });
        var manage = document.createElement('button');
        manage.type = 'button';
        manage.textContent = '+ 设置';
        manage.setAttribute('data-factor-series-tab-key', '__manage__');
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
        var values = {};
        Object.keys(defaults()).forEach(function(key) { values[key] = effectiveValue(key); });
        (manifest.settings || []).forEach(function(setting) {
            if (!settingVisibleForValues(setting, values)) return;
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
        var control = setting.control_template === 'select' ? document.createElement('select') : document.createElement('input');
        if (control.tagName !== 'SELECT') {
            control.type = setting.control_template === 'date' || setting.control_template === 'time' || setting.control_template === 'number'
                ? setting.control_template : 'text';
            if (setting.step != null) control.step = String(setting.step);
            if (setting.minimum != null) control.min = String(setting.minimum);
            if (setting.maximum != null) control.max = String(setting.maximum);
            control.value = effectiveValue(setting.key) || '';
        }
        if (setting.key === 'factor') {
            if (!state.factors.length) {
                control.insertAdjacentHTML(
                    'beforeend',
                    optionHtml('', '请先提交参数设置或加载模板因子', true)
                );
                control.disabled = true;
                return control;
            }
            if (!effectiveValue(setting.key)) {
                state.values[setting.key] = state.factors[0].alias || state.factors[0].name || '';
            }
            state.factors.forEach(function(factor) {
                var value = factor.alias || factor.name || '';
                var label = value + (factor.freq ? ' · ' + factor.freq : '');
                control.insertAdjacentHTML('beforeend', optionHtml(value, label, effectiveValue(setting.key)));
            });
        } else if (control.tagName === 'SELECT') {
            (setting.options || []).forEach(function(option) {
                control.insertAdjacentHTML('beforeend', optionHtml(option.value, option.label, effectiveValue(setting.key)));
            });
        }
        control.addEventListener('change', function() {
            writeValue(setting.key, control.value);
            if (setting.key === 'time_precision') refreshActiveTab();
            if (setting.key === 'data_source') writeValue('frequency', '');
            if (setting.key === 'frequency') writeValue('data_source', '');
            if (state.currentProduct && (
                setting.key === 'data_source' || setting.key === 'frequency' || setting.key === 'price_type'
                || setting.key === 'start_date' || setting.key === 'end_date' || setting.key === 'start_time'
                || setting.key === 'end_time' || setting.key === 'timezone' || setting.key === 'time_precision'
            )) {
                activateSeriesProduct(state.activeProduct);
            }
        });
        return control;
    }

    function renderChooser() {
        var host = document.getElementById('factor-series-settings-host');
        if (!host || !state.manifest) return;
        var tabs = state.manifest.tab_lists && state.manifest.tab_lists[LOCAL] || [];
        if (!window.BackendSettingsPanel || typeof window.BackendSettingsPanel.renderChooser !== 'function') return;
        window.BackendSettingsPanel.renderChooser({
            host: host,
            tabs: tabs,
            mountedTabs: state.mountedTabs,
            introText: '选择要挂载到此栏的设置。未挂载项继续使用下列默认值。',
            defaultsForTab: function(tab) {
                return settingKeysForTab(tab.key).map(function(key) {
                    var setting = Object.assign({ key: key }, defaults()[key] || {});
                    if (!setting.chip_template) return null;
                    return { setting: setting, tabKey: tab.key };
                }).filter(Boolean);
            },
            renderChip: function(item) {
                return makeChip(item.setting, item.setting.value, item.tabKey, true);
            },
            onToggle: function(tab, enabled) {
                window.BackendSettingsPanel.toggleMountedTab({
                    mountedTabs: state.mountedTabs,
                    tabKey: tab.key,
                    enabled: enabled,
                    clearTabValues: function(tabKey) {
                        settingKeysForTab(tabKey).forEach(function(key) { delete state.values[key]; });
                    },
                    afterChange: function() {
                        renderTabBar();
                        renderSettingChips();
                        renderResultChips();
                    },
                });
            },
        });
    }

    function openTab(tabKey) {
        var host = document.getElementById('factor-series-settings-host');
        if (!host) return;
        var toggleResult = window.BackendSettingsPanel && typeof window.BackendSettingsPanel.toggleContent === 'function'
            ? window.BackendSettingsPanel.toggleContent({
                key: tabKey,
                host: host,
                getActiveKey: function() { return state.activeTab; },
                setActiveKey: function(value) { state.activeTab = value; },
                buttonSelector: '#factor-series-settings-tab-bar [data-factor-series-tab-key], #factor-series-settings-chip-row [data-factor-series-tab-key]',
                buttonKeyAttribute: 'data-factor-series-tab-key',
                onClose: function() {
                    renderTabBar();
                    renderSettingChips();
                },
            })
            : { opened: true };
        if (!window.BackendSettingsPanel || typeof window.BackendSettingsPanel.toggleContent !== 'function') {
            if (state.activeTab === tabKey && host.style.display !== 'none') {
                state.activeTab = null;
                host.style.display = 'none';
                renderTabBar();
                return;
            }
            state.activeTab = tabKey;
            host.style.display = '';
        }
        if (!toggleResult.opened) {
            renderTabBar();
            renderSettingChips();
            return;
        }
        renderTabBar();
        if (tabKey === '__manage__') {
            renderChooser();
            return;
        }
        host.innerHTML = '<span style="color:#64748b;font-size:12px;">正在加载...</span>';
        loadTab(tabKey).then(function(manifest) {
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
            summary.innerHTML = '<span style="color:#94a3b8;">未选择产品路径</span>';
            return;
        }
        var label = state.selectionKind === 'path' ? productLabel() : productLabel();
        summary.innerHTML = '<span class="gt-backend-chip factor-series-path-chip">'
            + renderChipHtml(state.selectionKind === 'path' ? '产品路径' : '产品', label || state.paths[0])
            + '</span>';
    }

    function currentProductPathSelection() {
        if (!state.paths.length) return null;
        var id = 'factor-series-selection';
        var label = productLabel() || state.paths[0] || '产品路径';
        return {
            product_path_selection_id: id,
            selection_id: id,
            label: label,
            source_type: 'manual_selection',
            paths: state.paths.slice(),
            selected_paths: state.paths.slice(),
        };
    }

    function extractProductName(node) {
        if (!node || !node.key) return null;
        var data = node.data || {};
        if (data.product_name) return data.product_name;
        if (node.folder || node.hasChildren && node.hasChildren()) return null;
        if (data.has_data === false) return null;
        var parts = String(node.key).split('/');
        var last = parts[parts.length - 1];
        if (last === '_products' || /^[0-9]+$/.test(last)) return null;
        return last;
    }

    function nodeLabel(node) {
        if (!node) return '';
        var title = String(node.title || '').trim();
        if (title) return title;
        var parts = String(node.key || '').split('/');
        return parts[parts.length - 1] || '';
    }

    function nodeDesc(node) {
        var data = node && node.data || {};
        return String(data.desc || data.description || '').trim();
    }

    function nodeHasProducts(node) {
        if (!node) return false;
        var data = node.data || {};
        if (data.has_data === true || data.product_name) return true;
        if (Array.isArray(data.products) && data.products.length) return true;
        if (Array.isArray(data._products) && data._products.length) return true;
        var desc = nodeDesc(node);
        return /[0-9]+\s*个产品/.test(desc) || !!node.folder;
    }

    function productMetaForName(name, item) {
        var data = Object.assign({}, state.allProductsMap[name] || {});
        if (item && item.desc && !data.desc) data.desc = item.desc;
        if (!data.name) data.name = name;
        if (!data.code) data.code = name;
        return data;
    }

    function setActiveProduct(name, item) {
        state.activeProduct = String(name || '');
        if (state.activeProduct) {
            state.currentProduct = productMetaForName(state.activeProduct, item);
            state.selectionKind = state.selectionKind || 'product';
            var title = document.getElementById('factor-series-chart-title');
            if (title) title.textContent = '因子序列';
            var selectedSummary = document.getElementById('factor-series-product-selected-summary');
            if (selectedSummary) selectedSummary.textContent = '';
        }
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
                if (productName && nodeData.has_data !== false) {
                    selectProduct(productName, nodeData, node.key);
                    return;
                }
                if (nodeHasProducts(node)) selectProductPath(node);
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
        state.selectionKind = 'product';
        state.currentPathLabel = '';
        state.currentPathDesc = '';
        state.currentProduct = data;
        state.paths = [String(path || name)];
        setActiveProduct(name, data);
        writeValue('product', String(name));
        loadTermTable(data.name);
        loadPriceDataForCurrentProduct().then(function(priceData) {
            drawResultChart(priceData, selectedSeriesItem(), selectedFactor() || {});
        }).catch(showResultError);
    }

    function selectProductPath(node) {
        if (!node || !node.key) return;
        state.selectionKind = 'path';
        state.currentPathLabel = nodeLabel(node);
        state.currentPathDesc = nodeDesc(node);
        state.currentProduct = null;
        state.currentContracts = [];
        state.paths = [String(node.key)];
        state.activeProduct = '';
        writeValue('product', String(node.key));
        var label = productLabel();
        var title = document.getElementById('factor-series-chart-title');
        if (title) title.textContent = '因子序列';
        var selectedSummary = document.getElementById('factor-series-product-selected-summary');
        if (selectedSummary) selectedSummary.textContent = '';
        var termContainer = document.getElementById('factor-series-term-table-container');
        if (termContainer) termContainer.style.display = 'none';
        var chart = document.getElementById('factor-series-chart-container');
        if (chart) chart.innerHTML = message('已选择产品路径，请点击计算因子。');
    }

    function syncProductFromActiveTree() {
        if (state.paths.length) return true;
        var tree = state.tree;
        if (!tree && window.jQuery && window.jQuery.ui && window.jQuery.ui.fancytree) {
            try {
                tree = window.jQuery.ui.fancytree.getTree('#factor-series-tree-container');
            } catch (err) {
                tree = null;
            }
        }
        var node = tree && tree.getActiveNode ? tree.getActiveNode() : null;
        if (!node) return false;
        var nodeData = node.data || {};
        var productName = extractProductName(node);
        if (productName && nodeData.has_data !== false) {
            selectProduct(productName, nodeData, node.key);
            return true;
        }
        if (nodeHasProducts(node)) {
            selectProductPath(node);
            return true;
        }
        return false;
    }

    function showMissingProductState(chart, status) {
        openTab('product');
        var text = '请先从产品树选择产品或产品路径';
        if (chart) chart.innerHTML = message(text + '。', true);
        if (status) status.textContent = text;
        showProgress();
        setProgress(8, text);
        setTimeout(function() {
            failProgress(text, 8);
        }, 250);
    }

    function normalizeProductForContractApi(name) {
        return String(name == null ? '' : name);
    }

    function renderTermTableRows(container, tbody, contracts) {
        if (!container || !tbody) return;
        tbody.innerHTML = '';
        var visibleContracts = (contracts || []).filter(contractOverlapsRunWindow);
        if (!visibleContracts.length) {
            container.style.display = 'none';
            return;
        }
        visibleContracts.forEach(function(c) {
            var tr = document.createElement('tr');
            var contractCell = c.has_data
                ? '<a href="/products?contract_uid=' + encodeURIComponent(c.uid) + '" title="查看合约信息">' + escapeHtml(c.contract) + '</a>'
                : '<span class="contract-name-muted" title="暂无价格数据，不能跳转">' + escapeHtml(c.contract || '') + '</span>';
            tr.innerHTML = '<td>' + contractCell + '</td>'
                + '<td>' + escapeHtml(c.start || c.start_ts || '') + '</td>'
                + '<td>' + escapeHtml(c.end || c.end_ts || '') + '</td>';
            tr.addEventListener('click', function(event) {
                if (event.target && event.target.tagName === 'A') event.preventDefault();
                highlightContractRange(c);
            });
            tbody.appendChild(tr);
        });
        container.style.display = 'block';
    }

    function highlightContractRange(contract) {
        if (!state.chart || !state.chart.xAxis || !state.chart.xAxis[0] || !contract) return;
        var axis = state.chart.xAxis[0];
        try { axis.removePlotBand('factor-series-selected-contract'); } catch (err) {}
        var from = contract.start_ts || pointTime(contract.start);
        var to = contract.end_ts || pointTime(contract.end);
        if (from == null || to == null) return;
        var min = axis.min;
        var max = axis.max;
        var fullyVisible = min != null && max != null && from >= min && to <= max;
        if (!fullyVisible && typeof axis.setExtremes === 'function') {
            axis.setExtremes(from, to, true, false, { trigger: 'factor-series-contract-range' });
        }
        axis.addPlotBand({
            id: 'factor-series-selected-contract',
            from: from,
            to: to,
            color: 'rgba(37,99,235,0.08)',
            label: {
                text: (contract.contract || '') + ' · ' + (contract.start || '') + ' → ' + (contract.end || ''),
                style: { color: '#1d4ed8', fontSize: '11px', fontWeight: '600' },
            },
            zIndex: 3,
        });
    }

    async function loadTermTable(productName) {
        var container = document.getElementById('factor-series-term-table-container');
        var tbody = document.querySelector('#factor-series-term-table tbody');
        if (!container || !tbody) return;
        container.style.display = 'none';
        tbody.innerHTML = '';
        if (!productName) return;
        try {
            var windowPayload = runWindowPayload();
            var query = new URLSearchParams({ product: normalizeProductForContractApi(productName) });
            if (windowPayload.start_date) query.set('start_date', windowPayload.start_date);
            if (windowPayload.end_date) query.set('end_date', windowPayload.end_date);
            var data = await requestJSON('/api/get_contracts?' + query.toString());
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
        if (!state.currentProduct && state.activeProduct) {
            setActiveProduct(state.activeProduct, selectedSeriesItem());
        }
        if (!state.currentProduct) return null;
        var product = state.currentProduct;
        var reqBody = {
            product_name: product.name || product.code,
            adjusted: priceTypeAdjusted(),
            series_variant: product.series_variant || 'primary_raw',
            freq: effectiveValue('frequency') || '',
            data_source: effectiveValue('data_source') || null,
        };
        Object.assign(reqBody, runWindowPayload());
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

    function seriesItemLabel(item) {
        if (!item) return '';
        var desc = item.desc && item.desc !== item.product ? ' · ' + item.desc : '';
        return String(item.product || '') + desc;
    }

    function filteredSeriesItems(query) {
        var q = String(query || '').trim().toLowerCase();
        if (!q) return state.lastSeries.slice();
        return state.lastSeries.filter(function(item) {
            return seriesItemLabel(item).toLowerCase().indexOf(q) >= 0;
        });
    }

    function updateSeriesSelectOptions(select, query) {
        if (!select) return false;
        var items = filteredSeriesItems(query);
        select.innerHTML = items.map(function(item) {
            return '<option value="' + escapeHtml(item.product) + '"' + (item.product === state.activeProduct ? ' selected' : '') + '>'
                + escapeHtml(seriesItemLabel(item))
                + '</option>';
        }).join('');
        if (items.length && !items.some(function(item) { return item.product === state.activeProduct; })) {
            state.activeProduct = items[0].product;
            select.value = state.activeProduct;
            return true;
        }
        return false;
    }

    function activateSeriesProduct(productName) {
        var item = state.lastSeries.find(function(series) { return series.product === productName; }) || null;
        setActiveProduct(productName, item);
        showChartLoading('正在加载 ' + displayProductLabel() + '...');
        loadTermTable(productName);
        return loadPriceDataForCurrentProduct().then(function(priceData) {
            drawResultChart(priceData, selectedSeriesItem(), selectedFactor() || {});
        }).catch(showResultError);
    }

    function renderProductChooser() {
        var host = document.getElementById('factor-series-product-row');
        if (!host) return;
        if (!state.lastSeries.length) {
            host.innerHTML = '';
            return;
        }
        host.innerHTML = '<label class="factor-series-field factor-series-series-picker">'
            + '<span>显示序列</span>'
            + '<input id="factor-series-product-search" type="search" placeholder="按 alias / desc 检索">'
            + '<select id="factor-series-product"></select>'
            + '</label>';
        var select = document.getElementById('factor-series-product');
        var search = document.getElementById('factor-series-product-search');
        updateSeriesSelectOptions(select, '');
        if (select) {
            select.addEventListener('change', function() {
                activateSeriesProduct(select.value);
            });
        }
        if (search) {
            search.addEventListener('input', function() {
                if (updateSeriesSelectOptions(select, search.value) && select.value) {
                    activateSeriesProduct(select.value);
                }
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

    function chartBoostThreshold(points, isIntraday) {
        return isIntraday && Array.isArray(points) && points.length > 5000 ? 500 : Number.MAX_SAFE_INTEGER;
    }

    function drawResultChart(priceData, item, factor) {
        var container = document.getElementById('factor-series-chart-container');
        if (!container) return;
        container.innerHTML = '';
        if (!window.Highcharts) {
            container.innerHTML = message('Highcharts 未加载，无法显示图表。', true);
            return;
        }
        var rows = priceData && Array.isArray(priceData.data) ? filterRowsByRunWindow(priceData.data).slice().sort(function(a, b) {
            return (a.timestamp || 0) - (b.timestamp || 0);
        }) : [];
        var factorData = filterPointsByRunWindow(factorPoints(item));
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

        var freqStr = priceData && priceData.freq ? String(priceData.freq) : '';
        var isIntraday = freqStr.indexOf('MIN') === 0 || freqStr.indexOf('HOUR') === 0 || freqStr.indexOf('SEC') === 0;
        var plotBands = [];
        if (priceData && priceData.supports_term_structure && Array.isArray(priceData.contracts) && priceData.contracts.length) {
            plotBands = priceData.contracts.map(function(contract, index) {
                return {
                    id: 'contract-' + index,
                    from: contract.start_ts,
                    to: contract.end_ts,
                    color: 'rgba(100,149,237,0.04)',
                };
            });
        }

        var yAxis = [{
            labels: { align: 'right', x: -3 },
            title: { text: '' },
            height: hasOi ? '44%' : '50%',
            lineWidth: 2,
            resize: { enabled: true },
        }, {
            labels: { align: 'right', x: -3 },
            title: { text: '' },
            top: hasOi ? '49%' : '55%',
            height: hasOi ? '20%' : '22%',
            offset: 0,
            lineWidth: 2,
        }, {
            labels: { align: 'right', x: -3 },
            title: { text: '' },
            top: hasOi ? '72%' : '80%',
            height: hasOi ? '10%' : '15%',
            offset: 0,
            lineWidth: 2,
        }];
        var series = [];
        if (ohlc.length) {
            series.push({
                type: 'candlestick',
                name: priceData.product || '价格',
                data: ohlc,
                yAxis: 0,
                legendIndex: 10,
                boostThreshold: chartBoostThreshold(ohlc, isIntraday),
                tooltip: {
                    pointFormat:
                        '<span style="font-weight:bold">开盘</span> {point.open:.2f}<br/>' +
                        '<span style="font-weight:bold">最高</span> {point.high:.2f}<br/>' +
                        '<span style="font-weight:bold">最低</span> {point.low:.2f}<br/>' +
                        '<span style="font-weight:bold">收盘</span> {point.close:.2f}'
                },
            });
        }
        if (factorData.length) {
            series.push({
                type: 'line',
                name: factor.alias || factor.name || '因子值',
                data: factorData,
                yAxis: 1,
                color: '#2563eb',
                legendIndex: 20,
                dataGrouping: { enabled: false },
                boostThreshold: chartBoostThreshold(factorData, isIntraday),
                tooltip: { valueDecimals: 6 },
            });
        }
        if (volume.length) {
            series.push({
                type: 'column',
                name: '成交量',
                data: volume,
                yAxis: 2,
                color: '#90CAF9',
                legendIndex: 30,
                boostThreshold: chartBoostThreshold(volume, isIntraday),
                tooltip: { valueDecimals: 0 },
            });
        }
        if (hasOi) {
            yAxis.push({
                labels: { align: 'right', x: -3 },
                title: { text: '' },
                top: '85%',
                height: '15%',
                offset: 0,
                lineWidth: 2,
            });
            series.push({
                type: 'line',
                name: '持仓量',
                data: oi,
                yAxis: 3,
                color: '#E91E63',
                legendIndex: 40,
                boostThreshold: chartBoostThreshold(oi, isIntraday),
                tooltip: { valueDecimals: 0 },
            });
        }
        var title = displayProductLabel() || (priceData && priceData.product) || '因子评估';
        var xAxisOptions = {
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
                    return isIntraday ? (hh + ':' + mm + '<br/>' + M + '-' + dd) : (M + '-' + dd);
                },
            },
            ordinal: true,
            plotBands: plotBands,
        };
        state.chart = window.Highcharts.stockChart(container, {
            chart: { animation: false, height: Math.max(520, Math.floor(container.getBoundingClientRect().height || 520)) },
            title: { text: title, style: { fontSize: '15px' } },
            subtitle: { text: (priceData ? ((priceData.adjusted ? '复权' : '原始') + ' · ' + priceData.freq + ' · ' + priceData.count + ' 条') : ''), style: { fontSize: '11px', color: '#888' } },
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
            navigator: { enabled: true },
            scrollbar: { enabled: false },
            legend: { enabled: true },
            xAxis: xAxisOptions,
            yAxis: yAxis,
            tooltip: {
                shared: true,
                useHTML: true,
                formatter: function() {
                    var d = new Date(this.x);
                    var dateStr = isIntraday
                        ? d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0') + ' '
                            + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0') + ':' + String(d.getSeconds()).padStart(2, '0')
                        : d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
                    var s = '<b>' + dateStr + '</b>';
                    (this.points || []).forEach(function(p) {
                        if (p.series.type === 'candlestick') {
                            s += '<br/><span style="font-weight:bold">开盘</span> ' + p.point.open.toFixed(2)
                                + '<br/><span style="font-weight:bold">最高</span> ' + p.point.high.toFixed(2)
                                + '<br/><span style="font-weight:bold">最低</span> ' + p.point.low.toFixed(2)
                                + '<br/><span style="font-weight:bold">收盘</span> ' + p.point.close.toFixed(2);
                        } else {
                            var decimals = p.series.tooltipOptions && typeof p.series.tooltipOptions.valueDecimals === 'number'
                                ? p.series.tooltipOptions.valueDecimals : 2;
                            var val = typeof p.y === 'number' ? p.y.toFixed(decimals) : p.y;
                            s += '<br/>' + p.series.name + ': ' + val;
                        }
                    });
                    return s;
                },
            },
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
        showProgress();
        setProgress(5, '检查配置');
        if (!state.paths.length) syncProductFromActiveTree();
        if (!state.paths.length) {
            showMissingProductState(chart, status);
            return;
        }
        if (!factor) {
            var factorText = '请先提交参数设置或加载模板因子';
            openTab('factor');
            chart.innerHTML = message(factorText + '。', true);
            if (status) status.textContent = factorText;
            setProgress(8, factorText);
            failProgress(factorText, 8);
            return;
        }
        if (status) status.textContent = '计算因子...';
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
                    settings: effectiveSettingsForRun(),
                }),
            });
            state.lastSeries = Array.isArray(data.series) ? data.series : [];
            if (state.lastSeries.length) {
                setActiveProduct(state.lastSeries[0].product, state.lastSeries[0]);
            }
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
        applyPageTimeDefaults({ blockOnAnyTimeValue: false });
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
        document.addEventListener('timeRangeDefaultLoaded', function() {
            if (applyPageTimeDefaults({ blockOnAnyTimeValue: true })) {
                renderSettingChips();
                renderResultChips();
                if (state.activeTab === 'time') refreshActiveTab();
            }
        });
        document.addEventListener('pageTimeRangeChanged', function() {
            if (applyPageTimeDefaults({ blockOnAnyTimeValue: false })) {
                renderSettingChips();
                renderResultChips();
                if (state.activeTab === 'time') refreshActiveTab();
            }
        });
    }

    window.FactorSeriesViewer = {
        setSelections: function(data) {
            if (data && data.product_path_selection) {
                var selection = data.product_path_selection;
                state.paths = (selection.paths || selection.selected_paths || []).slice();
                state.currentPathLabel = selection.label || selection.product_group || '';
                state.selectionKind = state.paths.length === 1 && String(state.paths[0]).indexOf('/_products/') >= 0 ? 'product' : 'path';
                renderPathSummary();
            }
        },
        getSelections: function() {
            return {
                product_path_selection: currentProductPathSelection(),
                paths: state.paths.slice(),
                factor: state.values.factor || '',
                settings: effectiveSettingsForRun(),
            };
        },
        render: function() {
            if (bodyOpen()) return render();
        },
    };

    loadOverlayProducts();
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
