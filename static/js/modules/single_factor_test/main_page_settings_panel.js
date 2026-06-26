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

    // 原生渲染"模板"标签页：构建工具栏 + 列表骨架，再交由
    // global_template_module.js 绑定保存按钮并加载模板列表。幂等。
    function renderSettingTemplateTab() {
        var container = state.containers.setting_template;
        if (!container) return;
        if (container.dataset.rendered !== '1') {
            container.dataset.rendered = '1';
            container.innerHTML = ''
                + '<div class="module global-template-panel">'
                + '  <div class="global-template-toolbar">'
                + '    <input type="text" id="global-tpl-save-name" placeholder="模板名称（默认当前时间戳）"'
                + '           style="margin-bottom:10px !important;margin-top:10px !important;margin-left:5px !important;">'
                + '    <button class="btn btn-primary btn-sm" id="global-tpl-save-btn">保存当前设置</button>'
                + '    <span id="global-tpl-save-status" class="global-template-status"></span>'
                + '  </div>'
                + '  <div id="global-tpl-list" class="global-template-list">'
                + '    <div class="global-template-empty">加载中...</div>'
                + '  </div>'
                + '</div>';
        }
        if (typeof window._bindGlobalTemplatePanel === 'function') {
            window._bindGlobalTemplatePanel();
        } else {
            setTimeout(function() {
                if (typeof window._bindGlobalTemplatePanel === 'function') window._bindGlobalTemplatePanel();
            }, 50);
        }
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

    function isEmptyValue(v) {
        return v === undefined || v === null || v === '' || (Array.isArray(v) && v.length === 0);
    }

    // ── 统一 fallback 入口：扫描 manifest 中声明了 load_*_when_page_empty 的字段，字段空时调用对应 loader ──
    // fallback_policy 形如 ("copy_page_candidates", "load_factor_library_when_page_empty")
    // "copy_page_candidates" 由 FieldStore.effective() 的 shared_page_field 处理（子模块 store 已 wired parent）；
    // "load_*_when_page_empty" 由这里的异步 loader 在页面初始化时填满页面字段。
    var PAGE_FALLBACK_LOADERS = {
        load_user_product_groups_when_page_empty: function(fieldKey, serial) {
            return requestJSON('/api/product-groups').then(function(payload) {
                var selections = (payload.groups || []).map(productGroupToSelection);
                var utils = window.ProductPathSelectionUtils || {};
                if (utils.dedupe) selections = utils.dedupe(selections);
                state.productPathSelections = selections;
                state.values[fieldKey] = selections;
                state.productPathSelectionsLoaded = true;
            });
        },
        load_factor_library_when_page_empty: function(fieldKey, serial) {
            var ffAlias = window.factorFamilyAlias || window._sftCurrentFactorId || '';
            if (!ffAlias) return Promise.resolve();
            return requestJSON('/custom-factors/api/factor-library-overview?factor_family_alias=' + encodeURIComponent(ffAlias)).then(function(payload) {
                var factors = Array.isArray(payload.factors) ? payload.factors : [];
                // 按当前 product_path_selection 的产品组过滤（与 loadFactorLibraryParams 逻辑一致）
                var group = currentFactorLibraryProductGroup();
                factors = filterFactorLibraryByProductGroup(factors, group);
                var utils = window.FactorParamSelectionUtils || {};
                var params = factors.map(function(item) {
                    return utils.factorItemToParamSelection ? utils.factorItemToParamSelection(item) : item;
                });
                state.values[fieldKey] = params;
                setFactorLibraryParams(params);
                state._factorLibraryParamsLoaded = true;
            });
        },
        load_data_source_categories_when_page_empty: function(fieldKey, serial) {
            // 分类来源：数据源内置 category（后续接入；目前不触发网络请求）
            return Promise.resolve();
        },
    };

    function populatePageFieldsWhenEmpty() {
        var defs = defaults();
        var promises = [];
        Object.keys(defs).forEach(function(key) {
            var value = state.values[key];
            if (!isEmptyValue(value)) return;  // 字段已有值，不覆盖
            var s = (defs[key] || {}).serialization;
            if (!s || !Array.isArray(s.fallback_policy)) return;
            s.fallback_policy.forEach(function(policy) {
                if (typeof policy !== 'string' || policy.indexOf('load_') !== 0) return;
                var loader = PAGE_FALLBACK_LOADERS[policy];
                if (typeof loader === 'function') {
                    promises.push(loader(key, s).catch(function(err) {
                        console.warn('[page-fallback] ' + policy + ' failed for ' + key, err);
                    }));
                }
            });
        });
        return Promise.all(promises).then(function() {
            syncPageStore();
            renderChips();
            broadcastGlobalSettingsChanged();
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

    // 旧的 chip 计算链（settingChipParts/registeredTabChipParts/chipPartsForTab）已删除，
    // chip 改由 manifest 驱动的 ChipRenderer + FieldStore 渲染（见 renderChips）。

    // ── 响应式 chip：manifest 建 FieldStore（backing = state.values），ChipRenderer 订阅 ──
    var pageStore = null;
    var pageChipUnbind = null;
    function ensurePageStore() {
        if (!pageStore && state.manifest && window.FieldStore) {
            pageStore = window.FieldStore.create({ defaults: state.manifest.defaults, values: state.values });
        }
        // 暴露给 global_template_module 等外部模块，通过 store.set('setting_template', name) 直接驱动 chip 刷新
        window._singleFactorPageStore = pageStore;
        return pageStore;
    }
    function syncPageStore() {
        var s = ensurePageStore();
        if (s) s.setMany(state.values);  // state.values 是页面字段真源（候选已同步进去）
    }

    function renderChips() {
        var row = document.getElementById('single-factor-page-settings-chips');
        if (!row) return;
        ensurePageStore();
        syncPageStore();
        if (pageChipUnbind) { pageChipUnbind(); pageChipUnbind = null; }

        var mounted = orderedMountedTabs();
        var chipKeys = [];
        mounted.forEach(function(tabKey) {
            settingKeysForTab(tabKey).forEach(function(key) {
                if ((defaults()[key] || {}).chip_template) chipKeys.push(key);
            });
        });
        if (window.ChipRenderer && pageStore) {
            pageChipUnbind = window.ChipRenderer.render(row, {
                manifest: state.manifest,
                store: pageStore,
                settingKeys: chipKeys,
                tabOf: function(key) { return (defaults()[key] || {}).tab_key || key; },
                onOpen: function(tabKey) { openTab(tabKey); },
                escapeHTML: escapeHtml,
                renderChipHtml: renderChipHtml,
            });
        } else {
            row.innerHTML = '';
        }
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
            renderSettingTemplateTab();
            return;
        }
        if (tabKey === 'time') {
            renderRegisteredTimeTab();
            return;
        }
        if (tabKey === 'product_path_selection') {
            renderProductPathSelectionTab();
            return;
        }
        if (tabKey === 'factors') {
            renderFactorsTab();
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
        window.BackendSettingsPanel.renderChooser({
            host: container,
            manifest: state.manifest,
            store: pageStore,
            tabs: tabs(),
            mountedTabs: state.mountedTabs,
            introText: '选择可作为各测试模块全局默认值的设置。',
            isVisible: function(tab) { return tabHasSharedGlobalDefaults(tab.key); },
            escapeHTML: escapeHtml,
            renderChipHtml: renderChipHtml,
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

    function setProductPathDefault(selection) {
        if (selection) state.values.product_path_selection = selection;
        else delete state.values.product_path_selection;
        renderChips();
        renderProductPathSelectionTab();
        // 因子库候选列表按当前产品组现场过滤，产品组变化后需要重新加载。
        if (state.containers.factors) loadFactorLibraryParams(true).then(renderFactorsTab);
        broadcastGlobalSettingsChanged();
    }

    // 页面级默认因子（factor，单选）——与 product_path_selection 同构：
    // 测试模块单选 factor 为空时回退到此字段（manifest 的 shared_page_field）。
    function setFactorDefault(alias) {
        state.values.factor = alias || '';
        renderChips();
        renderFactorsTab();
        broadcastGlobalSettingsChanged();
    }

    /* ── Factor-param tab (analogous to product_path_selection tab) ── */

    function factorFamilyAlias() {
        return window.factorFamilyAlias || window._sftCurrentFactorId || '';
    }

    function getParamDefs() {
        // Read param definitions from the top-level section's data attributes
        var section = document.querySelector('.section[data-param-aliases]');
        if (!section) return [];
        var aliasesAttr = section.getAttribute('data-param-aliases');
        var metasAttr = section.getAttribute('data-param-metas');
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

    // 因子库"现场加载池"（可从中加载到工作列表），与持久化的工作候选列表
    // state.values.factor_candidates 分开：后者镜像当前会话因子（chip 计数据此）。
    function factorLibraryParams() {
        return Array.isArray(state._factorLibraryPool) ? state._factorLibraryPool : [];
    }

    function setFactorLibraryParams(params) {
        state._factorLibraryPool = Array.isArray(params) ? params.slice() : [];
    }

    // 把工作候选列表（= 当前会话因子，shape {alias,in_library,library_product_group,params}）
    // 同步到 state.values.factor_candidates，供 chip 计数与快照收集。
    function syncFactorCandidatesValue() {
        state.values.factor_candidates = collectFactorCandidates();
    }

    // 因子库中的因子参数行可以绑定某个产品组，也可以不绑定（DEFAULT_SCOPE_KEY）。
    // 候选列表语义（类比"产品组要从用户的产品组中加载"，候选不持久化进模板，
    // 而是每次按页面当前产品组上下文从因子库现场加载）：
    //   - 页面未设置默认产品路径（或其为"路径组/现场"而非"产品组"）→ 仅未绑定产品组的因子库参数
    //   - 页面默认产品路径是某"产品组" → 未绑定产品组 + 恰好绑定该产品组的因子库参数
    var FACTOR_LIBRARY_DEFAULT_SCOPE = 'default';

    function factorLibraryScopeKey(item) {
        return (item && (item.scope_key || item.product_group || item.productGroup)) || '';
    }

    function isFactorLibraryUnboundScope(scope) {
        return !scope || scope === FACTOR_LIBRARY_DEFAULT_SCOPE || scope === '默认';
    }

    // 当前页面默认产品路径若是一个"产品组"（而非路径组/现场），返回其产品组名
    // 以匹配因子库的 scope_key；否则返回 null（视为"无产品组绑定"）。
    function currentFactorLibraryProductGroup() {
        var selection = state.values.product_path_selection;
        if (!selection) return null;
        var utils = window.ProductPathSelectionUtils;
        var sourceLabel = utils && typeof utils.selectionSourceLabel === 'function'
            ? utils.selectionSourceLabel(selection) : '';
        if (sourceLabel !== '产品组') return null;
        return selection.product_group || selection.product_group_name || null;
    }

    function filterFactorLibraryByProductGroup(items, groupName) {
        return (items || []).filter(function(item) {
            var scope = factorLibraryScopeKey(item);
            if (isFactorLibraryUnboundScope(scope)) return true;
            return !!groupName && scope === groupName;
        });
    }

    function loadFactorLibraryParams(force) {
        if (state._factorLibraryParamsLoaded && !force) return Promise.resolve(factorLibraryParams());
        var ffAlias = factorFamilyAlias();
        if (!ffAlias) return Promise.resolve([]);
        return requestJSON('/custom-factors/api/factor-library-overview?factor_family_alias=' + encodeURIComponent(ffAlias)).then(function(payload) {
            var factors = Array.isArray(payload.factors) ? payload.factors : [];
            factors = filterFactorLibraryByProductGroup(factors, currentFactorLibraryProductGroup());
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
        // Initialize from backend-injected data on first call
        if (!state._sessionParams && Array.isArray(window._initialSessionParams)) {
            setSessionFactorParams(window._initialSessionParams);
        }
        return Array.isArray(state._sessionParams) ? state._sessionParams : [];
    }

    function setSessionFactorParams(params) {
        state._sessionParams = Array.isArray(params) ? params.slice() : [];
        syncFactorCandidatesValue();  // 工作候选列表随会话因子变化，chip 计数才正确
    }

    function renderFactorsTab() {
        var container = state.containers.factors;
        if (!container) return;
        container.innerHTML = '<span style="color:#64748b;font-size:12px;">正在加载参数...</span>';

        var paramDefs = getParamDefs();
        var ffAlias = factorFamilyAlias();

        // Initialize session params from backend-injected data on first call
        if (!state._sessionParams && Array.isArray(window._initialSessionParams)) {
            setSessionFactorParams(window._initialSessionParams);
        }
        var sessionParams = getSessionFactorParams();
        // 工作候选列表与 chip 计数随会话因子保持同步（含直接改 _sessionParams 的路径）
        syncFactorCandidatesValue();
        renderChips();

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
                selectionMode: 'single',
                currentSelection: state.values.factor || '',
                onSetDefault: setFactorDefault,
                manualTitle: '现场新增因子参数',
                addLabel: '新增到参数列表',
                escapeHTML: escapeHtml,
                onLoadFromLibrary: function(param) {
                    // Insert param row from library into page_factors via backend, then track locally
                    if (!param || !ffAlias) return;
                    var body = {
                        factor_family_alias: ffAlias,
                        params: param.params || {},
                        page_uuid: window._pageUuid || ''
                    };
                    fetch('/add_factor_by_params', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body)
                    })
                    .then(function(res) { return res.json(); })
                    .then(function(data) {
                        if (data.success) {
                            // Use backend-returned factor_rows for canonical data
                            if (data.factor_rows && data.factor_rows.length) {
                                setSessionFactorParams(data.factor_rows.map(function(row) {
                                    return candidateToSessionRow({ alias: row.factor_alias, in_library: param.in_library, library_product_group: param.library_product_group, params: row.params }, ffAlias);
                                }));
                            } else {
                                state._sessionParams = getSessionFactorParams().concat([param]);
                            }
                            if (typeof window.refreshICModule === 'function') window.refreshICModule();
                            renderFactorsTab();
                        }
                    }).catch(function(e) {
                        console.error('[fps] load from library failed:', e);
                    });
                },
                onRemoveParam: function(alias) {
                    if (!alias || !ffAlias) return;
                    // Frontend manages candidate list locally — no backend call needed.
                    // Factor instances in page_factors are cleaned up on page lifecycle.
                    var params = getSessionFactorParams();
                    var targetIdx = -1;
                    for (var i = 0; i < params.length; i++) {
                        if (params[i].factor_alias === alias) {
                            targetIdx = i;
                            break;
                        }
                    }
                    if (targetIdx < 0) return;
                    params.splice(targetIdx, 1);
                    state._sessionParams = params;
                    if (typeof window.refreshICModule === 'function') window.refreshICModule();
                    renderFactorsTab();
                },
                onAddParam: function(alias, params) {
                    if (!alias || !ffAlias) return;
                    var body = {
                        factor_family_alias: ffAlias,
                        params: params || {},
                        page_uuid: window._pageUuid || ''
                    };
                    fetch('/add_factor_by_params', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body)
                    })
                    .then(function(res) { return res.json(); })
                    .then(function(data) {
                        if (data.success) {
                            // Update cache so snapshot collect reads latest
                            state._sessionParams = getSessionFactorParams().concat([{
                                factor_alias: alias,
                                factor_family_alias: ffAlias,
                                params: params,
                                scope_key: '现场',
                                source_type: 'session'
                            }]);
                            if (typeof window.refreshICModule === 'function') window.refreshICModule();
                            renderFactorsTab(); // re-render to reflect changes
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

    // ── 因子面板的快照存取（供 Panels 注册表使用） ────────────────────────────
    // 持久化字段镜像 product_path：factor_candidates（候选列表）+ factor（选中）。
    // 每个候选形如 { alias, in_library, library_product_group, params }，自带库归属，
    // 恢复时无需再向因子库现场交叉比对。
    function cleanParamDict(params) {
        var p = {};
        Object.keys(params || {}).forEach(function(k) { if (params[k] !== '') p[k] = params[k]; });
        return p;
    }

    // 会话参数行 → 候选项。scope_key 在加载/恢复时已标好库归属：
    //   '现场' → in_library=false；产品组名 → in_library=true(bound)；未绑定sentinel → in_library=true(unbound)
    function sessionRowToCandidate(row) {
        var scope = row.scope_key || '';
        var inLibrary = scope !== '' && scope !== '现场';
        return {
            alias: row.factor_alias || '',
            in_library: inLibrary,
            library_product_group: (inLibrary && !isFactorLibraryUnboundScope(scope)) ? scope : null,
            params: cleanParamDict(row.params),
        };
    }

    // 候选项 → 会话参数行（恢复时用，保留库归属元数据）
    function candidateToSessionRow(c, ffAlias) {
        var scope = c.in_library ? (c.library_product_group || FACTOR_LIBRARY_DEFAULT_SCOPE) : '现场';
        return {
            factor_alias: c.alias || '',
            factor_family_alias: ffAlias,
            scope_key: scope,
            source_type: c.in_library ? 'library' : 'session',
            params: c.params || {},
        };
    }

    function collectFactorCandidates() {
        return getSessionFactorParams().map(sessionRowToCandidate);
    }

    // 因子 tab 默认隐藏；加载的模板含因子设置时懒挂载它。
    function ensureFactorsTabMounted() {
        if (state.mountedTabs.indexOf('factors') < 0) {
            state.mountedTabs.push('factors');
            ensurePanel('factors');
            renderTabs();
        }
    }

    async function applyFactorsSnapshot(subset) {
        var candidates = (subset && Array.isArray(subset.factor_candidates)) ? subset.factor_candidates : [];
        var ffAlias = factorFamilyAlias();
        if (subset && Object.prototype.hasOwnProperty.call(subset, 'factor')) {
            state.values.factor = subset.factor || '';
        }
        if (candidates.length || (subset && subset.factor)) ensureFactorsTabMounted();
        if (!candidates.length || !ffAlias) { renderFactorsTab(); renderChips(); return; }
        try {
            // Push each candidate to backend page_factors via /add_factor_by_params.
            // Frontend manages candidate list locally; backend stores Factor instances.
            var pageUuid = window._pageUuid || '';
            for (var i = 0; i < candidates.length; i++) {
                var c = candidates[i];
                var resp = await fetch('/add_factor_by_params', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        factor_family_alias: ffAlias,
                        params: c.params || {},
                        page_uuid: pageUuid,
                    }),
                });
                var result = await resp.json();
                if (!result.success) { alert('恢复因子 ' + (c.alias || ('#' + (i + 1))) + ' 失败: ' + (result.error || '')); return; }
            }
            // Update local candidate list from what was pushed
            setSessionFactorParams(candidates.map(function(c) { return candidateToSessionRow(c, ffAlias); }));
            renderFactorsTab();
            renderChips();
            if (typeof window.refreshICModule === 'function') window.refreshICModule();
        } catch (e) {
            alert('恢复因子异常: ' + (e && e.message || e));
        }
    }

    function summarizeFactorsSnapshot(subset) {
        var candidates = (subset && subset.factor_candidates) || [];
        var lines = candidates.map(function(c, idx) {
            var src = c.in_library ? (c.library_product_group ? ('因子库·' + c.library_product_group) : '因子库·未绑定') : '现场';
            var parts = [];
            Object.keys(c.params || {}).forEach(function(k) { parts.push(k + '=' + c.params[k]); });
            return (c.alias || ('因子' + (idx + 1))) + ' · ' + src + (parts.length ? ' · ' + parts.join(', ') : '');
        });
        if (subset && subset.factor) lines.unshift('当前因子: ' + subset.factor);
        return lines;
    }

    if (window.Panels) {
        window.Panels.register({
            key: 'factors',
            kind: 'setting',
            label: '因子',
            icon: '⚙️',
            el: '#single-factor-page-settings',
            snapshot: {
                keys: ['factor_candidates', 'factor'],
                order: 20,
                get: function() {
                    return { factor_candidates: collectFactorCandidates(), factor: state.values.factor || '' };
                },
                set: applyFactorsSnapshot,
                summarize: summarizeFactorsSnapshot,
            },
        });
    }

    /* ── end factor-param tab ── */

    function renderProductPathSelectionTab() {
        var container = state.containers.product_path_selection;
        if (!container) return;
        container.innerHTML = '<span style="color:#64748b;font-size:12px;">正在加载产品路径...</span>';
        // 候选已在 init() → populatePageFieldsWhenEmpty() 填充，若仍为空则触发 load_user_product_groups_when_page_empty
        var loadPromise = isEmptyValue(state.values.product_path_candidates)
            ? populatePageFieldsWhenEmpty()
            : Promise.resolve();
        loadPromise.then(function() {
            var selections = productPathCandidates();
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
                    if (meta && meta.setAsDefault) {
                        state.values.product_path_selection = selection;
                        if (state.containers.factors) loadFactorLibraryParams(true).then(renderFactorsTab);
                    }
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
        // 模板 chip 由 FieldStore 订阅自动刷新，不再需要 DOM 事件监听
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
            populatePageFieldsWhenEmpty().then(function() {
                openTab('setting_template');
            });
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
