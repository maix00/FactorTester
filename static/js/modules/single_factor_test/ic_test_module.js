/**
 * IC 测试模块独立脚本（重写版）
 * 支持因子级选择和频率配置
 */
(function() {
    const Progress = window.SingleFactorProgress;
    if (!Progress) throw new Error('SingleFactorProgress bootstrap not loaded');

    // 全局变量
    let factorFamilyAlias = window.factorFamilyAlias || '';
    let factorList = [];  // 存储因子列表 [{alias, name, freq}]
    let icProductPathSelections = [];
    let icSettingsManifest = null;
    let icSettingValues = {};
    let icActiveSettingsTab = null;
    let icMountedSettingsTabs = ['factor', 'product_path_selection'];
    let icContractSelection = {}; // key: `${subId}-${idx}` => Set(contract_uid)
    let icHoverBandState = {}; // key: `${subId}-${idx}` => { from, to }

    if (typeof Highcharts !== 'undefined') {
        Highcharts.setOptions({
            global: { useUTC: false }
        });
    }

    // 辅助函数：获取因子列表（从后端 API）
    async function fetchFactorList() {
        if (!factorFamilyAlias) return [];
        try {
            const res = await fetch(`/api/factor_list?factor_family_alias=${encodeURIComponent(factorFamilyAlias)}`);
            const data = await res.json();
            if (data.success) {
                factorList = data.factors;
                window.factorList = factorList;   // 暴露全局
                return factorList;
            } else {
                console.error('获取因子列表失败:', data.error);
                return [];
            }
        } catch (err) {
            console.error('获取因子列表异常:', err);
            return [];
        }
    }

    function selectionId(selection) {
        const utils = window.ProductPathSelectionUtils;
        if (utils && utils.selectionId) return utils.selectionId(selection);
        return selection ? String(selection.product_path_selection_id || selection.selection_id || selection.id || '') : '';
    }

    function selectionLabel(selection) {
        const utils = window.ProductPathSelectionUtils;
        if (utils && utils.selectionDisplayLabel) return utils.selectionDisplayLabel(selection);
        return selection ? (selection.product_group || selection.label || selection.name || selectionId(selection)) : '';
    }

    function selectionById(id) {
        const target = String(id || '');
        return icProductPathSelections.find(selection => selectionId(selection) === target) || null;
    }

    function createIcProgressController(progressBarId) {
        return Progress.createSimpleProgressController({
            resolve: function() {
                return {
                    wrapper: document.getElementById(progressBarId),
                    bar: document.getElementById(`${progressBarId}-fill`),
                    text: document.getElementById(`${progressBarId}-text`),
                };
            },
        });
    }

    // ── 候选回退已由 FieldStore.effective() + pageStore wired parent 统一处理，
    //    不再需要 ad-hoc productGroupToSelection / loadSharedProductPathSelections。

    // 委托到共用 DomUtils（页面已先加载）；保留薄封装以免改动各调用点。
    function escapeHTML(value) {
        return window.DomUtils.escapeHTML(value);
    }

    function chipParts(labelOrText, value) {
        if (value !== undefined && value !== null && value !== '') {
            return { label: String(labelOrText || ''), value: String(value) };
        }
        const text = String(labelOrText == null ? '' : labelOrText).trim();
        const match = text.match(/^([^:：]{1,16})[:：]\s*(.*)$/);
        if (match && match[2]) return { label: match[1], value: match[2] };
        return { label: '', value: text };
    }

    function renderChipHtml(labelOrText, value) {
        const parts = chipParts(labelOrText, value);
        if (!parts.label) return '<span class="gt-backend-chip-value">' + escapeHTML(parts.value) + '</span>';
        return '<span class="gt-backend-chip-label">' + escapeHTML(parts.label) + '</span>'
            + '<span class="gt-backend-chip-value">' + escapeHTML(parts.value) + '</span>';
    }

    function settingVisible(setting) {
        const values = Object.assign({}, icSettingValues);
        return window.BackendSettingsPanel.settingVisibleForValues(setting, values);
    }

    // ── 响应式 chip：用 manifest 建 FieldStore，运行态值同步进去，chip 订阅字段 ──
    var icStore = null;
    var icChipUnbind = null;
    function ensureICStore() {
        if (!icStore && icSettingsManifest && window.FieldStore) {
            icStore = window.FieldStore.create({ defaults: icSettingsManifest.defaults, values: icSettingValues, parent: window._singleFactorPageStore || null });
        }
        // 延迟绑定：如果创建时 pageStore 未就绪，后续 sync 时补绑
        if (icStore && window._singleFactorPageStore && icStore.setParent) {
            icStore.setParent(window._singleFactorPageStore);
        }
        return icStore;
    }
    // 把运行态候选/选择推进 store（标量字段经 store.set 写入，见控件 change）。
    function syncICStore() {
        var s = ensureICStore();
        if (!s) return;
        s.setMany({
            product_path_selections: (icProductPathSelections || []).slice(),
            product_path_candidates: Array.isArray(icSettingValues.product_path_candidates) ? icSettingValues.product_path_candidates.slice() : [],
            factor_candidates: (factorList || []).slice(),
            factor_selections: collectFactorSelections(),
            category_candidates: Array.isArray(icSettingValues.category_candidates) ? icSettingValues.category_candidates.slice() : [],
        });
    }

    function mergeICProductPathCandidates(selections) {
        if (!Array.isArray(selections)) return icSettingValues.product_path_candidates || [];
        icSettingValues.product_path_candidates = Array.isArray(icSettingValues.product_path_candidates) ? icSettingValues.product_path_candidates.slice() : [];
        for (var i = 0; i < selections.length; i++) {
            var sel = selections[i];
            var sid = selectionId(sel);
            if (!sid) continue;
            var exists = icSettingValues.product_path_candidates.some(function(c) { return selectionId(c) === sid; });
            if (!exists) icSettingValues.product_path_candidates.push(sel);
        }
        syncICStore();
        return icSettingValues.product_path_candidates;
    }

    function isTabMounted(tabKey) {
        return icMountedSettingsTabs.indexOf(tabKey) >= 0;
    }

    function resetTabValues(tabKey, defaults) {
        Object.keys(defaults || {}).forEach(key => {
            const meta = defaults[key] || {};
            if (meta.tab_key === tabKey) icSettingValues[key] = meta.value;
        });
    }

    async function loadICSettingsManifest() {
        if (icSettingsManifest) return icSettingsManifest;
        const pageUuid = encodeURIComponent(window._pageUuid || '');
        const resp = await fetch('/api/backtest/settings/ic_test?page_uuid=' + pageUuid, {
            headers: { Accept: 'application/json' },
        });
        const data = await resp.json();
        if (!resp.ok || data.success === false) {
            throw new Error(data.error || ('HTTP ' + resp.status));
        }
        icSettingsManifest = data;
        icSettingValues = {};
        Object.keys(data.defaults || {}).forEach(key => {
            icSettingValues[key] = data.defaults[key].value;
        });
        applyGlobalICDefaults();
        return data;
    }

    function applyGlobalICDefaults() {
        if (!window.SingleFactorGlobalSettings || typeof window.SingleFactorGlobalSettings.getDefaultValues !== 'function') return false;
        const sharedKeys = (window.SingleFactorGlobalSettings.sharedDefaultKeys && window.SingleFactorGlobalSettings.sharedDefaultKeys()) || [];
        const values = window.SingleFactorGlobalSettings.getDefaultValues(sharedKeys);
        // 候选回退由 FieldStore.effective() 通过 shared_page_field→parent 自动处理，不再手动合并。
        let changed = false;
        ['data_source', 'frequency'].forEach(key => {
            if (!Object.prototype.hasOwnProperty.call(icSettingValues, key)) return;
            if (values[key] === undefined || values[key] === null || values[key] === '') return;
            if (String(icSettingValues[key]) === String(values[key])) return;
            icSettingValues[key] = values[key];
            changed = true;
        });
        return changed;
    }

    function enabledResultTabs(manifest) {
        const defaults = manifest && manifest.defaults ? manifest.defaults : {};
        const values = {};
        Object.keys(defaults).forEach(key => { values[key] = defaults[key].value; });
        Object.keys(icSettingValues || {}).forEach(key => { values[key] = icSettingValues[key]; });
        return (manifest && manifest.result_tabs || []).filter(tab => {
            const requires = tab.requires || {};
            return window.BackendSettingsPanel.matchesConditions(requires, values);
        });
    }

    function renderICResultTabs(subId, manifest) {
        const tabs = enabledResultTabs(manifest);
        if (!tabs.length) return '';
        return '<div class="ic-result-tabs" data-product-path-selection-id="' + subId + '" style="display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 12px;">'
            + tabs.map((tab, idx) => '<button type="button" class="ic-result-tab-btn' + (idx === 0 || tab.default ? ' active' : '') + '" data-result-tab="' + tab.key + '" style="height:26px;padding:0 9px;border:1px solid ' + (idx === 0 || tab.default ? '#2563eb' : '#cbd5e1') + ';border-radius:6px;background:' + (idx === 0 || tab.default ? '#eff6ff' : '#fff') + ';color:' + (idx === 0 || tab.default ? '#1d4ed8' : '#475569') + ';font-size:12px;cursor:pointer;">' + tab.label + '</button>').join('')
            + '</div>';
    }

    function renderICSettingsPanel(manifest) {
        const host = document.getElementById('ic-settings-container');
        if (!host || !manifest) return;
        const defaults = manifest.defaults || {};
        const tabs = (manifest.tab_lists && manifest.tab_lists['local-settings'] || []);
        const settingsByTab = {};
        Object.keys(defaults).forEach(key => {
            const meta = defaults[key];
            if (!settingsByTab[meta.tab_key]) settingsByTab[meta.tab_key] = [];
            settingsByTab[meta.tab_key].push({ key, meta });
        });
        Object.keys(settingsByTab).forEach(tabKey => {
            settingsByTab[tabKey].sort((a, b) => {
                const ao = window.BackendSettingsPanel.settingDisplayOrder(a.meta);
                const bo = window.BackendSettingsPanel.settingDisplayOrder(b.meta);
                if (ao == null && bo == null) return 0;
                if (ao == null) return 1;
                if (bo == null) return -1;
                return ao - bo;
            });
        });
        function renderChooser() {
            if (!window.BackendSettingsPanel || typeof window.BackendSettingsPanel.renderChooser !== 'function') return;
            window.BackendSettingsPanel.renderChooser({
                host: contentHost,
                manifest: manifest,
                store: icStore,
                tabs,
                mountedTabs: icMountedSettingsTabs,
                introText: '选择要挂载到 IC 测试的设置。未挂载项使用后端默认值。',
                isVisible: function(tab) {
                    return !!(settingsByTab[tab.key] || []).length;
                },
                escapeHTML: escapeHTML,
                renderChipHtml: renderChipHtml,
                onToggle: function(tab, enabled) {
                    const tabKey = tab.key;
                    const index = icMountedSettingsTabs.indexOf(tabKey);
                    if (enabled && index < 0) icMountedSettingsTabs.push(tabKey);
                    if (!enabled && index >= 0) {
                        icMountedSettingsTabs.splice(index, 1);
                        resetTabValues(tabKey, defaults);
                        if (icActiveSettingsTab === tabKey) icActiveSettingsTab = '__manage__';
                    }
                    icActiveSettingsTab = '__manage__';
                    if (icProductPathSelections.length) window.renderICTabs(icProductPathSelections);
                    else renderICSettingsPanel(manifest);
                },
            });
        }
        host.innerHTML = ''
            + '<div class="backend-settings-tab-bar" id="ic-settings-tab-bar"></div>'
            + '<div class="backend-settings-chip-row" id="ic-settings-chip-row"></div>'
            + '<div class="backend-settings-host" id="ic-settings-host" style="display:none;"></div>';
        const tabBar = document.getElementById('ic-settings-tab-bar');
        const chipRow = document.getElementById('ic-settings-chip-row');
        const contentHost = document.getElementById('ic-settings-host');

        let tabHtml = '';
        tabs.forEach(tab => {
            const rows = settingsByTab[tab.key] || [];
            if (!rows.length || !isTabMounted(tab.key)) return;
            tabHtml += '<button type="button" data-ic-settings-tab="' + escapeHTML(tab.key) + '" class="' + (icActiveSettingsTab === tab.key ? 'active' : '') + '">'
                + escapeHTML(tab.label || tab.key) + '</button>';
        });
        tabHtml += '<button type="button" data-ic-settings-tab="__manage__" class="' + (icActiveSettingsTab === '__manage__' ? 'active' : '') + '">+ 设置</button>';
        tabBar.innerHTML = tabHtml;

        // chip 栏：manifest 驱动，订阅 FieldStore 字段，字段变更（含 fallback）自动回刷。
        ensureICStore();
        syncICStore();
        const chipKeys = [];
        tabs.forEach(tab => {
            if (!isTabMounted(tab.key)) return;
            (settingsByTab[tab.key] || []).forEach(row => {
                if ((row.meta || {}).chip_template) chipKeys.push(row.key);
            });
        });
        if (icChipUnbind) { icChipUnbind(); icChipUnbind = null; }
        if (window.ChipRenderer && icStore) {
            icChipUnbind = window.ChipRenderer.render(chipRow, {
                manifest: icSettingsManifest,
                store: icStore,
                settingKeys: chipKeys,
                tabOf: function(key) { return (icSettingsManifest.defaults[key] || {}).tab_key || key; },
                onOpen: function(tabKey) { openTab(tabKey); },
                escapeHTML: escapeHTML,
                renderChipHtml: renderChipHtml,
            });
        }

        function renderTabContent(tabKey) {
            const tab = tabs.find(item => item.key === tabKey);
            const rows = settingsByTab[tabKey] || [];
            if (tabKey === '__manage__') {
                renderChooser();
                return;
            }
            if (tabKey === 'product_path_selection') {
                renderICProductPathSelectionTab();
                return;
            }
            if (tabKey === 'factor') {
                renderICFactorSelectionTab();
                return;
            }
            if (tabKey === 'return_frequency') {
                renderICReturnFreqTab();
                return;
            }
            if (tabKey === 'category') {
                renderICCategoryTab();
                return;
            }
            if (!tab || !rows.length || !isTabMounted(tabKey)) {
                contentHost.innerHTML = '';
                return;
            }
            let html = '<div class="backend-settings-grid">';
            rows.forEach(row => {
                const meta = Object.assign({ key: row.key }, row.meta || {});
                if (!settingVisible(meta)) return;
                const value = icSettingValues[row.key];
                html += '<label class="gt-backtest-setting-row">';
                html += '<span class="gt-backtest-setting-label">' + escapeHTML(meta.label || row.key) + '</span>';
                html += '<span class="gt-backtest-setting-control">';
                if (meta.control_template === 'custom') {
                    html += '<span class="backend-input" style="height:auto;min-height:28px;display:flex;align-items:center;color:#475569;background:#f8fafc;">'
                        + escapeHTML(window.BackendSettingsPanel.displaySettingValue(meta, value))
                        + '</span>';
                } else if ((meta.options || []).length || meta.control_template === 'select') {
                    html += '<select data-ic-setting="' + row.key + '">';
                    (meta.options || []).forEach(option => {
                        html += '<option value="' + escapeHTML(option.value) + '"' + (String(option.value) === String(value) ? ' selected' : '') + '>' + escapeHTML(option.label) + '</option>';
                    });
                    html += '</select>';
                } else {
                    const type = meta.control_template === 'date' || meta.control_template === 'time' || meta.control_template === 'number'
                        ? meta.control_template
                        : 'text';
                    html += '<input data-ic-setting="' + row.key + '" type="' + type + '" value="' + escapeHTML(value == null ? '' : value) + '"'
                        + (meta.step != null ? ' step="' + escapeHTML(meta.step) + '"' : '')
                        + (meta.minimum != null ? ' min="' + escapeHTML(meta.minimum) + '"' : '')
                        + (meta.maximum != null ? ' max="' + escapeHTML(meta.maximum) + '"' : '')
                        + '>';
                }
                html += '</span></label>';
            });
            html += '</div>';
            contentHost.innerHTML = html;
            contentHost.querySelectorAll('[data-ic-setting]').forEach(control => {
                control.addEventListener('change', function() {
                    const key = this.getAttribute('data-ic-setting');
                    const meta = defaults[key] || {};
                    const v = meta.control_template === 'number' ? Number(this.value) : this.value;
                    icSettingValues[key] = v;
                    if (icStore) icStore.set(key, v);  // 通知订阅该字段的 chip 即时回刷
                    if (icProductPathSelections.length) window.renderICTabs(icProductPathSelections);
                    else renderICSettingsPanel(manifest);
                });
            });
        }

        // 分类(Category)管理：列表初始来自数据源(数据库)，可叠加 自定义/现场；
        // 每项可启用/停用（是否用于产品树类别筛选），可选中作为默认 category。
        // 新建分类（提交互不相交的多个路径组、命名、其余归"其他"）是更复杂的流程，
        // 这里先做"列表 + 启停 + 选默认"，新建入口先占位。
        function icCategoryCandidates() {
            return Array.isArray(icSettingValues.category_candidates) ? icSettingValues.category_candidates : [];
        }
        function renderICCategoryTab() {
            var cats = icCategoryCandidates();
            if (!cats.length) {
                contentHost.innerHTML = '<div style="font-size:12px;color:#64748b;padding:8px;">正在加载分类候选...</div>';
                fetch('/api/data_source_categories', { headers: { Accept: 'application/json' } })
                    .then(function(r) { return r.json(); })
                    .then(function(d) {
                        icSettingValues.category_candidates = (d && d.categories) || [];
                        renderICCategoryTab();
                    })
                    .catch(function() { contentHost.innerHTML = '<div style="font-size:12px;color:#b91c1c;">分类加载失败</div>'; });
                return;
            }
            var selectedName = icSettingValues.category || '';
            var html = '<div class="backend-settings-grid">'
                + '<div class="gt-backtest-setting-row"><span class="gt-backtest-setting-label">分类（用于 by_group IC）</span>'
                + '<span class="gt-backtest-setting-control"><span class="gt-backend-chip unified-backend-chip">' + renderChipHtml('候选', String(cats.length)) + '</span></span></div>'
                + '<div style="grid-column:1 / -1;max-height:300px;overflow:auto;border:1px solid #e8eaed;border-radius:6px;">';
            cats.forEach(function(cat, i) {
                var name = cat.name || ('分类' + (i + 1));
                var src = cat.source || '数据库';
                var srcColor = src === '数据库' ? '#1e40af' : (src === '自定义' ? '#7a4b00' : '#92400e');
                var srcBg = src === '数据库' ? '#dbeafe' : (src === '自定义' ? '#fff8e6' : '#fef3c7');
                var enabled = cat.enabled !== false;
                var isDefault = name === selectedName;
                html += '<div class="ic-cat-row" data-cat-idx="' + i + '" style="display:flex;align-items:center;gap:10px;padding:8px 10px;border-bottom:1px solid #f0f2f5;font-size:12px;' + (isDefault ? 'background:#e8f4fd;' : '') + '">'
                    + '<span class="ic-cat-default" data-cat-idx="' + i + '" title="选为默认" style="width:16px;text-align:center;cursor:pointer;color:' + (isDefault ? '#0078d4' : '#ccc') + ';">' + (isDefault ? '●' : '○') + '</span>'
                    + '<span style="flex:1;min-width:0;"><b>' + escapeHTML(name) + '</b>'
                    + ' <span style="display:inline-block;padding:0 5px;border-radius:3px;font-size:10px;font-weight:600;background:' + srcBg + ';color:' + srcColor + ';">' + escapeHTML(src) + '</span>'
                    + ' <span style="color:#94a3b8;">' + escapeHTML((cat.categories || []).join('、')) + '</span>'
                    + (cat.product_paths && cat.product_paths.length ? ' <span style="color:#cbd5e1;">· ' + escapeHTML(cat.product_paths.join(', ')) + '</span>' : '')
                    + '</span>'
                    + '<button type="button" class="ic-cat-toggle" data-cat-idx="' + i + '" style="height:22px;padding:0 9px;border:1px solid ' + (enabled ? '#86efac' : '#cbd5e1') + ';border-radius:4px;background:' + (enabled ? '#f0fdf4' : '#fff') + ';color:' + (enabled ? '#15803d' : '#64748b') + ';font-size:11px;cursor:pointer;">' + (enabled ? '已启用' : '已停用') + '</button>'
                    + '</div>';
            });
            html += '</div>'
                + '<div style="grid-column:1 / -1;margin-top:8px;"><button type="button" id="ic-cat-add" style="height:26px;padding:0 12px;border:1px solid #93c5fd;border-radius:4px;background:#eff6ff;color:#1d4ed8;font-size:12px;cursor:pointer;">+ 新增分类（现场）</button>'
                + '<span style="margin-left:10px;color:#94a3b8;font-size:11px;">新建：提交互不相交的多个路径组并命名，其余产品归"其他"（待实现）</span></div>'
                + '</div>';
            contentHost.innerHTML = html;
            contentHost.querySelectorAll('.ic-cat-default').forEach(function(el) {
                el.addEventListener('click', function() {
                    var c = icCategoryCandidates()[parseInt(el.getAttribute('data-cat-idx'), 10)];
                    icSettingValues.category = c ? (c.name || '') : '';
                    renderICCategoryTab();
                });
            });
            contentHost.querySelectorAll('.ic-cat-toggle').forEach(function(el) {
                el.addEventListener('click', function() {
                    var c = icCategoryCandidates()[parseInt(el.getAttribute('data-cat-idx'), 10)];
                    if (c) c.enabled = c.enabled === false;  // 启停：是否用于产品树类别筛选
                    renderICCategoryTab();
                });
            });
            var addBtn = document.getElementById('ic-cat-add');
            if (addBtn) addBtn.addEventListener('click', function() {
                alert('新建分类（提交互不相交路径组 + 命名 + 其余归"其他"）流程待实现。');
            });
        }

        // IC 因子（多选）：从因子列表多选，直接写 factor_selections（不再经频率抽屉）。
        // 因子管理：照搬"因子家族测试设置"模块的因子管理界面（同一个 FactorParamSelectionUtils
        // 组件），selectionMode='multi'。候选 = factorList（page_factors，与页面/分组测试同源），
        // 可从因子库新增到 page_factors；选择 = factor_selections（IC 的计算输入）。
        function renderICFactorSelectionTab() {
            if (!factorList.length) {
                contentHost.innerHTML = '<div style="font-size:12px;color:#64748b;padding:8px;">正在加载因子...</div>';
                fetchFactorList().then(function() { ensureFactorSelectionsDefault(); renderICFactorSelectionTab(); });
                return;
            }
            ensureFactorSelectionsDefault();
            var utils = window.FactorParamSelectionUtils;
            if (!utils || typeof utils.renderFactorParamSettingsTab !== 'function') {
                contentHost.textContent = '因子参数设置组件未加载';
                return;
            }
            var currentParams = factorList.map(function(f) {
                return { factor_alias: f.alias || f.name || '', scope_key: '', params: {} };
            });
            fetch('/custom-factors/api/factor-library-overview?factor_family_alias=' + encodeURIComponent(factorFamilyAlias))
                .then(function(res) { return res.json(); })
                .catch(function() { return { factors: [] }; })
                .then(function(payload) {
                    var libraryItems = Array.isArray(payload.factors) ? payload.factors : [];
                    var libraryParams = libraryItems.map(function(item) {
                        return utils.factorItemToParamSelection ? utils.factorItemToParamSelection(item) : item;
                    });
                    utils.renderFactorParamSettingsTab({
                        host: contentHost,
                        prefix: 'ic-fps',
                        paramDefs: [],
                        currentFactorParams: currentParams,
                        libraryFactorParams: libraryParams,
                        selectionMode: 'multi',
                        selectedIds: getFactorSelections().map(function(s) { return s.alias; }),
                        onToggle: function(alias) { toggleFactorSelection(alias); renderICFactorSelectionTab(); },
                        manualTitle: '现场新增因子参数',
                        addLabel: '新增到参数列表',
                        escapeHTML: escapeHTML,
                        onAddParam: function(alias, params) {
                            if (!alias || !factorFamilyAlias) return;
                            addFactorByParams(params).then(renderICFactorSelectionTab);
                        },
                        onLoadFromLibrary: function(param) {
                            if (!param || !factorFamilyAlias) return;
                            addFactorByParams(param.params || {}).then(renderICFactorSelectionTab);
                        },
                    });
                });
        }

        // 新增一个因子候选：POST /add_factor_by_params（写入 page_factors），成功后刷新 factorList。
        function addFactorByParams(params) {
            return fetch('/add_factor_by_params', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    factor_family_alias: factorFamilyAlias,
                    params: params || {},
                    page_uuid: window._pageUuid || '',
                }),
            }).then(function(res) { return res.json(); }).then(function(data) {
                if (data && data.success) return fetchFactorList();
                return data;
            }).catch(function(err) {
                console.error('[IC factor-manager] add_factor_by_params failed:', err);
            });
        }

        // IC 收益率频率：从选中的 factor_selections 出发，一行一个因子一个频率输入框，
        // 默认占位 $F（跟随因子频率），用户可填自定义频率（文本框，非下拉）。
        function renderICReturnFreqTab() {
            ensureFactorSelectionsDefault();
            var sel = getFactorSelections();
            var html = '<div class="backend-settings-grid">'
                + '<div class="gt-backtest-setting-row"><span class="gt-backtest-setting-label">收益率频率（每因子）</span>'
                + '<span class="gt-backtest-setting-control" style="font-size:11px;color:#94a3b8;">默认 $F = 跟随因子频率；可填自定义如 1d / 5m</span></div>'
                + '<div style="grid-column:1 / -1;max-height:300px;overflow:auto;border:1px solid #e8eaed;border-radius:6px;">';
            if (!sel.length) {
                html += '<div style="padding:14px;text-align:center;color:#94a3b8;font-size:12px;">未选因子，请先在"因子"tab 选择</div>';
            } else {
                sel.forEach(function(s) {
                    html += '<div style="display:flex;align-items:center;gap:10px;padding:7px 10px;border-bottom:1px solid #f0f2f5;font-size:12px;">'
                        + '<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escapeHTML(s.alias) + '</span>'
                        + '<input type="text" class="ic-freq-input" data-factor-alias="' + escapeHTML(s.alias) + '" value="' + escapeHTML(s.return_freq || '') + '" placeholder="$F" style="width:120px;height:26px;padding:0 8px;border:1px solid #cbd5e1;border-radius:4px;font-size:12px;">'
                        + '</div>';
                });
            }
            html += '</div></div>';
            contentHost.innerHTML = html;
            contentHost.querySelectorAll('.ic-freq-input').forEach(function(inp) {
                inp.addEventListener('input', function() {
                    setFactorReturnFreq(inp.getAttribute('data-factor-alias'), inp.value.trim());
                });
            });
        }

        // IC 产品路径（多选）：复用共享的 renderSelectionSettingsTab（多选模式），
        // 以便统一管理 + 现场新增路径组。每个选中项对应一个结果 tab。
        function renderICProductPathSelectionTab() {
            var s = ensureICStore();
            var selections = (s && s.effective('product_path_candidates')) || [];
            var utils = window.ProductPathSelectionUtils;
            if (!utils || typeof utils.renderSelectionSettingsTab !== 'function') {
                contentHost.textContent = '产品路径设置组件未加载';
                return;
            }
            utils.renderSelectionSettingsTab({
                host: contentHost,
                prefix: 'ic-pps',
                selections: selections,
                multiSelect: true,
                selectedIds: icProductPathSelections.map(selectionId),
                currentLabel: 'IC 产品路径（多选）',
                manualTitle: 'IC 现场新增路径组',
                createLabel: '新增',
                createDefaultLabel: '新增并选中',
                escapeHTML: escapeHTML,
                onToggle: function(selection) {
                    var sid = selectionId(selection);
                    var i = icProductPathSelections.findIndex(function(s) { return selectionId(s) === sid; });
                    if (i >= 0) icProductPathSelections.splice(i, 1);
                    else icProductPathSelections.push(selection);
                    window.renderICTabs(icProductPathSelections.slice());
                },
                onCreate: function(selection) {
                    mergeICProductPathCandidates([selection]);  // 现场新增进候选池
                    icProductPathSelections.push(selection);    // 并默认选中
                    window.renderICTabs(icProductPathSelections.slice());
                },
            });
        }

        function openTab(tabKey) {
            const toggleResult = window.BackendSettingsPanel && typeof window.BackendSettingsPanel.toggleContent === 'function'
                ? window.BackendSettingsPanel.toggleContent({
                    key: tabKey,
                    host: contentHost,
                    getActiveKey: function() { return icActiveSettingsTab; },
                    setActiveKey: function(value) { icActiveSettingsTab = value; },
                    buttonSelector: '#ic-settings-tab-bar [data-ic-settings-tab], #ic-settings-chip-row [data-ic-settings-tab]',
                    buttonKeyAttribute: 'data-ic-settings-tab',
                })
                : { opened: true };
            if (!window.BackendSettingsPanel || typeof window.BackendSettingsPanel.toggleContent !== 'function') {
                if (icActiveSettingsTab === tabKey && contentHost.style.display !== 'none') {
                    icActiveSettingsTab = null;
                    contentHost.style.display = 'none';
                    return;
                }
                icActiveSettingsTab = tabKey;
                contentHost.style.display = '';
            }
            if (!toggleResult.opened) return;
            renderTabContent(tabKey);
        }

        host.querySelectorAll('[data-ic-settings-tab]').forEach(control => {
            control.addEventListener('click', function(event) {
                event.preventDefault();
                openTab(this.getAttribute('data-ic-settings-tab'));
            });
        });

        if (icActiveSettingsTab && tabs.some(tab => tab.key === icActiveSettingsTab)) {
            contentHost.style.display = '';
            renderTabContent(icActiveSettingsTab);
        } else if (icActiveSettingsTab === '__manage__') {
            contentHost.style.display = '';
            renderChooser();
        }
    }

    function drawComparisonChart(containerId, priceData, factorData, returnData, productName, factorName, factorAlias, subId, product) {
        if (typeof Highcharts === 'undefined') return;
        const container = document.getElementById(containerId);
        if (!container) return;

        // 从 containerId 中提取 idx（格式：factor-chart-{subId}-{idx}）
        const parts = containerId.split('-');
        const idx = parts[parts.length - 1];

        const showVolume = document.getElementById(`show-volume-${subId}-${idx}`)?.checked;
        const showOI = document.getElementById(`show-oi-${subId}-${idx}`)?.checked;
        const hasOI = priceData.OPEN_INTEREST && priceData.OPEN_INTEREST.length > 0;
        const volumeOn = showVolume && priceData.VOLUME && priceData.VOLUME.length > 0;
        const oiOn = showOI && hasOI;

        const _parseTs = ts => typeof ts === 'string' ? new Date(ts + 'T00:00:00').getTime() : ts;
        const isDaily = factorData.dates.length > 0 && typeof factorData.dates[0] === 'string';
        const _fmtHeader = isDaily
            ? x => Highcharts.dateFormat('%Y-%m-%d', x)
            : x => Highcharts.dateFormat('%Y-%m-%d %H:%M', x);
        function groupName(group, name) {
            return `[${group}] ${name}`;
        }
        function priceSeriesName() {
            const base = productName || priceData.product || '价格序列';
            if (priceData.is_term_contract) return `${base} 合约价格`;
            return `${base} 价格`;
        }
        const ohlcData     = priceData.dates.map((ts, i) => [_parseTs(ts), priceData.OPEN[i], priceData.HIGH[i], priceData.LOW[i], priceData.CLOSE[i]]);
        const factorValues = factorData.dates.map((ts, i) => [_parseTs(ts), factorData.values[i]]);
        const returnValues = returnData.dates.map((ts, i) => [_parseTs(ts), returnData.values[i]]);
        const contractSeriesList = Array.isArray(priceData.contract_series_list) ? priceData.contract_series_list : [];

        // 动态计算各面板布局（gap=0.5%，总和精确=100%）
        let priceH, factorH, returnH, extraH;
        if (volumeOn && oiOn) {
            // 5联: 48+20+12+9+9 + 4×0.5 = 100
            priceH = 48; factorH = 20; returnH = 12; extraH = 9;
        } else if (volumeOn || oiOn) {
            // 4联: 52+22+14+10 + 3×0.5 = 99.5 ≈ 100
            priceH = 52; factorH = 22; returnH = 14; extraH = 10;
        } else {
            // 3联: 56+24+18 + 2×0.5 = 99
            priceH = 56; factorH = 24; returnH = 18;
        }

        // 构建 yAxis
        let gap = 0.5;
        const yAxis = [
            {
                labels: { format: '{value:.2f}', align: 'right', x: -8 },
                title: { text: '价格' },
                height: priceH + '%',
                resize: { enabled: true }
            },
            {
                labels: { format: '{value:.4f}', align: 'right', x: -8 },
                title: { text: '因子值' },
                top: (priceH + gap) + '%',
                height: factorH + '%',
                opposite: true,
                offset: 0,
            },
            {
                labels: { formatter: function() { return (this.value * 100).toFixed(2) + '%'; }, align: 'right', x: -8 },
                title: { text: '下一期收益率' },
                top: (priceH + factorH + gap * 2) + '%',
                height: returnH + '%',
                opposite: true,
                offset: 0,
            }
        ];

        // 构建 series
        const series = [
            {
                name: groupName('价格', priceSeriesName()),
                type: 'candlestick',
                data: ohlcData,
                yAxis: 0,
                zIndex: 10,
                legendIndex: 10,
                color: '#1F2937',
                lineColor: '#1F2937',
                upColor: '#FFF176',
                upLineColor: '#1F2937',
            },
            {
                name: groupName('指标', '因子值'),
                type: 'line',
                data: factorValues,
                yAxis: 1,
                color: '#FF5722',
                id: 'factor',
                legendIndex: 200,
            },
            {
                name: groupName('指标', '下一期收益率'),
                type: 'line',
                data: returnValues,
                yAxis: 2,
                color: '#4CAF50',
                id: 'return',
                legendIndex: 210,
            }
        ];

        // 同一品种不同期限合约叠加：使用价格查看模块同链路 /api/get_price_data(contract_uid)
        const palette = ['#7E57C2', '#26A69A', '#FF7043', '#5C6BC0', '#EC407A', '#66BB6A'];
        if (contractSeriesList.length > 0) {
            contractSeriesList.forEach(function(s, i) {
                if (!s || !Array.isArray(s.data) || s.data.length === 0) return;
                const fromTs = s.data[0] && s.data[0][0] != null ? s.data[0][0] : null;
                const toTs = s.data[s.data.length - 1] && s.data[s.data.length - 1][0] != null ? s.data[s.data.length - 1][0] : null;
                series.push({
                    name: groupName('期限价格', s.name),
                    type: 'candlestick',
                    data: s.data,
                    yAxis: 0,
                    zIndex: 2,
                    legendIndex: 30 + i,
                    custom: { isContractOverlay: true, rangeFrom: fromTs, rangeTo: toTs },
                    color: palette[i % palette.length],
                    lineWidth: 1,
                    upColor: 'transparent',
                    upLineColor: palette[i % palette.length],
                    lineColor: palette[i % palette.length],
                    fillColor: 'transparent',
                });
            });
        }

        let nextTop = priceH + factorH + returnH + gap * 3;
        let nextIdx = 3;

        if (volumeOn) {
            const volData = priceData.dates.map((ts, i) => [_parseTs(ts), priceData.VOLUME[i]]);
            yAxis.push({
                labels: { format: '{value:.0f}', align: 'right', x: -8 },
                title: { text: '成交量' },
                top: nextTop + '%',
                height: extraH + '%',
                opposite: true,
                offset: 0,
            });
            series.push({
                name: groupName('成交量', productName),
                type: 'column',
                data: volData,
                yAxis: nextIdx,
                color: '#90CAF9',
                id: 'volume',
                legendIndex: 100,
            });
            contractSeriesList.forEach(function(s, i) {
                if (!s || !Array.isArray(s.volume) || s.volume.length === 0) return;
                series.push({
                    name: groupName('成交量', s.name),
                    type: 'column',
                    data: s.volume,
                    yAxis: nextIdx,
                    color: palette[i % palette.length],
                    opacity: 0.35,
                    id: `contract-volume-${i}`,
                    legendIndex: 110 + i,
                });
            });
            nextTop += extraH + gap;
            nextIdx++;
        }

        if (oiOn) {
            const oiData = priceData.dates.map((ts, i) => [_parseTs(ts), priceData.OPEN_INTEREST[i]]);
            yAxis.push({
                labels: { format: '{value:.0f}', align: 'right', x: -8 },
                title: { text: '持仓量' },
                top: nextTop + '%',
                height: extraH + '%',
                opposite: true,
                offset: 0,
            });
            series.push({
                name: groupName('持仓量', productName),
                type: 'line',
                data: oiData,
                yAxis: nextIdx,
                color: '#E91E63',
                id: 'oi',
                legendIndex: 150,
            });
            contractSeriesList.forEach(function(s, i) {
                if (!s || !Array.isArray(s.open_interest) || s.open_interest.length === 0) return;
                series.push({
                    name: groupName('持仓量', s.name),
                    type: 'line',
                    data: s.open_interest,
                    yAxis: nextIdx,
                    color: palette[i % palette.length],
                    dashStyle: 'ShortDot',
                    opacity: 0.8,
                    id: `contract-oi-${i}`,
                    legendIndex: 160 + i,
                });
            });
        }

        const chart = Highcharts.stockChart(container, {
            chart: { zoomType: 'x' },
            title: { text: `${productName} — ${factorName}` },
            legend: {
                enabled: true,
                layout: 'horizontal',
                align: 'center',
                verticalAlign: 'bottom',
                itemDistance: 18,
                maxHeight: 96,
                navigation: { enabled: true },
            },
            plotOptions: {
                series: {
                    point: {
                        events: {
                            click: function() {
                                if (this.series.options.id === 'factor') {
                                    openFactorDistribution(subId, factorName, factorAlias, this.x, product);
                                }
                            }
                        }
                    }
                }
            },
            xAxis: { type: 'datetime' },
            yAxis: yAxis,
            tooltip: {
                split: true,
                formatter: function() {
                    const header = _fmtHeader(this.x);
                    return [header].concat(this.points.map(pt => {
                        if (pt.series.type === 'candlestick') {
                            const p = pt.point;
                            return `${pt.series.name}<br/>开: <b>${p.open.toFixed(2)}</b>  高: <b>${p.high.toFixed(2)}</b><br/>` +
                                   `低: <b>${p.low.toFixed(2)}</b>  收: <b>${p.close.toFixed(2)}</b>`;
                        }
                        if (pt.series.options.id === 'factor') {
                            return `${pt.series.name}: <b>${pt.y.toFixed(4)}</b>`;
                        }
                        if (pt.series.options.id === 'return') {
                            return `${pt.series.name}: <b>${(pt.y * 100).toFixed(2)}%</b>`;
                        }
                        if (String(pt.series.options.id || '').indexOf('volume') >= 0) {
                            return `${pt.series.name}: <b>${pt.y.toFixed(0)}</b>`;
                        }
                        if (String(pt.series.options.id || '').indexOf('oi') >= 0) {
                            return `${pt.series.name}: <b>${pt.y.toFixed(0)}</b>`;
                        }
                        return `${pt.series.name}: <b>${pt.y}</b>`;
                    }));
                }
            },
            series: series,
            navigator: { enabled: true },
            scrollbar: { enabled: true },
            rangeSelector: { enabled: true }
        });
        window._icComparisonChartRefs = window._icComparisonChartRefs || {};
        window._icComparisonChartRefs[`${subId}-${idx}`] = chart;
        bindLegendHoverHighlight(chart, subId, idx);
    }

    function bindLegendHoverHighlight(chart, subId, idx) {
        if (!chart || !Array.isArray(chart.series)) return;
        chart.series.forEach(function(s) {
            const custom = s && s.options ? s.options.custom : null;
            if (!custom || !custom.isContractOverlay) return;
            const legendEl = s.legendItem && s.legendItem.element;
            if (!legendEl || legendEl.__icHoverBound) return;

            legendEl.addEventListener('mouseenter', function() {
                window.icHighlightContractRange(subId, idx, custom.rangeFrom, custom.rangeTo);
            });
            legendEl.addEventListener('mouseleave', function() {
                window.icHighlightContractRange(subId, idx, null, null);
            });
            legendEl.__icHoverBound = true;
        });
    }

    // Volume / OI 复选框切换时重绘对比图（全局函数，供 onchange 调用）
    window.icRedrawComparison = function(subId, idx) {
        const cacheKey = `${subId}-${idx}`;
        const cache = window._icComparisonCache && window._icComparisonCache[cacheKey];
        if (!cache) return;
        const { priceData, factorData, returnData, product, factorName, factorAlias } = cache;
        const chartDiv = document.getElementById(`factor-chart-${subId}-${idx}`);
        if (chartDiv) {
            chartDiv.style.height = '800px';
            drawComparisonChart(`factor-chart-${subId}-${idx}`, priceData, factorData, returnData, product, factorName, factorAlias, subId, product);
        }
    };

    function updateComparisonOptionControls(subId, factorIdx, priceApi, priceData) {
        const supportsAdjusted = !!(priceApi && priceApi.supports_adjusted);
        const adjustWrap = document.getElementById(`adjust-wrap-${subId}-${factorIdx}`);
        if (adjustWrap) adjustWrap.style.display = supportsAdjusted ? 'inline-block' : 'none';
        if (window.PriceDisplay && window.PriceDisplay.setCheckboxVisibility) {
            window.PriceDisplay.setCheckboxVisibility(
                `show-volume-${subId}-${factorIdx}`,
                `show-volume-wrap-${subId}-${factorIdx}`,
                !!(priceData && priceData.has_volume),
                !!(priceData && priceData.has_volume)
            );
            window.PriceDisplay.setCheckboxVisibility(
                `show-oi-${subId}-${factorIdx}`,
                `show-oi-wrap-${subId}-${factorIdx}`,
                !!(priceData && priceData.has_open_interest),
                !!(priceData && priceData.has_open_interest)
            );
        }
    }

    function buildPriceRequestPayload(selectedProduct, submission, adjusted, isTermContractProduct, freq) {
        const body = {
            adjusted: adjusted,
            start_date: submission.start_date,
            end_date: submission.end_date,
            freq: freq || ''
        };
        if (isTermContractProduct) {
            body.contract_uid = selectedProduct;
            body.adjusted = false;
        } else {
            body.product_name = selectedProduct;
        }
        return body;
    }

    // 绘制 Highcharts 图表（保持原有功能）
    function drawChart(containerId, seriesData, seriesName) {
        if (typeof Highcharts === 'undefined') return;
        const container = document.getElementById(containerId);
        if (!container || !seriesData || !seriesData.dates || !seriesData.values) return;
        const isDaily = seriesData.dates.length > 0 && typeof seriesData.dates[0] === 'string';
        const _parseTs = ts => typeof ts === 'string' ? new Date(ts + 'T00:00:00').getTime() : ts;
        const data = seriesData.dates.map((ts, i) => [_parseTs(ts), seriesData.values[i]]);
        Highcharts.stockChart(container, {
            chart: { zoomType: 'x' },
            title: { text: null },
            xAxis: { type: 'datetime', ordinal: true },
            yAxis: { title: { text: seriesName }, crosshair: true },
            tooltip: { shared: true, valueDecimals: 4, xDateFormat: isDaily ? '%Y-%m-%d' : '%Y-%m-%d %H:%M:%S' },
            series: [{ name: seriesName, data: data, type: 'line', dataGrouping: { enabled: false }, marker: { enabled: true, radius: 2 } }],
            navigator: { enabled: true },
            scrollbar: { enabled: true },
            rangeSelector: { enabled: true }
        });
    }

    // 绘制 IC 衰减分析图（多周期 IC mean + IR）
    function drawICDecayChart(containerId, icDecay) {
        if (typeof Highcharts === 'undefined') return;
        const container = document.getElementById(containerId);
        if (!container || !icDecay || !icDecay.length) return;
        const lags = icDecay.map(d => d.lag);
        const means = icDecay.map(d => d.mean);
        const irs = icDecay.map(d => d.ir);
        Highcharts.chart(container, {
            chart: { zoomType: 'x' },
            title: { text: null },
            xAxis: {
                categories: lags.map(l => 'Lag ' + l),
                title: { text: '收益滞后期数' },
                crosshair: true,
            },
            yAxis: [
                { title: { text: 'IC Mean' }, labels: { format: '{value:.4f}' } },
                { title: { text: 'IR' }, opposite: true, labels: { format: '{value:.2f}' } },
            ],
            tooltip: { shared: true },
            plotOptions: {
                column: { pointPadding: 0.1, groupPadding: 0.05, borderWidth: 0 },
            },
            series: [
                {
                    name: 'IC Mean',
                    type: 'column',
                    data: means,
                    yAxis: 0,
                    color: '#0078d4',
                    tooltip: { valueDecimals: 6 },
                },
                {
                    name: 'IR',
                    type: 'spline',
                    data: irs,
                    yAxis: 1,
                    color: '#f44336',
                    marker: { enabled: true, radius: 4 },
                    tooltip: { valueDecimals: 4 },
                },
            ],
            credits: { enabled: false },
        });
    }

    // 绘制滚动窗口 IC 图
    function drawRollingICChart(containerId, rollingIc) {
        if (typeof Highcharts === 'undefined') return;
        const container = document.getElementById(containerId);
        if (!container || !rollingIc || !rollingIc.dates || !rollingIc.dates.length) return;
        const isDaily = rollingIc.dates.length > 0 && typeof rollingIc.dates[0] === 'string';
        const _parseTs = ts => typeof ts === 'string' ? new Date(ts + 'T00:00:00').getTime() : ts;
        const meanData = rollingIc.dates.map((ts, i) => [_parseTs(ts), rollingIc.mean[i]]);
        const irData = rollingIc.dates.map((ts, i) => [_parseTs(ts), rollingIc.ir[i]]);
        Highcharts.stockChart(container, {
            chart: { zoomType: 'x' },
            title: { text: null },
            xAxis: { type: 'datetime' },
            yAxis: [
                { title: { text: 'IC Mean' }, labels: { format: '{value:.4f}' }, crosshair: true },
                { title: { text: 'IR' }, opposite: true, labels: { format: '{value:.2f}' } },
            ],
            tooltip: {
                shared: true,
                valueDecimals: 6,
                xDateFormat: isDaily ? '%Y-%m-%d' : '%Y-%m-%d %H:%M:%S',
            },
            series: [
                { name: 'IC Mean', type: 'line', data: meanData, yAxis: 0, color: '#0078d4', tooltip: { valueDecimals: 6 } },
                { name: 'IR', type: 'line', data: irData, yAxis: 1, color: '#f44336', dashStyle: 'Dash', tooltip: { valueDecimals: 4 } },
            ],
            navigator: { enabled: true },
            scrollbar: { enabled: true },
            rangeSelector: { enabled: true },
            credits: { enabled: false },
        });
    }

    // 绘制自相关衰减柱状图
    function drawAutocorrChart(containerId, autocorr) {
        if (typeof Highcharts === 'undefined') return;
        const container = document.getElementById(containerId);
        if (!container || !autocorr || !autocorr.length) return;
        const lags = autocorr.map(d => 'Lag ' + d.lag);
        const acValues = autocorr.map(d => d.ac);
        // 找半衰期点
        let hlAnnotation = null;
        for (let i = 0; i < autocorr.length; i++) {
            if (autocorr[i].ac < 0.5) {
                const prev = i > 0 ? autocorr[i-1].ac : 1.0;
                const curr = autocorr[i].ac;
                const frac = (0.5 - prev) / (curr - prev);
                hlAnnotation = i - 1 + frac;
                break;
            }
        }

        Highcharts.chart(container, {
            chart: { type: 'column', zoomType: 'x' },
            title: { text: null },
            xAxis: {
                categories: lags,
                title: { text: '滞后期数' },
                crosshair: true,
            },
            yAxis: {
                title: { text: '自相关系数' },
                min: -0.2,
                max: 1.0,
                plotLines: [{
                    value: 0.5,
                    color: '#f44336',
                    dashStyle: 'dash',
                    width: 1,
                    label: { text: '半衰线 0.5', style: { color: '#f44336', fontSize: '10px' } },
                    zIndex: 5,
                }],
            },
            tooltip: {
                pointFormat: '<b>{point.category}</b>: {point.y:.4f}',
            },
            plotOptions: {
                column: {
                    pointPadding: 0.05,
                    groupPadding: 0,
                    borderWidth: 0,
                    color: '#0078d4',
                    negativeColor: '#f44336',
                },
            },
            series: [{
                name: '自相关',
                data: acValues,
                showInLegend: false,
            }],
            credits: { enabled: false },
        });
    }

    // 统计量最优方向：越大越好=1，越小越好=-1（key 对应后端 ic_stats 返回的 index）
    var IC_METRIC_DIRECTION = {
        'mean': 1,
        'std': -1,
        'IR': 1,
        't_stat': 1,
        'max': 1,
        'min': -1,
        'ac1': 1,
        'half_life': -1
    };

    // index → 显示名映射
    var IC_METRIC_LABELS = {
        'mean': 'IC Mean',
        'std': 'IC Std',
        'IR': 'IR',
        't_stat': 't-stat',
        'max': 'IC Max',
        'min': 'IC Min',
        'ac1': 'IC AC1',
        'half_life': 'Half-Life'
    };

    function _getBestValIdx(values, metricName) {
        var dir = IC_METRIC_DIRECTION[metricName] || 0;
        if (dir === 0) return null;
        var bestIdx = null;
        var bestVal = null;
        for (var i = 0; i < values.length; i++) {
            var v = values[i];
            if (v === null || v === undefined || v === '' || (typeof v === 'number' && isNaN(v))) continue;
            if (metricName === 'half_life' && !isFinite(v)) continue;
            var num = typeof v === 'number' ? v : parseFloat(v);
            if (isNaN(num)) continue;
            if (bestIdx === null || (dir > 0 ? num > bestVal : num < bestVal)) {
                bestIdx = i;
                bestVal = num;
            }
        }
        return bestIdx;
    }

    // 构建统计表格 HTML（含最优值高亮 + 活跃因子表头标注）
    function buildPrettyTable(data, subId) {
        if (!data || !data.ic_stats || !data.ic_stats.columns || !data.ic_stats.rows || !data.ic_stats.columns.length) {
            return '<div class="ic-empty">无可展示结果</div>';
        }
        // 默认激活第一个因子
        if (subId) {
            window._icActiveFactorIdx = window._icActiveFactorIdx || {};
            if (window._icActiveFactorIdx[subId] === undefined || window._icActiveFactorIdx[subId] >= (data.ic_stats.columns.length - 1)) {
                window._icActiveFactorIdx[subId] = 0;
            }
        }
        var activeIdx = subId ? (window._icActiveFactorIdx[subId] || 0) : 0;
        var html = '<div class="ic-table-wrap" style="margin-bottom:16px;"><table class="ic-table"><thead><tr>';
        data.ic_stats.columns.forEach(function(col, i) {
            var isIdx = i === 0;
            var isActive = !isIdx && (i - 1 === activeIdx);
            var draggable = !isIdx ? ' draggable="true"' : '';
            var dataColIdx = !isIdx ? ' data-col-idx="' + (i - 1) + '"' : '';
            var activeClass = isActive ? ' ic-active-factor' : '';
            var label = isIdx ? '统计量' : col;
            html += '<th class="' + (isIdx ? 'idx-col' : 'draggable-col') + activeClass + '"' + draggable + dataColIdx + '>' + label + '</th>';
        });
        html += '</tr></thead><tbody>';
        data.ic_stats.rows.forEach(function(row) {
            // 找该行最优值列（不含 index 列）
            var factorCols = data.ic_stats.columns.slice(1);
            var factorVals = factorCols.map(function(c) { return row[c]; });
            var metricName = row['index'] || '';
            var bestColIdx = _getBestValIdx(factorVals, metricName);
            html += '<tr>';
            data.ic_stats.columns.forEach(function(col, i) {
                var val = row[col];
                var display;
                if (i === 0) {
                    // 第一列是统计量名，使用可读标签
                    display = IC_METRIC_LABELS[val] || String(val);
                } else if (val === null || val === undefined || val === '') {
                    display = '—';
                } else if (metricName === 'half_life' && !isFinite(val)) {
                    display = '∞';
                } else if (typeof val === 'number') {
                    display = Number.isInteger(val) ? val : val.toFixed(6);
                } else {
                    display = String(val);
                }
                var cellClass = '';
                if (i === 0) {
                    cellClass = 'idx-col';
                } else if (bestColIdx !== null && (i - 1) === bestColIdx) {
                    cellClass = 'ic-best-cell';
                }
                html += '<td class="' + cellClass + '">' + display + '</td>';
            });
            html += '</tr>';
        });
        html += '</tbody></table></div>';
        return html;
    }

    // 切换到指定因子（点击表头触发）
    function switchActiveFactor(subId, colIdx, factors) {
        factors = factors || (window._icDataFactors && window._icDataFactors[subId]);
        window._icActiveFactorIdx = window._icActiveFactorIdx || {};
        window._icActiveFactorIdx[subId] = colIdx;
        // 更新表头高亮
        var table = document.querySelector('#ic-result-' + subId + ' .ic-table');
        if (table) {
            table.querySelectorAll('thead th.draggable-col').forEach(function(th, i) {
                if (i === colIdx) {
                    th.classList.add('ic-active-factor');
                } else {
                    th.classList.remove('ic-active-factor');
                }
            });
        }
        // 重新渲染因子面板
        if (factors && factors.length > colIdx) {
            renderFactorPanel(subId, factors[colIdx], colIdx, factors);
        }
    }
    window.switchActiveFactor = switchActiveFactor;

    // 本地重排表格列和因子面板（不重新请求后端数据）
    // fromIdx/toIdx 是相对于因子列（不含 index 列）的索引
    function reorderTableColumns(table, fromIdx, toIdx, subId) {
        // ── 1. 重排表格列 ──
        var rows = table.querySelectorAll('tr');
        rows.forEach(function(row) {
            var cells = Array.from(row.children);
            // cells[0] = index 列，cells[1..] = 因子列
            var factorCells = cells.slice(1);
            var moved = factorCells.splice(fromIdx, 1)[0];
            factorCells.splice(toIdx, 0, moved);
            // 更新 data-col-idx
            factorCells.forEach(function(cell, i) {
                cell.setAttribute('data-col-idx', i);
            });
            // 清空并重新插入
            while (row.children.length > 1) row.removeChild(row.lastChild);
            factorCells.forEach(function(cell) { return row.appendChild(cell); });
        });

        // ── 2. 更新活跃因子索引 ──
        window._icActiveFactorIdx = window._icActiveFactorIdx || {};
        var cur = window._icActiveFactorIdx[subId];
        if (cur === fromIdx) {
            window._icActiveFactorIdx[subId] = toIdx;
        } else if (fromIdx < toIdx) {
            if (cur > fromIdx && cur <= toIdx) window._icActiveFactorIdx[subId] = cur - 1;
        } else {
            if (cur >= toIdx && cur < fromIdx) window._icActiveFactorIdx[subId] = cur + 1;
        }

        // ── 3. 重新应用表头高亮 ──
        var activeIdx = window._icActiveFactorIdx[subId];
        table.querySelectorAll('thead th.draggable-col').forEach(function(th, i) {
            if (i === activeIdx) {
                th.classList.add('ic-active-factor');
            } else {
                th.classList.remove('ic-active-factor');
            }
        });
    }

    // 渲染单个因子的详情面板（无选项卡，由表头点击切换）
    function renderFactorPanel(subId, factor, idx, allFactors) {
        var containerId = 'ic-factor-panel-' + subId;
        var container = document.getElementById(containerId);
        if (!container) {
            var resultDiv = document.getElementById('ic-result-' + subId);
            if (!resultDiv) return;
            var existing = document.getElementById(containerId);
            if (existing) existing.remove();
            container = document.createElement('div');
            container.id = containerId;
            container.className = 'ic-factor-panel';
            resultDiv.appendChild(container);
        }
        if (!factor) {
            container.innerHTML = '<div class="ic-empty">暂无因子数据</div>';
            return;
        }
        var productOptions = (factor.products && factor.products.length)
            ? factor.products.map(function(p) { return '<option value="' + p.name + '" data-is-term-contract="' + (p.is_term_contract ? '1' : '0') + '">' + p.name + (p.desc && p.desc !== p.name ? ' · ' + p.desc : '') + '</option>'; }).join('')
            : '<option value="">无可用产品</option>';
        var icDecayHtml = '';
        var rollingIcHtml = '';
        if (factor.ic_decay && factor.ic_decay.length > 0) {
            icDecayHtml = '<div class="ic-result-section" data-result-section="ic_decay" style="margin-top:20px;"><h6>IC 衰减分析（多周期）</h6><div id="ic-decay-chart-' + subId + '-' + idx + '" style="width:100%; height:300px;"></div></div>';
        } else {
            icDecayHtml = '<div class="ic-result-section" data-result-section="ic_decay" style="margin-top:20px;color:#94a3b8;font-size:13px;">暂无 IC 衰减数据（运行前在设置中配置 ic_decay_lags）</div>';
        }
        if (factor.rolling_ic && factor.rolling_ic.dates && factor.rolling_ic.dates.length > 0) {
            rollingIcHtml = '<div class="ic-result-section" data-result-section="rolling_ic" style="margin-top:20px;"><h6>滚动窗口 IC（窗口=' + factor.rolling_ic.window + '）</h6><div id="ic-rolling-chart-' + subId + '-' + idx + '" style="width:100%; height:350px;"></div></div>';
        } else {
            rollingIcHtml = '<div class="ic-result-section" data-result-section="rolling_ic" style="margin-top:20px;color:#94a3b8;font-size:13px;">暂无滚动 IC 数据（运行前在设置中配置 rolling_window）</div>';
        }
        // 未实现的结果分析：显式占位而非隐藏。
        function _notImplemented(key, label) {
            return '<div class="ic-result-section" data-result-section="' + key + '" style="margin-top:20px;padding:24px;text-align:center;color:#94a3b8;border:1px dashed #d8dee4;border-radius:8px;background:#fafcff;font-size:13px;">🚧 ' + label + '：未实现</div>';
        }
        container.innerHTML = ''
            + '<!-- 因子切换导航条 -->'
            + '<div class="ic-factor-nav" style="display:flex;align-items:center;gap:12px;margin-bottom:12px;padding:10px 14px;background:#f0f5ff;border-radius:8px;border:1px solid #d0ddf0;">'
            + '<span style="font-weight:700;color:#0f4c81;font-size:14px;">📊 ' + (factor.alias || factor.name) + '</span>'
            + '<span style="font-size:12px;color:#888;">点击统计表表头切换因子</span>'
            + (allFactors && allFactors.length > 1 ? '<span style="font-size:12px;color:#666;">（共' + allFactors.length + '个因子，当前第' + (idx + 1) + '个）</span>' : '')
            + '</div>'
            // IC 序列图 & 自相关衰减图（rank/pearson 主视图）
            + '<div class="ic-result-section" data-result-section="cross_sectional_rank_ic cross_sectional_pearson_ic ic_summary" style="display:flex; flex-wrap:wrap; gap:20px; margin-top:16px;">'
            + '<div style="flex:1;min-width:45%;"><h6>IC 序列</h6><div id="ic-chart-' + subId + '-' + idx + '" style="width:100%; height:350px;"></div></div>'
            + '<div style="flex:1;min-width:45%;"><h6>IC 自相关衰减</h6><div id="ic-acf-chart-' + subId + '-' + idx + '" style="width:100%; height:350px;"></div></div>'
            + '</div>'
            + icDecayHtml
            + rollingIcHtml
            + _notImplemented('by_group_ic', '分组 IC（by_group）')
            + _notImplemented('coverage_missing', 'Coverage / Missing 覆盖率')
            + '<div style="margin-top:14px;padding:10px 12px;border:1px dashed #d8dee4;border-radius:8px;color:#64748b;font-size:12px;background:#fafcff;">产品级因子值、价格、收益标签和合约/期限对比已拆到上方“因子序列查看”模块。</div>';

        // 绘制 IC 图表
        if (factor.ic_series && factor.ic_series.dates && factor.ic_series.values) {
            drawChart('ic-chart-' + subId + '-' + idx, factor.ic_series, 'IC');
        }
        if (factor.autocorr && factor.autocorr.length > 0) {
            drawAutocorrChart('ic-acf-chart-' + subId + '-' + idx, factor.autocorr);
        }
        if (factor.ic_decay && factor.ic_decay.length > 0) {
            drawICDecayChart('ic-decay-chart-' + subId + '-' + idx, factor.ic_decay);
        }
        if (factor.rolling_ic && factor.rolling_ic.dates && factor.rolling_ic.dates.length > 0) {
            drawRollingICChart('ic-rolling-chart-' + subId + '-' + idx, factor.rolling_ic);
        }

        // 应用当前选中的结果分析 tab（默认第一个），只显示对应 section
        var resultBar = document.querySelector('.ic-result-tabs[data-product-path-selection-id="' + subId + '"]');
        if (resultBar) {
            var activeBtn = resultBar.querySelector('.ic-result-tab-btn.active') || resultBar.querySelector('.ic-result-tab-btn');
            if (activeBtn) applyICResultTabFilter(subId, activeBtn.getAttribute('data-result-tab'));
        }
    }

    // 加载因子值和收益率并绘图
    async function loadFactorAndReturn(subId, factorIdx, factorName, factorAlias) {
        const primarySelect = document.getElementById(`primary-product-select-${subId}-${factorIdx}`);
        const testerPrimary = primarySelect ? primarySelect.value : '';
        const selectedOption = primarySelect ? primarySelect.options[primarySelect.selectedIndex] : null;
        const isTermContractProduct = selectedOption ? selectedOption.getAttribute('data-is-term-contract') === '1' : false;
        const product = testerPrimary || null;
        if (!product || product === '') { alert('请选择一个产品'); return; }

        const factorChartDiv = document.getElementById(`factor-chart-${subId}-${factorIdx}`);
        if (!factorChartDiv) return;
        factorChartDiv.style.height = 'auto';
        factorChartDiv.innerHTML = '<div style="color:#888; text-align:center; padding:18px 0;">加载价格与因子值...</div>';

        const selection = selectionById(subId);
        if (!selection) {
            factorChartDiv.innerHTML = '<div style="color:#d00; text-align:center;">未找到产品路径选择</div>';
            return; 
        }

        const factorInfo = factorList.find(f => f.alias === factorAlias) || factorList.find(f => f.name === factorName);
        const freq = (factorInfo && factorInfo.freq !== 'N') ? factorInfo.freq : '1D';

        const _safeJson = async (r, label) => {
                const text = await r.text();
                try { return JSON.parse(text); }
                catch (e) { throw new Error(`${label} 返回非JSON (HTTP ${r.status}): ${text.slice(0, 300)}`); }
            };
        try {
            const [factorData, returnData] = await Promise.all([
                fetch('/get_factor_series', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        product_path_selection_id: selectionId(selection),
                        product_path_selection: selection,
                        factor_family_alias: factorFamilyAlias,
                        factor_name: factorName,
                        factor_alias: factorAlias,
                        product: testerPrimary || product,
                        page_uuid: window._pageUuid || ''
                    })
                }).then(r => _safeJson(r, 'get_factor_series')),
                fetch('/get_return_series', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        product_path_selection_id: selectionId(selection),
                        product_path_selection: selection,
                        factor_name: factorName,
                        factor_alias: factorAlias,
                        factor_family_alias: factorFamilyAlias,
                        product: testerPrimary || product,
                        paths: selection.paths || selection.selected_paths || [],
                        page_uuid: window._pageUuid || ''
                    })
                }).then(r => _safeJson(r, 'get_return_series'))
            ]);
            if (factorData.error) {
                var factorErr = 'get_factor_series 错误: ' + factorData.error;
                if (factorData.traceback) {
                    factorChartDiv.innerHTML = '<div style="color:#d00; text-align:left;">' + factorErr + '</div>' +
                        `<pre style="background:#fff3f3;border:1px solid #f99;padding:10px;font-size:11px;overflow:auto;white-space:pre-wrap;margin-top:8px;">${factorData.traceback.replace(/</g,'&lt;')}</pre>`;
                    return;
                }
                throw new Error(factorErr);
            }
            if (returnData.error) {
                var returnErr = 'get_return_series 错误: ' + returnData.error;
                if (returnData.traceback) {
                    factorChartDiv.innerHTML = '<div style="color:#d00; text-align:left;">' + returnErr + '</div>' +
                        `<pre style="background:#fff3f3;border:1px solid #f99;padding:10px;font-size:11px;overflow:auto;white-space:pre-wrap;margin-top:8px;">${returnData.traceback.replace(/</g,'&lt;')}</pre>`;
                    return;
                }
                throw new Error(returnErr);
            }

            const adjustCheckbox = document.getElementById(`adjust-price-${subId}-${factorIdx}`);
            const adjusted = adjustCheckbox ? adjustCheckbox.checked : false;

            // 主价格序列改为复用价格查看模块链路，保证连续性
            const priceApi = await fetch('/api/get_price_data', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(buildPriceRequestPayload(testerPrimary || product, selection, adjusted, isTermContractProduct, freq))
            }).then(r => r.json());

            const priceData = priceApiToSeries(priceApi);

            if (priceData.error) {
                var priceErr = 'get_price_data 错误: ' + priceData.error;
                if (priceApi.traceback) {
                    factorChartDiv.innerHTML = '<div style="color:#d00; text-align:left;">' + priceErr + '</div>' +
                        `<pre style="background:#fff3f3;border:1px solid #f99;padding:10px;font-size:11px;overflow:auto;white-space:pre-wrap;margin-top:8px;">${priceApi.traceback.replace(/</g,'&lt;')}</pre>`;
                    return;
                }
                throw new Error(priceErr);
            }
            updateComparisonOptionControls(subId, factorIdx, priceApi, priceData);

            if (priceData.dates && priceData.OPEN && factorData.dates && factorData.values && returnData.dates && returnData.values) {
                // 拉取“同一产品不同期限合约”叠加线（接口链路复用 price_viewer）
                const key = `${subId}-${factorIdx}`;
                const selectedContractUids = Array.from(icContractSelection[key] || []);
                const contractSeriesList = adjusted
                    ? []
                    : await fetchContractSeriesForOverlay(selectedContractUids, selection, adjusted);
                priceData.contract_series_list = contractSeriesList;

                // 缓存数据以便 Volume/OI 复选框切换时重绘
                const cacheKey = `${subId}-${factorIdx}`;
                window._icComparisonCache = window._icComparisonCache || {};
                window._icComparisonCache[cacheKey] = { priceData, factorData, returnData, product, factorName, factorAlias };
                factorChartDiv.style.height = '800px';
                drawComparisonChart(`factor-chart-${subId}-${factorIdx}`, priceData, factorData, returnData, product, factorName, factorAlias, subId, product);
            } else {
                factorChartDiv.innerHTML = '<div style="color:#d00; text-align:center;">价格、因子或收益率数据无效</div>';
            }
        } catch (err) {
            console.error('加载错误:', err);
            factorChartDiv.innerHTML = `<div style="color:#d00; text-align:center;">请求失败: ${err.message}</div>`;
        }
    }

    async function populateContractTable(subId, factorIdx, productName) {
        const wrap = document.getElementById(`contract-table-wrap-${subId}-${factorIdx}`);
        const tbody = document.getElementById(`contract-table-body-${subId}-${factorIdx}`);
        const adjustWrap = document.getElementById(`adjust-wrap-${subId}-${factorIdx}`);
        const adjustCheckbox = document.getElementById(`adjust-price-${subId}-${factorIdx}`);
        if (!wrap || !tbody) return;
        tbody.innerHTML = '';
        wrap.style.display = 'none';
        if (adjustWrap) adjustWrap.style.display = 'none';
        if (adjustCheckbox) adjustCheckbox.checked = false;
        if (!productName) return;
        const key = `${subId}-${factorIdx}`;
        icContractSelection[key] = new Set();
        try {
            const selection = selectionById(subId);
            const primarySelect = document.getElementById(`primary-product-select-${subId}-${factorIdx}`);
            const selectedOption = primarySelect ? primarySelect.options[primarySelect.selectedIndex] : null;
            const isTermContractProduct = selectedOption ? selectedOption.getAttribute('data-is-term-contract') === '1' : false;
            if (isTermContractProduct) return;
            const q = new URLSearchParams({ product: productName });
            if (selection && selection.start_date) q.set('start_date', selection.start_date);
            if (selection && selection.end_date) q.set('end_date', selection.end_date);
            const resp = await fetch('/api/get_contracts?' + q.toString());
            const data = await resp.json();
            if (!data.success || !Array.isArray(data.contracts)) return;
            wrap.style.display = data.contracts.length > 0 ? 'block' : 'none';
            data.contracts.forEach(function(c, idx) {
                const tr = document.createElement('tr');
                tr.style.cursor = 'pointer';
                tr.innerHTML =
                    '<td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;">' + c.contract + '</td>' +
                    '<td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;">' + (c.start || '') + '</td>' +
                    '<td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;">' + (c.end || '') + '</td>';
                if (idx < 3) {
                    icContractSelection[key].add(c.uid);
                    tr.style.background = 'rgba(255,165,0,0.15)';
                }
                tr.addEventListener('mouseenter', function() {
                    window.icHighlightContractRange(subId, factorIdx, c.start_ts, c.end_ts);
                });
                tr.addEventListener('mouseleave', function() {
                    window.icHighlightContractRange(subId, factorIdx, null, null);
                });
                tr.addEventListener('click', function() {
                    if (icContractSelection[key].has(c.uid)) {
                        icContractSelection[key].delete(c.uid);
                        tr.style.background = '';
                    } else {
                        icContractSelection[key].add(c.uid);
                        tr.style.background = 'rgba(255,165,0,0.15)';
                    }
                });
                tbody.appendChild(tr);
            });
        } catch (e) {
            console.warn('加载期限合约失败:', e);
        }
    }

    async function fetchContractSeriesForOverlay(contractUids, submission, adjusted) {
        const list = [];
        if (!Array.isArray(contractUids) || contractUids.length === 0) return list;
        const startMs = submission && submission.start_date ? new Date(submission.start_date + 'T00:00:00').getTime() : null;
        const endMs = submission && submission.end_date ? new Date(submission.end_date + 'T23:59:59').getTime() : null;
        const reqs = contractUids.map(async function(uid) {
            const res = await fetch('/api/get_price_data', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    contract_uid: uid,
                    adjusted: false,
                    start_date: submission.start_date,
                    end_date: submission.end_date,
                })
            }).then(r => r.json());
            const overlay = window.PriceDisplay && window.PriceDisplay.contractOverlayFromApi
                ? window.PriceDisplay.contractOverlayFromApi(res)
                : null;
            if (!overlay) return null;
            const keepRange = function(point) {
                const ts = point && point[0];
                if (ts == null) return false;
                if (startMs != null && ts < startMs) return false;
                if (endMs != null && ts > endMs) return false;
                return true;
            };
            overlay.data = overlay.data.filter(keepRange);
            overlay.volume = (overlay.volume || []).filter(keepRange);
            overlay.open_interest = (overlay.open_interest || []).filter(keepRange);
            if (overlay.data.length === 0) return null;
            return overlay;
        });
        const got = await Promise.all(reqs);
        got.forEach(function(x) { if (x) list.push(x); });
        return list;
    }

    function priceApiToSeries(apiData) {
        if (window.PriceDisplay && window.PriceDisplay.normalizePriceApi) {
            return window.PriceDisplay.normalizePriceApi(apiData);
        }
        if (!apiData || !apiData.success || !Array.isArray(apiData.data) || apiData.data.length === 0) {
            return { error: (apiData && apiData.error) || '无价格数据' };
        }
        const data = apiData.data.slice().sort(function(a, b) { return (a.timestamp || 0) - (b.timestamp || 0); });
        const series = {
            product: apiData.product || '',
            desc: apiData.desc || '',
            contract_uid: apiData.contract_uid || '',
            contract_name: apiData.contract_name || '',
            is_term_contract: !!apiData.is_term_contract || !!apiData.contract_uid,
            supports_term_structure: !!apiData.supports_term_structure,
            dates: data.map(d => d.timestamp),
            OPEN: data.map(d => d.open),
            HIGH: data.map(d => d.high),
            LOW: data.map(d => d.low),
            CLOSE: data.map(d => d.close),
            VOLUME: data.map(d => d.volume == null ? null : d.volume),
            OPEN_INTEREST: data.map(d => d.open_interest == null ? null : d.open_interest),
        };
        series.has_volume = series.VOLUME.some(v => v != null);
        series.has_open_interest = !!apiData.has_oi && series.OPEN_INTEREST.some(v => v != null);
        return series;
    }

    window.icHighlightContractRange = function(subId, idx, fromTs, toTs) {
        const key = `${subId}-${idx}`;
        const chart = window._icComparisonChartRefs && window._icComparisonChartRefs[key];
        if (!chart || !chart.xAxis || !chart.xAxis[0]) return;
        const axis = chart.xAxis[0];
        axis.removePlotBand('ic-contract-hover-band');
        if (fromTs == null || toTs == null) {
            delete icHoverBandState[key];
            return;
        }
        icHoverBandState[key] = { from: fromTs, to: toTs };
        axis.addPlotBand({
            id: 'ic-contract-hover-band',
            from: fromTs,
            to: toTs,
            color: 'rgba(100,149,237,0.12)',
            zIndex: 3,
        });
    };

    // 运行 IC 测试
    window.runIC = async function(subId) {
        const btn = document.getElementById(`run-ic-btn-${subId}`);
        const statusSpan = document.getElementById(`ic-status-${subId}`);
        const resultDiv = document.getElementById(`ic-result-${subId}`);
        if (!btn || !statusSpan || !resultDiv) return;

        // 收集选中的因子及频率（factor_selections，与快照/抽屉同一来源）
        const selectedFactors = collectFactorSelections();
        if (selectedFactors.length === 0) {
            statusSpan.innerText = '请至少选择一个因子';
            statusSpan.style.color = '#d40000';
            return;
        }
        const selection = selectionById(subId);
        if (!selection) {
            statusSpan.innerText = '错误：未找到产品路径选择';
            btn.disabled = false;
            return;
        }
        btn.disabled = true;
        statusSpan.innerText = 'IC测试运行中...';
        statusSpan.style.color = '#0078d4';
        resultDiv.innerHTML = '';

        // 读取 IC 衰减和滚动窗口参数
        let ic_decay_lags = null;
        let rolling_window = null;
        const decaySetting = icSettingValues.ic_decay_lags;
        const rollingSetting = icSettingValues.rolling_window;
        if (decaySetting != null && String(decaySetting).trim()) {
            const parts = String(decaySetting).trim().split(',').map(s => parseInt(s.trim(), 10)).filter(n => !isNaN(n) && n > 0);
            if (parts.length > 0) ic_decay_lags = parts;
        }
        if (rollingSetting != null && String(rollingSetting).trim()) {
            const w = parseInt(String(rollingSetting).trim(), 10);
            if (!isNaN(w) && w > 1) rolling_window = w;
        }

        try {
            // 显示进度条
            const progressBarId = `ic-progress-${subId}`;
            let progressDiv = document.getElementById(progressBarId);
            if (!progressDiv) {
                progressDiv = document.createElement('div');
                progressDiv.id = progressBarId;
                progressDiv.className = 'ic-progress-container';
                progressDiv.innerHTML = `
                    <div class="ic-progress-bar-bg">
                        <div class="ic-progress-bar-fill" id="${progressBarId}-fill"></div>
                    </div>
                    <span class="ic-progress-text" id="${progressBarId}-text">0/0</span>
                `;
                resultDiv.parentNode.insertBefore(progressDiv, resultDiv);
            }
            const progressUi = createIcProgressController(progressBarId);
            // 单根进度条只由节点级 eval 进度（累计、单调）驱动；组完成只作文字标注，
            // 避免节点/组两套分母互相竞态。
            let nodeCompleted = 0, nodeTotal = 0, groupDone = 0, groupTotal = 0;
            const renderICProgress = () => {
                const pct = nodeTotal > 0 ? (nodeCompleted / nodeTotal * 100) : 0;
                const parts = [];
                if (nodeTotal > 0) parts.push(nodeCompleted + '/' + nodeTotal + ' 节点');
                if (groupTotal > 0) parts.push('第 ' + groupDone + '/' + groupTotal + ' 组');
                progressUi.set(pct, parts.join(' · ') || '准备中…');
            };

            const body = JSON.stringify({
                product_path_selection_id: selectionId(selection),
                product_path_selection: selection,
                factor_family_alias: factorFamilyAlias,
                paths: selection.paths || selection.selected_paths || [],
                factors: selectedFactors,
                ic_decay_lags: ic_decay_lags,
                rolling_window: rolling_window,
                ic_lag: icSettingValues.ic_lag,
                ic_correlation: icSettingValues.ic_correlation,
                return_frequency_mode: icSettingValues.return_frequency_mode,
                return_price_basis: icSettingValues.return_price_basis,
                settings: icSettingValues,
                page_uuid: window._pageUuid || ''
            });

            const sseResponse = await fetch('/run_ic_test_stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: body
            });

            if (!sseResponse.ok) {
                btn.disabled = false;
                statusSpan.innerText = '✗ IC测试失败: HTTP ' + sseResponse.status;
                statusSpan.style.color = '#d40000';
                return;
            }

            const reader = sseResponse.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let lastEvent = '';
            let data = null;

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop(); // 保留未完成的行

                for (const line of lines) {
                    if (line.startsWith('event: ')) {
                        lastEvent = line.slice(7).trim();
                    } else if (line.startsWith('data: ')) {
                        try {
                            const payload = JSON.parse(line.slice(6));
                            if (lastEvent === 'start') {
                                nodeTotal = payload.total || 0;
                                groupTotal = payload.groups || 0;
                                nodeCompleted = 0; groupDone = 0;
                                renderICProgress();
                            } else if (lastEvent === 'progress') {
                                const phase = payload.phase || '';
                                if (phase === 'eval') {
                                    nodeCompleted = payload.completed; nodeTotal = payload.total;
                                } else {
                                    // group_done 等：只更新组计数文字，不改进度分数
                                    groupDone = payload.completed; groupTotal = payload.total;
                                }
                                renderICProgress();
                            } else if (lastEvent === 'result') {
                                data = payload;
                            } else if (lastEvent === 'error') {
                                data = payload;
                            }
                        } catch (e) {
                            // skip malformed JSON
                        }
                    }
                }
            }

            // 清理进度条
            if (progressDiv) progressDiv.remove();

            btn.disabled = false;
            if (!data || !data.success) {
                statusSpan.innerText = '✗ IC测试失败: ' + (data?.error || '未知错误');
                statusSpan.style.color = '#d40000';
                if (data?.traceback) {
                    resultDiv.innerHTML = `<pre style="background:#fff3f3;border:1px solid #f99;padding:10px;font-size:12px;overflow:auto;white-space:pre-wrap;">${data.traceback.replace(/</g,'&lt;')}</pre>`;
                }
                return;
            }
            statusSpan.innerText = '✓ IC测试完成' + (data.paths_hash ? (' (路径哈希: ' + data.paths_hash + ')') : '');
            statusSpan.style.color = '#28a745';
            resultDiv.innerHTML = buildPrettyTable(data, subId);
            // 缓存因子数据供 switchActiveFactor / reorder 使用
            window._icDataFactors = window._icDataFactors || {};
            window._icDataFactors[subId] = data.factors;
            // 设置活跃因子索引（默认第一个）
            window._icActiveFactorIdx = window._icActiveFactorIdx || {};
            window._icActiveFactorIdx[subId] = 0;
            // 渲染第一个因子的详情面板
            if (data.factors && data.factors.length > 0) {
                renderFactorPanel(subId, data.factors[0], 0, data.factors);
            }
            // 表格列头点击切换到对应因子选项卡 + 拖拽排序
            const table = resultDiv.querySelector('.ic-table');
            if (table) {
                const theadRow = table.querySelector('thead tr');
                const headers = table.querySelectorAll('thead th:not(.idx-col)');

                // ── 拖拽排序 ──
                let dragStartColIdx = null;
                let dragOverColIdx = null;

                // 标记活跃因子列（默认第0列）
                headers.forEach(function(th, i) {
                    if (i === 0) th.classList.add('ic-active-factor');
                });
                headers.forEach(function(th) {
                    // 点击切换到对应因子
                    th.style.cursor = 'pointer';
                    th.addEventListener('click', function() {
                        var colIdx = parseInt(th.getAttribute('data-col-idx'));
                        if (!isNaN(colIdx) && window._icDataFactors) {
                            switchActiveFactor(subId, colIdx, window._icDataFactors[subId]);
                        }
                    });

                    // ── 长按添加因子到因子库 ──
                    bindLongPressAddToLibrary(th, subId);

                    // 拖拽开始
                    th.addEventListener('dragstart', function(e) {
                        const colIdx = parseInt(this.getAttribute('data-col-idx'));
                        if (isNaN(colIdx)) return;
                        dragStartColIdx = colIdx;
                        this.style.opacity = '0.5';
                        e.dataTransfer.effectAllowed = 'move';
                    });

                    // 拖拽结束
                    th.addEventListener('dragend', function(e) {
                        this.style.opacity = '';
                        dragStartColIdx = null;
                        dragOverColIdx = null;
                    });

                    // 拖拽经过
                    th.addEventListener('dragover', function(e) {
                        const colIdx = parseInt(this.getAttribute('data-col-idx'));
                        if (isNaN(colIdx) || dragStartColIdx === null) return;
                        e.preventDefault();
                        dragOverColIdx = colIdx;
                        this.classList.add('drag-over');
                    });

                    th.addEventListener('dragleave', function(e) {
                        this.classList.remove('drag-over');
                    });

                    // 放下
                    th.addEventListener('drop', function(e) {
                        e.preventDefault();
                        this.classList.remove('drag-over');
                        const colIdx = parseInt(this.getAttribute('data-col-idx'));
                        if (isNaN(colIdx)) return;
                        if (dragStartColIdx !== null && dragOverColIdx !== null && dragStartColIdx !== dragOverColIdx) {
                            // 先在本地重排表格列和因子面板（瞬时的前端操作，无需重新计算）
                            reorderTableColumns(table, dragStartColIdx, dragOverColIdx, subId);
                            // 同步更新因子缓存顺序
                            var cachedFactors = window._icDataFactors && window._icDataFactors[subId];
                            if (cachedFactors) {
                                var moved = cachedFactors.splice(dragStartColIdx, 1)[0];
                                cachedFactors.splice(dragOverColIdx, 0, moved);
                            }

                            // Frontend manages candidate order locally — no backend call needed.
                            // Reorder is tracked in local state by the settings panel.
                            if (typeof window.reloadParamModule === 'function') {
                                window.reloadParamModule();
                            }
                            fetchFactorList();
                        }
                    });
                });
            }
            // 隐藏原有的 Highcharts 大容器
            const chartContainer = document.getElementById(`chart-container-${subId}`);
            if (chartContainer) chartContainer.style.display = 'none';
        } catch (err) {
            btn.disabled = false;
            statusSpan.innerText = '前端错误: ' + err.message;
            statusSpan.style.color = '#d40000';
        }
    };

    // 旧的频率抽屉（populateFreqDrawer/updateFreqSummary/抽屉勾选框）已删除：
    // 因子选择 + 每因子 return_freq 现由"因子"tab 与"收益率频率"tab 直接管理
    // factor_selections（见 renderICFactorSelectionTab / renderICReturnFreqTab）。
    window.updateFreqSummary = function() {};  // 兼容旧调用（global_template 摘要刷新）

    // 弃用旧的内联面板生成，保留兼容性（返回空字符串）
    function buildFactorConfigPanel(subId, factors) {
        return '';
    }

    // 按后端 manifest serialization.fallback 声明，将空 selections 回退到 candidates
    function applyFallbackSelectionsFromCandidates() {
        var s = ensureICStore();
        if (!s || !icSettingsManifest) return;
        var defs = icSettingsManifest.defaults || {};
        Object.keys(defs).forEach(function(key) {
            var meta = defs[key] || {};
            var ser = meta.serialization || {};
            if (ser.fallback !== 'candidates') return;
            if (!ser.candidate_field) return;
            var selections = icSettingValues[key];
            if (Array.isArray(selections) && selections.length > 0) return;
            // 从 candidate_field 对应的值回退：先 icSettingValues，再 effective（parent 回退）
            var candidates = s.effective(ser.candidate_field);
            if (!Array.isArray(candidates) || !candidates.length) return;
            // 全选候选
            icSettingValues[key] = candidates.slice();
            if (key === 'product_path_selections') {
                icProductPathSelections = candidates.slice();
            }
        });
    }

    // 渲染主选项卡（外部调用）
    window.renderICTabs = async function(productPathSelections) {
        const container = document.getElementById('ic-tab-container');
        if (!container) return;
        icProductPathSelections = Array.isArray(productPathSelections) ? productPathSelections.slice() : [];
        if (window.FactorSeriesViewer && typeof window.FactorSeriesViewer.setSelections === 'function') {
            window.FactorSeriesViewer.setSelections({ product_path_selection: icProductPathSelections[0] || null });
        }
        const settingsManifest = await loadICSettingsManifest();
        applyFallbackSelectionsFromCandidates();
        syncICStore();
        renderICSettingsPanel(settingsManifest);
        if (icProductPathSelections.length === 0) {
            container.innerHTML = '<div style="color:#888; padding:8px; border:1px dashed #ccc; border-radius:4px;">请在 IC 测试设置中选择产品路径。</div>';
            return;
        }
        // 获取因子列表（如果尚未获取），并确保 factor_selections 默认全选
        if (factorList.length === 0) await fetchFactorList();
        ensureFactorSelectionsDefault();
        let tabsHtml = '<ul class="nav nav-tabs" id="icTab" role="tablist">';
        let panelsHtml = '<div class="tab-content" id="icTabContent">';
        icProductPathSelections.forEach((sub, idx) => {
            const subId = selectionId(sub);
            const activeClass = idx === 0 ? 'active' : '';
            const showClass = idx === 0 ? 'show active' : '';
            const tabId = `ic-tab-${subId}`;
            const panelId = `ic-panel-${subId}`;
            const tabLabel = selectionLabel(sub) || ('产品路径' + (idx+1));
            const pgPrefix = sub.product_group ? '📦 ' : '';
            // tab 名用 chip 渲染
            const tabChip = '<span class="gt-backend-chip" style="pointer-events:none;">' + renderChipHtml('产品路径', pgPrefix + tabLabel) + '</span>';
            tabsHtml += `<li class="nav-item"><button class="nav-link ${activeClass}" id="${tabId}" data-product-path-selection-id="${subId}" data-bs-toggle="tab" data-bs-target="#${panelId}" type="button" role="tab">${tabChip}</button></li>`;
            panelsHtml += `
                <div class="tab-pane fade ${showClass}" id="${panelId}" role="tabpanel">
                    <div class="ic-card">
                        <div style="display: flex; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 12px;">
                            <button class="btn btn-primary btn-sm" id="run-ic-btn-${subId}" onclick="runIC('${subId}')">运行IC测试</button>
                            <span id="ic-status-${subId}" class="ic-status"></span>
                        </div>
                        ${renderICResultTabs(subId, settingsManifest)}
                        <div id="ic-result-${subId}"></div>
                        <div id="chart-container-${subId}" style="width:100%; margin-top:14px;"></div>
                    </div>
                </div>
            `;
        });
        tabsHtml += '</ul>';
        panelsHtml += '</div>';
        container.innerHTML = tabsHtml + panelsHtml;
        if (typeof bootstrap !== 'undefined') {
            const tabTriggers = document.querySelectorAll('#icTab button[data-bs-toggle="tab"]');
            tabTriggers.forEach(trigger => {
                const tab = new bootstrap.Tab(trigger);
                trigger.addEventListener('click', (e) => { e.preventDefault(); tab.show(); });
            });
        }
        // 结果分析 tab（rank/pearson/summary/decay/rolling/by_group/coverage）：
        // 点击切换显示对应 data-result-section，未实现的显式占位。委托绑定一次。
        container.querySelectorAll('.ic-result-tabs').forEach(function(bar) {
            bar.addEventListener('click', function(e) {
                var btn = e.target.closest('.ic-result-tab-btn');
                if (!btn) return;
                applyICResultTabFilter(bar.getAttribute('data-product-path-selection-id'), btn.getAttribute('data-result-tab'));
            });
        });
    };

    // 在某 product_path 的结果区内，只显示与 tabKey 匹配的 result section。
    function applyICResultTabFilter(subId, tabKey) {
        if (!subId || !tabKey) return;
        var resultDiv = document.getElementById('ic-result-' + subId);
        if (!resultDiv) return;
        resultDiv.querySelectorAll('.ic-result-section').forEach(function(sec) {
            var keys = (sec.getAttribute('data-result-section') || '').split(/\s+/);
            sec.style.display = keys.indexOf(tabKey) >= 0 ? '' : 'none';
        });
        // 高亮当前 result tab 按钮
        var bar = resultDiv.parentNode && resultDiv.parentNode.querySelector('.ic-result-tabs[data-product-path-selection-id="' + subId + '"]');
        if (bar) {
            bar.querySelectorAll('.ic-result-tab-btn').forEach(function(b) {
                var on = b.getAttribute('data-result-tab') === tabKey;
                b.style.borderColor = on ? '#2563eb' : '#cbd5e1';
                b.style.background = on ? '#eff6ff' : '#fff';
                b.style.color = on ? '#1d4ed8' : '#475569';
            });
        }
    }
    window.applyICResultTabFilter = applyICResultTabFilter;

    // 页面加载完成后，如果已有 submissions，则渲染
    // 频率抽屉已删除——因子/收益率频率改由设置 tab 管理。保留空函数兼容旧调用。
    function initFreqDrawerButtons() {}

    // 因子选择(factor_selections)：从频率抽屉读勾选的因子 [{alias, return_freq}]，
    // ── 因子选择(factor_selections) 唯一真源（取代旧频率抽屉）──────────────────
    // 形如 [{alias, return_freq}]，return_freq 空 = 跟随因子频率 $F。
    function getFactorSelections() {
        if (!Array.isArray(icSettingValues.factor_selections)) icSettingValues.factor_selections = [];
        return icSettingValues.factor_selections;
    }
    function setFactorSelections(list) {
        icSettingValues.factor_selections = (Array.isArray(list) ? list : []).map(function(it) {
            return { alias: it.alias, return_freq: it.return_freq || '' };
        });
    }
    // 未选时默认选中全部因子（return_freq 默认空 = $F）。
    function ensureFactorSelectionsDefault() {
        if (!getFactorSelections().length && factorList.length) {
            setFactorSelections(factorList.map(function(f) { return { alias: f.alias || f.name, return_freq: '' }; }));
        }
    }
    function collectFactorSelections() {
        ensureFactorSelectionsDefault();
        return getFactorSelections().slice();
    }
    function applyFactorSelections(list) {
        if (Array.isArray(list)) setFactorSelections(list);
    }
    function toggleFactorSelection(alias) {
        var sel = getFactorSelections();
        var i = sel.findIndex(function(s) { return s.alias === alias; });
        if (i >= 0) sel.splice(i, 1);
        else sel.push({ alias: alias, return_freq: '' });
    }
    function setFactorReturnFreq(alias, freq) {
        var hit = getFactorSelections().find(function(s) { return s.alias === alias; });
        if (hit) hit.return_freq = freq;
    }

    // ── 模板快照：把 IC 的设置/选择注册进因子家族设置模板 ──────────────────
    function collectICSnapshot() {
        return {
            settings: Object.assign({}, icSettingValues),
            product_path_selections: (icProductPathSelections || []).slice(),
            factor_selections: collectFactorSelections(),
            mounted_tabs: (icMountedSettingsTabs || []).slice(),
        };
    }

    async function applyICSnapshot(data) {
        if (!data || typeof data !== 'object') return;
        await loadICSettingsManifest();
        if (data.settings && typeof data.settings === 'object') {
            Object.keys(data.settings).forEach(function(k) { icSettingValues[k] = data.settings[k]; });
        }
        if (Array.isArray(data.mounted_tabs) && data.mounted_tabs.length) {
            icMountedSettingsTabs = data.mounted_tabs.slice();
        }
        if (Array.isArray(data.product_path_selections) && data.product_path_selections.length) {
            icProductPathSelections = data.product_path_selections.slice();
            mergeICProductPathCandidates(icProductPathSelections);
        }
        // factor_selections 现在是纯字段，须在渲染前恢复，因子/频率 tab 才显示正确。
        if (Array.isArray(data.factor_selections)) applyFactorSelections(data.factor_selections);
        renderICSettingsPanel(icSettingsManifest);
        await window.renderICTabs(icProductPathSelections);
    }

    function registerICSnapshot() {
        if (!window._snapshotRegistry || typeof window._snapshotRegistry.register !== 'function') return false;
        window._snapshotRegistry.register({
            key: 'ic_test',
            order: 60,   // 在页面设置 / 分组之后再 apply（IC 依赖页面产品路径作回退）
            label: 'IC 测试',
            icon: '📈',
            collect: collectICSnapshot,
            apply: applyICSnapshot,
            summarize: function(d) {
                var s = (d && d.settings) || {};
                var lines = [];
                var n = (d && d.product_path_selections || []).length;
                if (n) lines.push('产品路径选择: ' + n + ' 个');
                var fn = (d && d.factor_selections || []).length;
                if (fn) lines.push('因子选择: ' + fn + ' 个');
                ['ic_correlation', 'ic_lag', 'return_price_basis', 'return_frequency_mode', 'by_group', 'group_adjust', 'min_cross_section_count'].forEach(function(k) {
                    if (s[k] !== undefined && s[k] !== '' && s[k] !== null) lines.push(k + ': ' + s[k]);
                });
                return lines.length ? lines : null;
            },
        });
        return true;
    }

    async function initICModule() {
        registerICSnapshot();
        await fetchFactorList();
        ensureFactorSelectionsDefault();
        await window.renderICTabs(icProductPathSelections);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initICModule);
    } else {
        initICModule();
    }

    // 供参数模块调用，刷新因子列表和 IC 选项卡
    window.refreshICModule = async function() {
        console.log('刷新 IC 模块因子列表');
        await fetchFactorList();  // 重新获取因子列表
        ensureFactorSelectionsDefault();
        await window.renderICTabs(icProductPathSelections);
        window.factorList = factorList;
    };

    window.factorList = factorList;

    document.addEventListener('groupTestProductPathSelectionsChanged', function() {
        if (icProductPathSelections.length) {
            window.renderICTabs(icProductPathSelections).catch(function(error) {
                console.error('[IC] refresh product path selection failed:', error);
            });
        } else {
            renderICSettingsPanel(icSettingsManifest);
        }
    });

    document.addEventListener('singleFactorGlobalSettingsChanged', function() {
        const changed = applyGlobalICDefaults();
        if (changed) {
            window.renderICTabs(icProductPathSelections).catch(function(error) {
                console.error('[IC] refresh global defaults failed:', error);
            });
        } else {
            renderICSettingsPanel(icSettingsManifest);
        }
    });

    // ========== 因子截面分布可视化 ==========

    async function openFactorDistribution(subId, factorName, factorAlias, tsMs, product) {
        const drawer = document.getElementById('factor-dist-drawer');
        const title  = document.getElementById('dist-drawer-title');
        const chartContainer = document.getElementById('dist-chart-container');
        if (!drawer || !title || !chartContainer) return;

        // 打开抽屉并显示加载状态
        drawer.classList.add('open');
        title.textContent = `${factorName} 截面分布` + (product ? ` · ${product}` : '');
        chartContainer.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#888;">加载中...</div>';

        try {
            const selection = selectionById(subId);
            const res = await fetch('/get_factor_distribution', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    product_path_selection_id: selectionId(selection),
                    product_path_selection: selection,
                    factor_family_alias: factorFamilyAlias,
                    factor_name: factorName,
                    factor_alias: factorAlias,
                    timestamp: tsMs,
                    product: product || null,
                    page_uuid: window._pageUuid || '',
                }),
            });
            const data = await res.json();
            if (!data.success) {
                chartContainer.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#d00;">${data.error || '获取分布数据失败'}</div>`;
                return;
            }
            drawDistributionHistogram(chartContainer, data, factorName);
        } catch (err) {
            console.error('获取因子分布异常:', err);
            chartContainer.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#d00;">请求失败: ${err.message}</div>`;
        }
    }

    function drawDistributionHistogram(container, data, factorName) {
        if (typeof Highcharts === 'undefined') return;
        const values = data.values.map(v => v.value);
        const stats  = data.stats;
        const n      = data.n;
        const highlightValue = data.highlight_value;
        const highlightProduct = data.highlight_product;

        // 自动分箱：用 Sturges 公式 k = ceil(log2(n) + 1)
        const nBins = Math.max(8, Math.min(80, Math.ceil(Math.log2(n) + 1)));
        const vmin = stats.min, vmax = stats.max;
        const binWidth = (vmax - vmin) / nBins || 1;
        const bins = [];
        let highlightBinIdx = -1;
        for (let i = 0; i < nBins; i++) {
            bins.push({ low: vmin + i * binWidth, high: vmin + (i + 1) * binWidth, count: 0 });
        }
        for (const v of values) {
            let idx = Math.min(nBins - 1, Math.max(0, Math.floor((v - vmin) / binWidth)));
            if (idx === nBins) idx = nBins - 1;
            bins[idx].count++;
        }
        // 找高亮产品所在的 bin
        if (highlightValue !== null && highlightValue !== undefined) {
            highlightBinIdx = Math.min(nBins - 1, Math.max(0, Math.floor((highlightValue - vmin) / binWidth)));
            if (highlightBinIdx === nBins) highlightBinIdx = nBins - 1;
        }

        // 用区间中点作为 x 值，Highcharts 可自动计算合适的刻度密度
        const binMids = bins.map(b => (b.low + b.high) / 2);
        const binCounts = bins.map(b => b.count);

        // 构建 tooltip 用的完整区间说明
        const binFullNames = bins.map((b, i) => {
            if (i === nBins - 1) return `[${b.low.toFixed(4)}, ${b.high.toFixed(4)}]`;
            return `[${b.low.toFixed(4)}, ${b.high.toFixed(4)})`;
        });

        // 构建数据点，高亮柱用不同颜色
        const seriesData = binMids.map((mid, i) => ({
            x: mid,
            y: binCounts[i],
            color: (i === highlightBinIdx) ? '#e74c3c' : '#0078d4',
        }));

        const pcts = stats.percentiles || {};
        const extraInfo = [];
        if (highlightProduct && highlightValue !== null && highlightValue !== undefined) {
            extraInfo.push(`${highlightProduct} 因子值=${highlightValue.toFixed(4)}`);
        }
        const subtitle = [
            `N=${n}`,
            `均值=${stats.mean?.toFixed(4)}`,
            `标准差=${stats.std?.toFixed(4)}`,
            `偏度=${stats.skewness?.toFixed(4)}`,
            `峰度=${stats.kurtosis?.toFixed(4)}`,
            `P1=${pcts['1']}`,
            `P99=${pcts['99']}`,
        ].concat(extraInfo).join(' ｜ ');

        Highcharts.chart(container, {
            chart: { type: 'column', zoomType: 'x' },
            title: { text: `${factorName} 截面分布`, style: { fontSize: '14px' } },
            subtitle: { text: subtitle, style: { fontSize: '11px', color: '#666' } },
            xAxis: {
                title: { text: '因子值' },
                crosshair: true,
                labels: { style: { fontSize: '10px' }, formatter: function() { return this.value.toFixed(4); } },
            },
            yAxis: {
                title: { text: '频数' },
                min: 0,
            },
            tooltip: {
                formatter: function() {
                    var tip = '<b>' + binFullNames[this.point.index] + '</b><br/>频数: <b>' + this.y + '</b>';
                    if (this.point.index === highlightBinIdx && highlightProduct) {
                        tip += '<br/>🔴 <b>' + highlightProduct + '</b> (' + highlightValue.toFixed(4) + ')';
                    }
                    return tip;
                },
            },
            series: [{
                name: '品种数',
                data: seriesData,
                pointPadding: 0,
                groupPadding: 0,
            }],
            plotOptions: {
                column: {
                    borderWidth: 0,
                },
            },
            credits: { enabled: false },
            legend: { enabled: false },
        });
    }

    // ── 长按因子列头 → 添加到因子库 ──
    function bindLongPressAddToLibrary(th, subId) {
        var helper = window.SingleFactorLibraryHelper;
        if (!helper) return;
        helper.bindLongPress(th, {
            popoverClass: 'ic-add-to-library-popover',
            getFactorAlias: function() {
                var colIdx = parseInt(th.getAttribute('data-col-idx'));
                if (isNaN(colIdx)) return null;
                var factors = window._icDataFactors && window._icDataFactors[subId];
                if (!factors || colIdx >= factors.length) return null;
                return factors[colIdx].alias || factors[colIdx].name || null;
            },
            getProductGroup: function() {
                return helper.inferScopeFromSubmissionId(subId);
            }
        });
    }

    function esc(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }
})();
