(function() {
    var APP = 'single_factor_page';
    var LOCAL = 'local-settings';
    var state = {
        manifest: null,
        mountedTabs: [],
        activeTab: null,
        values: Object.create(null),
        tabCache: Object.create(null),
        containers: {},
        timeSyncTimer: null,
        productPathSelections: [],
        productPathSelectionsLoaded: false,
    };

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function requestJSON(url) {
        return fetch(url, { headers: { Accept: 'application/json' } }).then(function(response) {
            return response.json().catch(function() { return {}; }).then(function(payload) {
                if (!response.ok || payload.success === false) {
                    throw new Error(payload.error || ('HTTP ' + response.status));
                }
                return payload;
            });
        });
    }

    function tabs() {
        return state.manifest && state.manifest.tab_lists
            ? (state.manifest.tab_lists[LOCAL] || [])
            : [];
    }

    function tabMeta(tabKey) {
        var list = tabs();
        for (var i = 0; i < list.length; i++) {
            if (list[i].key === tabKey) return list[i];
        }
        return null;
    }

    function orderedMountedTabs() {
        return window.BackendSettingsPanel.sortTabsByOrder(state.mountedTabs, tabs());
    }

    function defaults() {
        return state.manifest && state.manifest.defaults ? state.manifest.defaults : {};
    }

    function sharedGlobalDefaultKeys() {
        return state.manifest && Array.isArray(state.manifest.shared_global_default_keys)
            ? state.manifest.shared_global_default_keys.slice()
            : [];
    }

    function sharedGlobalDefaultKeySet() {
        var out = Object.create(null);
        sharedGlobalDefaultKeys().forEach(function(key) { out[key] = true; });
        return out;
    }

    function effectiveValue(key) {
        if (Object.prototype.hasOwnProperty.call(state.values, key)) return state.values[key];
        var def = defaults()[key];
        return def ? def.value : '';
    }

    function settingKeysForTab(tabKey) {
        var out = [];
        var defs = defaults();
        Object.keys(defs).forEach(function(key) {
            if (defs[key] && defs[key].tab_key === tabKey) out.push(key);
        });
        return window.BackendSettingsPanel.sortSettingKeysByDisplayOrder(out, defs);
    }

    function tabHasSharedGlobalDefaults(tabKey) {
        var allowed = sharedGlobalDefaultKeySet();
        return settingKeysForTab(tabKey).some(function(key) { return !!allowed[key]; });
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

    function makeChip(tabKey, label, value) {
        var chip = document.createElement('span');
        chip.className = 'gt-backend-chip';
        chip.innerHTML = renderChipHtml(label, value);
        chip.title = '打开' + ((tabMeta(tabKey) && tabMeta(tabKey).label) || tabKey);
        chip.style.cursor = 'pointer';
        chip.setAttribute('data-page-settings-tab-btn', tabKey);
        chip.addEventListener('click', function() { openTab(tabKey); });
        return chip;
    }

    function hideLegacyRows() {
        var rows = [
            document.getElementById('global-tpl-summary-row'),
            document.getElementById('param-summary-text') && document.getElementById('param-summary-text').closest('.setting-summary-row'),
            document.getElementById('time-summary-text') && document.getElementById('time-summary-text').closest('.setting-summary-row'),
        ];
        rows.forEach(function(row) {
            if (row) row.style.display = 'none';
        });
    }

    function movePanelContent(drawerId, tabKey) {
        var drawer = document.getElementById(drawerId);
        var panel = drawer && drawer.querySelector('.settings-drawer-panel');
        if (!panel || !state.containers[tabKey]) return;
        if (tabKey === 'parameters') {
            var factorChipListHost = document.createElement('div');
            factorChipListHost.id = 'single-factor-page-factor-candidates';
            factorChipListHost.className = 'single-factor-page-factor-candidates';
            state.containers[tabKey].appendChild(factorChipListHost);
            renderFactorCandidateChipList(factorChipListHost);

            var parameterModule = panel.querySelector('#parameter_module');
            if (parameterModule) {
                parameterModule.classList.add('single-factor-page-embedded-params');
                Array.from(parameterModule.children).forEach(function(child) {
                    if (child.classList && child.classList.contains('section-title')) return;
                    if (child.classList && child.classList.contains('param-hint')) return;
                    state.containers[tabKey].appendChild(child);
                });
            }
            drawer.style.display = 'none';
            drawer.classList.remove('open');
            return;
        }
        if (tabKey === 'time') {
            drawer.style.display = 'none';
            drawer.classList.remove('open');
            return;
        }
        Array.from(panel.children).forEach(function(child) {
            if (child.classList && child.classList.contains('drawer-close-btn')) {
                child.style.display = 'none';
                return;
            }
            state.containers[tabKey].appendChild(child);
        });
        drawer.style.display = 'none';
        drawer.classList.remove('open');
    }

    function templateSummaryValue() {
        return window._currentSingleFactorTemplateName || '无';
    }

    function productPathSelectionId(selection) {
        if (!selection) return '';
        if (window.ProductPathSelectionUtils && typeof window.ProductPathSelectionUtils.selectionId === 'function') {
            return window.ProductPathSelectionUtils.selectionId(selection);
        }
        return String(selection.product_path_selection_id || selection.selection_id || selection.id || '');
    }

    function productPathSelectionLabel(selection) {
        if (!selection) return '无';
        if (window.ProductPathSelectionUtils && typeof window.ProductPathSelectionUtils.selectionDisplayLabel === 'function') {
            return window.ProductPathSelectionUtils.selectionDisplayLabel(selection);
        }
        var label = selection.product_group || selection.label || selection.name || productPathSelectionId(selection);
        if (!label) return '无';
        if (selection.product_group_template_id || selection.product_group || selection.product_group_name) return label + ' · 产品组';
        if (selection.path_id || selection.paths || selection.selected_paths) return label + ' · 路径组';
        return label;
    }

    function productGroupToSelection(group) {
        if (window.ProductPathSelectionUtils && typeof window.ProductPathSelectionUtils.productGroupToSelection === 'function') {
            return window.ProductPathSelectionUtils.productGroupToSelection(group);
        }
        group = group || {};
        return {
            id: String(group.id || group.name || ''),
            product_path_selection_id: String(group.id || group.name || ''),
            product_group_template_id: String(group.id || ''),
            path_id: String(group.id || ''),
            product_group: group.name || '',
            label: group.name || '',
            paths: (group.paths || []).slice(),
            selected_paths: (group.paths || []).slice(),
            products: [],
            product_groups: [],
        };
    }

    function loadProductPathSelections(force) {
        if (state.productPathSelectionsLoaded && !force) return Promise.resolve(state.productPathSelections);
        return requestJSON('/api/product-groups').then(function(payload) {
            setProductPathCandidates((payload.groups || []).map(productGroupToSelection), { silent: false });
            state.productPathSelectionsLoaded = true;
            return state.productPathSelections;
        });
    }

    function productPathCandidates() {
        var value = state.values.product_path_candidates;
        return Array.isArray(value) ? value : [];
    }

    function setProductPathCandidates(selections, options) {
        options = options || {};
        var utils = window.ProductPathSelectionUtils || {};
        var list = Array.isArray(selections) ? selections.slice() : [];
        if (utils.dedupe) list = utils.dedupe(list);
        state.productPathSelections = list;
        state.values.product_path_candidates = list;
        if (!options.silent) {
            renderChips();
            broadcastGlobalSettingsChanged();
        }
    }

    function displayValue(setting, value) {
        return window.BackendSettingsPanel.displaySettingValue(setting, value);
    }

    function settingChipParts(setting) {
        if (!setting || !setting.chip_template) return null;
        var value = displayValue(setting, effectiveValue(setting.key));
        var text = String(setting.chip_template).replace('{value}', value);
        var match = text.match(/^([^:：]{1,16})[:：]\s*(.*)$/);
        if (match && match[2]) return { label: match[1], value: match[2] };
        return { label: setting.label || setting.key, value: value };
    }

    function registeredTabChipParts(tabKey) {
        var values = {};
        Object.keys(defaults()).forEach(function(key) { values[key] = effectiveValue(key); });
        return settingKeysForTab(tabKey).map(function(key) {
            var setting = Object.assign({ key: key }, defaults()[key] || {});
            if (!settingVisibleForValues(setting, values)) return null;
            return settingChipParts(setting);
        }).filter(Boolean);
    }

    function chipPartsForTab(tabKey) {
        if (tabKey === 'setting_template') return [{ label: '模板', value: templateSummaryValue() }];
        return registeredTabChipParts(tabKey);
    }

    function renderChips() {
        var row = document.getElementById('single-factor-page-settings-chips');
        if (!row) return;
        row.innerHTML = '';
        orderedMountedTabs().forEach(function(tabKey) {
            chipPartsForTab(tabKey).forEach(function(parts) {
                row.appendChild(makeChip(tabKey, parts.label, parts.value));
            });
        });
    }

    function renderTabs() {
        var bar = document.getElementById('single-factor-page-settings-tabs');
        if (!bar) return;
        bar.innerHTML = '';
        orderedMountedTabs().forEach(function(tabKey) {
            var meta = tabMeta(tabKey);
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.textContent = meta ? meta.label : tabKey;
            btn.className = state.activeTab === tabKey ? 'active' : '';
            btn.setAttribute('data-page-settings-tab-btn', tabKey);
            btn.addEventListener('click', function() {
                openTab(tabKey);
            });
            bar.appendChild(btn);
        });
        var manage = document.createElement('button');
        manage.type = 'button';
        manage.textContent = '+ 设置';
        manage.className = state.activeTab === '__manage__' ? 'active' : '';
        manage.setAttribute('data-page-settings-tab-btn', '__manage__');
        manage.addEventListener('click', function() {
            openTab('__manage__');
        });
        bar.appendChild(manage);
    }

    function ensurePanel(tabKey) {
        var host = document.getElementById('single-factor-page-settings-host');
        if (!host || !tabKey) return null;
        if (state.containers[tabKey]) return state.containers[tabKey];
        var panel = document.createElement('div');
        panel.className = 'single-factor-page-settings-panel';
        panel.setAttribute('data-page-settings-tab-panel', tabKey);
        panel.style.display = 'none';
        host.appendChild(panel);
        state.containers[tabKey] = panel;
        return panel;
    }

    function renderShell() {
        var root = document.getElementById('single-factor-page-settings');
        if (!root || root.dataset.rendered === '1') return;
        root.dataset.rendered = '1';
        root.className = 'backend-settings-shell single-factor-page-settings-shell';
        root.innerHTML = ''
            + '<div class="backend-settings-tab-bar" id="single-factor-page-settings-tabs"></div>'
            + '<div class="backend-settings-chip-row" id="single-factor-page-settings-chips"></div>'
            + '<div class="backend-settings-host" id="single-factor-page-settings-host"></div>';
        var host = document.getElementById('single-factor-page-settings-host');
        state.mountedTabs.forEach(ensurePanel);
        movePanelContent('global-tpl-drawer', 'setting_template');
        movePanelContent('param-drawer', 'parameters');
        movePanelContent('time-range-drawer', 'time');
        hideLegacyRows();
        renderTabs();
        renderChips();
    }

    function openTab(tabKey) {
        var host = document.getElementById('single-factor-page-settings-host');
        if (tabKey) ensurePanel(tabKey);
        var toggleResult = window.BackendSettingsPanel && typeof window.BackendSettingsPanel.toggleContent === 'function'
            ? window.BackendSettingsPanel.toggleContent({
                key: tabKey,
                host: host,
                getActiveKey: function() { return state.activeTab; },
                setActiveKey: function(value) { state.activeTab = value; },
                buttonSelector: '#single-factor-page-settings-tabs [data-page-settings-tab-btn], #single-factor-page-settings-chips [data-page-settings-tab-btn]',
                buttonKeyAttribute: 'data-page-settings-tab-btn',
                panelSelector: '[data-page-settings-tab-panel]',
                panelKeyAttribute: 'data-page-settings-tab-panel',
                onClose: function() {
                    renderTabs();
                    renderChips();
                },
            })
            : { opened: true };
        if (!window.BackendSettingsPanel || typeof window.BackendSettingsPanel.toggleContent !== 'function') {
            state.activeTab = tabKey || null;
            if (state.activeTab) ensurePanel(state.activeTab);
            Object.keys(state.containers).forEach(function(key) {
                state.containers[key].style.display = key === state.activeTab ? '' : 'none';
            });
            if (host) host.style.display = state.activeTab ? '' : 'none';
        }
        renderTabs();
        renderChips();
        if (!toggleResult.opened) return;
        if (tabKey === '__manage__') {
            renderChooser();
            return;
        }
        if (tabKey === 'setting_template') {
            if (typeof window._loadGlobalTemplateList === 'function') {
                window._loadGlobalTemplateList();
            } else {
                setTimeout(function() {
                    if (typeof window._loadGlobalTemplateList === 'function') window._loadGlobalTemplateList();
                }, 50);
            }
        }
        if (tabKey === 'time') {
            renderRegisteredTimeTab();
            return;
        }
        if (tabKey === 'product_path_selection') {
            renderProductPathSelectionTab();
            return;
        }
        if (tabKey === 'parameters') {
            renderParametersTab();
            return;
        }
        if (tabMeta(tabKey) && state.containers[tabKey] && state.containers[tabKey].childNodes.length === 0) {
            renderRegisteredSettingsTab(tabKey);
        }
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

    function optionHtml(value, label, selected) {
        return '<option value="' + escapeHtml(value) + '"' + (String(value) === String(selected) ? ' selected' : '') + '>'
            + escapeHtml(label)
            + '</option>';
    }

    function currentTimeValues() {
        if (window.BacktestTimeWindowSettings && typeof window.BacktestTimeWindowSettings.pageRuntimeTimeRangeValues === 'function') {
            var runtime = window.BacktestTimeWindowSettings.pageRuntimeTimeRangeValues();
            if (runtime) return runtime;
        }
        return {};
    }

    function syncTimeDefaultsFromPage() {
        var values = currentTimeValues();
        ['start_date', 'end_date', 'start_time', 'end_time', 'timezone', 'time_precision'].forEach(function(key) {
            if (values[key] !== undefined && values[key] !== null) state.values[key] = values[key];
        });
    }

    function settingVisibleForValues(setting, values) {
        return window.BackendSettingsPanel.settingVisibleForValues(setting, values);
    }

    function settingVisible(setting) {
        var values = {};
        Object.keys(defaults()).forEach(function(key) { values[key] = effectiveValue(key); });
        return settingVisibleForValues(setting, values);
    }

    function makeSettingControl(setting) {
        var control = setting.control_template === 'select' ? document.createElement('select') : document.createElement('input');
        if (control.tagName === 'SELECT') {
            (setting.options || []).forEach(function(option) {
                control.insertAdjacentHTML('beforeend', optionHtml(option.value, option.label, effectiveValue(setting.key)));
            });
        } else {
            control.type = setting.control_template === 'date' || setting.control_template === 'time' || setting.control_template === 'number'
                ? setting.control_template : 'text';
            if (setting.step != null) control.step = String(setting.step);
            if (setting.minimum != null) control.min = String(setting.minimum);
            if (setting.maximum != null) control.max = String(setting.maximum);
            control.value = effectiveValue(setting.key) || '';
        }
        control.addEventListener('change', function() {
            state.values[setting.key] = control.value;
            if (setting.key === 'time_precision') renderRegisteredTimeTab({ keepValues: true });
            if (['start_date', 'end_date', 'start_time', 'end_time', 'timezone', 'time_precision'].indexOf(setting.key) >= 0) {
                syncRegisteredTimeRange();
            }
            renderChips();
            broadcastGlobalSettingsChanged();
        });
        return control;
    }

    function broadcastGlobalSettingsChanged() {
        document.dispatchEvent(new CustomEvent('singleFactorGlobalSettingsChanged', {
            detail: {
                values: window.SingleFactorGlobalSettings
                    ? window.SingleFactorGlobalSettings.getDefaultValues(sharedGlobalDefaultKeys())
                    : {},
            },
        }));
    }

    function toggleMounted(tabKey, enabled) {
        if (!window.BackendSettingsPanel) {
            var index = state.mountedTabs.indexOf(tabKey);
            if (enabled && index < 0) state.mountedTabs.push(tabKey);
            if (!enabled && index >= 0) state.mountedTabs.splice(index, 1);
            settingKeysForTab(tabKey).forEach(function(key) { delete state.values[key]; });
            if (enabled) ensurePanel(tabKey);
            renderTabs();
            renderChips();
            return;
        }
        window.BackendSettingsPanel.toggleMountedTab({
            mountedTabs: state.mountedTabs,
            tabKey: tabKey,
            enabled: enabled,
            clearTabValues: function(key) {
                settingKeysForTab(key).forEach(function(settingKey) { delete state.values[settingKey]; });
            },
            afterChange: function() {
                if (enabled) ensurePanel(tabKey);
                renderTabs();
                renderChips();
            },
        });
    }

    function renderChooser() {
        var container = ensurePanel('__manage__');
        if (!container || !state.manifest) return;
        if (!window.BackendSettingsPanel || typeof window.BackendSettingsPanel.renderChooser !== 'function') return;
        var allowed = sharedGlobalDefaultKeySet();
        window.BackendSettingsPanel.renderChooser({
            host: container,
            tabs: tabs(),
            mountedTabs: state.mountedTabs,
            introText: '选择可作为各测试模块全局默认值的设置。',
            isVisible: function(tab) { return tabHasSharedGlobalDefaults(tab.key); },
            defaultsForTab: function(tab) {
                return settingKeysForTab(tab.key).map(function(key) {
                    if (!allowed[key]) return null;
                    var setting = Object.assign({ key: key }, defaults()[key] || {});
                    return {
                        tabKey: tab.key,
                        setting: setting,
                        label: setting.label || key,
                        value: displayValue(setting, effectiveValue(key)),
                    };
                }).filter(Boolean);
            },
            renderChip: function(item) {
                return makeChip(item.tabKey, item.label, item.value);
            },
            onToggle: function(tab, enabled) { toggleMounted(tab.key, enabled); },
        });
    }

    function syncRegisteredTimeRange() {
        clearTimeout(state.timeSyncTimer);
        state.timeSyncTimer = setTimeout(function() {
            persistRegisteredTimeRange();
        }, 1000);
    }

    function persistRegisteredTimeRange() {
        var precision = effectiveValue('time_precision') || 'exact';
        var payload = {
            page_uuid: window._pageUuid || '',
            factor_family_alias: window.factorFamilyAlias || window._sftCurrentFactorId || '',
            start_date: effectiveValue('start_date') || '',
            end_date: effectiveValue('end_date') || '',
            start_time: precision === 'trading_day' ? '00:00' : (effectiveValue('start_time') || '00:00'),
            end_time: precision === 'trading_day' ? '00:00' : (effectiveValue('end_time') || '23:59'),
            timezone: precision === 'trading_day' ? 'UTC' : (effectiveValue('timezone') || 'Asia/Shanghai'),
            is_trading_day: precision === 'trading_day',
            is_cn_futures_day: false,
            is_cn_futures_night: false,
        };
        var status = document.getElementById('single-factor-page-time-status');
        if (status) {
            status.textContent = '正在更新页面默认时间范围...';
            status.style.color = '#2563eb';
        }
        if (typeof window.applySharedRuntimeTimeRange === 'function') {
            window.applySharedRuntimeTimeRange(payload, { persist: false });
        }
        window._confirmedTimeData = payload;
        document.dispatchEvent(new CustomEvent('pageTimeRangeChanged', { detail: payload }));
        broadcastGlobalSettingsChanged();
        if (status) {
            status.textContent = '已更新';
            status.style.color = '#16a34a';
        }
        renderChips();
    }

    function renderRegisteredTimeTab(options) {
        var container = state.containers.time;
        if (!container) return;
        options = options || {};
        if (!options.keepValues) syncTimeDefaultsFromPage();
        container.innerHTML = '<span style="color:#64748b;font-size:12px;">正在加载...</span>';
        loadTab('time').then(function(manifest) {
            container.innerHTML = '';
            var grid = document.createElement('div');
            grid.className = 'backend-settings-grid';
            (manifest.settings || []).forEach(function(setting) {
                if (!settingVisible(setting)) return;
                var row = document.createElement('label');
                row.className = 'gt-backtest-setting-row';
                var label = document.createElement('span');
                label.className = 'gt-backtest-setting-label';
                label.textContent = setting.label;
                var controlWrap = document.createElement('span');
                controlWrap.className = 'gt-backtest-setting-control';
                controlWrap.appendChild(makeSettingControl(setting));
                row.appendChild(label);
                row.appendChild(controlWrap);
                grid.appendChild(row);
            });
            var status = document.createElement('span');
            status.id = 'single-factor-page-time-status';
            status.className = 'single-factor-page-settings-status';
            container.appendChild(grid);
            container.appendChild(status);
        }).catch(function(error) {
            container.textContent = '加载失败：' + error.message;
        });
    }

    function renderRegisteredSettingsTab(tabKey) {
        var container = state.containers[tabKey];
        if (!container) return;
        container.innerHTML = '<span style="color:#64748b;font-size:12px;">正在加载...</span>';
        loadTab(tabKey).then(function(manifest) {
            container.innerHTML = '';
            var grid = document.createElement('div');
            grid.className = 'backend-settings-grid';
            (manifest.settings || []).forEach(function(setting) {
                if (!settingVisible(setting)) return;
                var row = document.createElement('label');
                row.className = 'gt-backtest-setting-row';
                var label = document.createElement('span');
                label.className = 'gt-backtest-setting-label';
                label.textContent = setting.label;
                var controlWrap = document.createElement('span');
                controlWrap.className = 'gt-backtest-setting-control';
                controlWrap.appendChild(makeSettingControl(setting));
                row.appendChild(label);
                row.appendChild(controlWrap);
                grid.appendChild(row);
            });
            container.appendChild(grid);
        }).catch(function(error) {
            container.textContent = '加载失败：' + error.message;
        });
    }

    function loadFactorCandidates() {
        if (Array.isArray(window.factorList) && window.factorList.length) {
            return Promise.resolve(window.factorList);
        }
        var alias = window.factorFamilyAlias || window._sftCurrentFactorId || '';
        if (!alias) return Promise.resolve([]);
        return requestJSON('/api/factor_list?factor_family_alias=' + encodeURIComponent(alias)).then(function(data) {
            var factors = data.factors || [];
            window.factorList = factors;
            return factors;
        });
    }

    function renderFactorCandidateChipList(container) {
        container.innerHTML = '<span style="color:#64748b;font-size:12px;">正在加载因子候选...</span>';
        loadFactorCandidates().then(function(factors) {
            container.innerHTML = '';
            var label = document.createElement('div');
            label.className = 'gt-backtest-setting-label';
            label.style.marginBottom = '6px';
            label.textContent = '因子候选 (' + factors.length + ')';
            container.appendChild(label);
            if (!factors.length) {
                var empty = document.createElement('div');
                empty.style.cssText = 'color:#888;font-size:12px;padding:6px 0;';
                empty.textContent = '暂无因子候选数据';
                container.appendChild(empty);
                return;
            }
            var currentAlias = String(effectiveValue('factor') || '');
            var row = document.createElement('div');
            row.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;';
            factors.forEach(function(factor) {
                var alias = factor.alias || factor.name || '';
                var isCurrent = !!currentAlias && alias === currentAlias;
                var chip = document.createElement('span');
                chip.className = 'gt-backend-chip' + (isCurrent ? ' is-primary' : '');
                chip.style.cursor = 'pointer';
                chip.innerHTML = '<span class="gt-backend-chip-value">' + escapeHtml(alias) + '</span>';
                chip.title = '查看因子信息';
                chip.addEventListener('click', function() {
                    if (window.FactorInfoOverlay) window.FactorInfoOverlay.open(factor);
                });
                row.appendChild(chip);
            });
            container.appendChild(row);
        }).catch(function(error) {
            container.innerHTML = '<span style="color:#d40000;font-size:12px;">加载失败：' + escapeHtml(error.message) + '</span>';
        });
    }

    function setProductPathDefault(selection) {
        if (selection) state.values.product_path_selection = selection;
        else delete state.values.product_path_selection;
        renderChips();
        renderProductPathSelectionTab();
        broadcastGlobalSettingsChanged();
    }

    /* ── Factor-param tab (analogous to product_path_selection tab) ── */

    function factorFamilyAlias() {
        return window.factorFamilyAlias || window._sftCurrentFactorId || '';
    }

    function getParamDefs() {
        var paramModule = document.getElementById('parameter_module');
        if (!paramModule) return [];
        var aliasesAttr = paramModule.getAttribute('data-param-aliases');
        var metasAttr = paramModule.getAttribute('data-param-metas');
        var aliases = [];
        var metas = [];
        try { if (aliasesAttr) aliases = JSON.parse(aliasesAttr); } catch(e) {}
        try { if (metasAttr) metas = JSON.parse(metasAttr); } catch(e) {}
        var metaMap = {};
        metas.forEach(function(m) { if (m && m.alias) metaMap[m.alias] = m; });
        return aliases.map(function(alias) {
            var meta = metaMap[alias] || {};
            return {
                alias: alias,
                label: meta.label || meta.display_name || alias,
                default_value: meta.default_value !== undefined ? meta.default_value : '',
            };
        });
    }

    function factorLibraryParams() {
        var value = state.values.factor_candidates;
        return Array.isArray(value) ? value : [];
    }

    function setFactorLibraryParams(params) {
        state.values.factor_candidates = Array.isArray(params) ? params.slice() : [];
    }

    function loadFactorLibraryParams(force) {
        if (state._factorLibraryParamsLoaded && !force) return Promise.resolve(factorLibraryParams());
        var ffAlias = factorFamilyAlias();
        if (!ffAlias) return Promise.resolve([]);
        return requestJSON('/api/param-factor-overview?factor_family_alias=' + encodeURIComponent(ffAlias)).then(function(payload) {
            var factors = Array.isArray(payload.factors) ? payload.factors : [];
            var utils = window.FactorParamSelectionUtils || {};
            var params = factors.map(function(item) {
                return utils.factorItemToParamSelection ? utils.factorItemToParamSelection(item) : item;
            });
            setFactorLibraryParams(params);
            state._factorLibraryParamsLoaded = true;
            return params;
        }).catch(function() {
            return [];
        });
    }

    function getSessionFactorParams() {
        // Read current session params from the param table DOM (parameter_module)
        var paramModule = document.getElementById('parameter_module');
        if (!paramModule) return [];
        var tbody = paramModule.querySelector('#factor_table_body');
        if (!tbody) return [];
        var aliasesAttr = paramModule.getAttribute('data-param-aliases');
        var aliases = [];
        try { if (aliasesAttr) aliases = JSON.parse(aliasesAttr); } catch(e) {}
        var rows = [];
        var trs = tbody.querySelectorAll('tr');
        var ffAlias = factorFamilyAlias();
        trs.forEach(function(tr) {
            var cells = tr.querySelectorAll('td');
            if (cells.length < aliases.length + 1) return;
            var factorAlias = (cells[0].textContent || '').trim();
            if (!factorAlias) return;
            var params = {};
            aliases.forEach(function(alias, i) {
                params[alias] = (cells[i + 1].textContent || '').trim();
            });
            rows.push({ factor_alias: factorAlias, factor_family_alias: ffAlias, scope_key: '现场', params: params, source_type: 'session' });
        });
        return rows;
    }

    function renderParametersTab() {
        var container = state.containers.parameters;
        if (!container) return;
        container.innerHTML = '<span style="color:#64748b;font-size:12px;">正在加载参数...</span>';

        var paramDefs = getParamDefs();
        var ffAlias = factorFamilyAlias();
        var sessionParams = getSessionFactorParams();

        loadFactorLibraryParams(false).then(function(libraryParams) {
            if (!window.FactorParamSelectionUtils || typeof window.FactorParamSelectionUtils.renderFactorParamSettingsTab !== 'function') {
                container.textContent = '因子参数设置组件未加载';
                return;
            }
            window.FactorParamSelectionUtils.renderFactorParamSettingsTab({
                host: container,
                prefix: 'page-fps',
                factorFamilyAlias: ffAlias,
                paramDefs: paramDefs,
                currentFactorParams: sessionParams,
                libraryFactorParams: libraryParams,
                manualTitle: '现场新增因子参数',
                addLabel: '新增到参数列表',
                escapeHTML: escapeHtml,
                onLoadFromLibrary: function(param) {
                    // Insert param row from library into current session table
                    if (!param || !ffAlias) return;
                    var body = {
                        factor_family_alias: ffAlias,
                        params: param.params || {}
                    };
                    fetch('/add_params', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body)
                    })
                    .then(function(res) { return res.json(); })
                    .then(function(data) {
                        if (data.success) {
                            if (typeof window._renderParamFactorRows === 'function') {
                                window._renderParamFactorRows(data.factor_rows || []);
                            }
                            if (typeof window._updateParamSummary === 'function') window._updateParamSummary();
                            if (typeof window.refreshICModule === 'function') window.refreshICModule();
                            renderParametersTab(); // re-render to reflect changes
                        }
                    }).catch(function(e) {
                        console.error('[fps] load from library failed:', e);
                    });
                },
                onRemoveParam: function(alias) {
                    if (!alias || !ffAlias) return;
                    // Find the row index from the current session table
                    var paramModule = document.getElementById('parameter_module');
                    var tbody = paramModule && paramModule.querySelector('#factor_table_body');
                    if (!tbody) return;
                    var trs = tbody.querySelectorAll('tr');
                    var targetIdx = -1;
                    trs.forEach(function(tr, idx) {
                        var firstCell = tr.querySelector('td');
                        if (firstCell && (firstCell.textContent || '').trim() === alias) {
                            targetIdx = idx;
                        }
                    });
                    if (targetIdx < 0) return;
                    fetch('/delete_params', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            factor_family_alias: ffAlias,
                            factor_idx: targetIdx
                        })
                    })
                    .then(function(res) { return res.json(); })
                    .then(function(data) {
                        if (data.success) {
                            if (typeof window._renderParamFactorRows === 'function') {
                                window._renderParamFactorRows(data.factor_rows || []);
                            }
                            if (typeof window._updateParamSummary === 'function') window._updateParamSummary();
                            if (typeof window.refreshICModule === 'function') window.refreshICModule();
                            renderParametersTab(); // re-render to reflect changes
                        }
                    }).catch(function(e) {
                        console.error('[fps] remove failed:', e);
                    });
                },
                onAddParam: function(alias, params) {
                    if (!alias || !ffAlias) return;
                    var body = {
                        factor_family_alias: ffAlias,
                        params: params || {}
                    };
                    fetch('/add_params', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body)
                    })
                    .then(function(res) { return res.json(); })
                    .then(function(data) {
                        if (data.success) {
                            if (typeof window._renderParamFactorRows === 'function') {
                                window._renderParamFactorRows(data.factor_rows || []);
                            }
                            if (typeof window._updateParamSummary === 'function') window._updateParamSummary();
                            if (typeof window.refreshICModule === 'function') window.refreshICModule();
                            renderParametersTab(); // re-render to reflect changes
                        } else {
                            alert('添加失败: ' + (data.error || '未知错误'));
                        }
                    }).catch(function(e) {
                        console.error('[fps] add failed:', e);
                    });
                },
            });
        }).catch(function(error) {
            container.textContent = '加载失败：' + error.message;
        });
    }

    /* ── end factor-param tab ── */

    function renderProductPathSelectionTab() {
        var container = state.containers.product_path_selection;
        if (!container) return;
        container.innerHTML = '<span style="color:#64748b;font-size:12px;">正在加载产品路径...</span>';
        loadProductPathSelections(false).then(function(selections) {
            if (!window.ProductPathSelectionUtils || typeof window.ProductPathSelectionUtils.renderSelectionSettingsTab !== 'function') {
                container.textContent = '产品路径设置组件未加载';
                return;
            }
            window.ProductPathSelectionUtils.renderSelectionSettingsTab({
                host: container,
                prefix: 'page-pps',
                selections: selections,
                currentSelection: effectiveValue('product_path_selection'),
                currentLabel: '页面默认',
                manualTitle: '页面现场路径组',
                createLabel: '新增到页面候选列表',
                createDefaultLabel: '新增并设为默认',
                escapeHTML: escapeHtml,
                onSetDefault: setProductPathDefault,
                onCreate: function(selection, meta) {
                    setProductPathCandidates(productPathCandidates().concat([selection]));
                    if (meta && meta.setAsDefault) state.values.product_path_selection = selection;
                    renderProductPathSelectionTab();
                    broadcastGlobalSettingsChanged();
                },
            });
        }).catch(function(error) {
            container.textContent = '加载失败：' + error.message;
        });
    }

    function observeSummaries() {
        ['global-tpl-save-status', 'time-summary-text'].forEach(function(id) {
            var node = document.getElementById(id);
            if (!node || !window.MutationObserver) return;
            new MutationObserver(renderChips).observe(node, { childList: true, characterData: true, subtree: true });
        });
        document.addEventListener('singleFactorTemplateChanged', renderChips);
        document.addEventListener('singleFactorFactorCandidatesChanged', function(event) {
            var candidates = event && event.detail && Array.isArray(event.detail.candidates)
                ? event.detail.candidates.slice()
                : [];
            state.values.factor_candidates = candidates;
            var current = state.values.factor || '';
            var exists = candidates.some(function(item) {
                return String(item.alias || item.name || '') === String(current);
            });
            state.values.factor = exists ? current : (candidates[0] ? (candidates[0].alias || candidates[0].name || '') : '');
            renderTabs();
            renderChips();
            broadcastGlobalSettingsChanged();
        });
    }

    function init() {
        requestJSON('/api/backtest/settings/' + APP).then(function(manifest) {
            state.manifest = manifest;
            state.mountedTabs = (manifest.default_mounted_tabs && manifest.default_mounted_tabs[LOCAL] || []).slice();
            Object.keys(manifest.defaults || {}).forEach(function(key) {
                state.values[key] = manifest.defaults[key].value;
            });
            syncTimeDefaultsFromPage();
            renderShell();
            observeSummaries();
            openTab('setting_template');
        }).catch(function(error) {
            console.error('[single-factor-page-settings] init failed:', error);
        });
    }

    window.SingleFactorGlobalSettings = {
        getDefaultValues: function(keys) {
            var allowed = sharedGlobalDefaultKeySet();
            var out = {};
            (Array.isArray(keys) ? keys : []).forEach(function(key) {
                if (!allowed[key]) return;
                if (!Object.prototype.hasOwnProperty.call(defaults(), key)) return;
                out[key] = effectiveValue(key);
            });
            return out;
        },
        sharedDefaultKeys: sharedGlobalDefaultKeys,
    };

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
