/**
 * 单因子测试的因子家族设置模板模块。
 * 保存/加载当前因子家族的测试设置：参数、时间范围、产品路径选择、分组/IC 测试设置。
 *
 * ── Snapshot Registry（快照注册表）─────────────────────────────────────
 * 扩展方式：调用 window._snapshotRegistry.register({ key, order, label, icon,
 *   collect(), apply(data, ctx), summarize(data) })
 * - key:       快照字段名（如 "params", "group_settings"）
 * - order:     应用顺序（数字越小越先 apply），默认 100
 * - label:     摘要行中文标签
 * - icon:      摘要行 emoji 图标
 * - collect(): 返回当前模块状态的纯数据对象（同步或 async）
 * - apply():   接收快照数据 + ctx{tplId}，恢复到页面（同步或 async）
 * - summarize(): 接收快照数据，返回摘要字符串（或字符串数组，多行展示）
 */
(function() {
    const FF_ALIAS = window.factorFamilyAlias || '';
    const TEMPLATE_API_BASE = '/api/single_factor_setting_templates/';
    var _templateListRequest = null;
    var _templateDetailCache = {};

    function requestJSON(url, options) {
        options = options || {};
        var headers = Object.assign({
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
        }, options.headers || {});
        return fetch(url, Object.assign({}, options, {
            headers: headers,
            credentials: 'same-origin',
        })).then(function(resp) {
            var contentType = resp.headers.get('content-type') || '';
            if (contentType.indexOf('application/json') < 0) {
                return resp.text().then(function(text) {
                    var hint = text && text.trim().charAt(0) === '<'
                        ? '接口返回了 HTML，可能登录已失效'
                        : '接口未返回 JSON';
                    throw new Error(hint + ' (HTTP ' + resp.status + ')');
                });
            }
            return resp.json().then(function(data) {
                if (!resp.ok || data.success === false) {
                    throw new Error(data.error || ('HTTP ' + resp.status));
                }
                return data;
            });
        });
    }

    function setTransientStatus(el, text, color, delayMs) {
        if (!el) return;
        el.textContent = text || '';
        el.style.color = color || '#64748b';
        if (el._clearTimer) clearTimeout(el._clearTimer);
        if (text) {
            el._clearTimer = setTimeout(function() {
                if (el.textContent === text) el.textContent = '';
            }, delayMs || 2600);
        }
    }

    function templateStatusEl() {
        return document.getElementById('global-tpl-save-status');
    }

    function rememberLoadedTemplateName(name) {
        window._currentSingleFactorTemplateName = name || '';
        document.dispatchEvent(new CustomEvent('singleFactorTemplateChanged', {
            detail: { name: window._currentSingleFactorTemplateName },
        }));
    }

    function restoreScrollAfter(work) {
        var scrollX = window.scrollX;
        var scrollY = window.scrollY;
        return Promise.resolve()
            .then(work)
            .finally(function() {
                requestAnimationFrame(function() {
                    window.scrollTo(scrollX, scrollY);
                });
            });
    }

    // ═══════════════════════════════════════════════════════════════════════
    // Snapshot Registry — 统一管理所有可保存/恢复的配置模块
    // ═══════════════════════════════════════════════════════════════════════
    var _registry = [];
    var _registryByKey = {};

    var SnapshotRegistry = {
        _registry: _registry,           // 按 order 排序的注册项数组（只读引用）
        _registryByKey: _registryByKey, // key → 注册项映射（只读引用）
        /**
         * 注册一个快照模块。
         * @param {object} spec — { key, order?, label, icon, collect, apply, summarize }
         */
        register: function(spec) {
            if (!spec.key || !spec.collect || !spec.apply) {
                console.error('[SnapshotRegistry] register failed: missing key/collect/apply', spec);
                return;
            }
            if (_registryByKey[spec.key]) {
                console.warn('[SnapshotRegistry] overwriting existing key:', spec.key);
                // remove old entry
                for (var ri = _registry.length - 1; ri >= 0; ri--) {
                    if (_registry[ri].key === spec.key) _registry.splice(ri, 1);
                }
                delete _registryByKey[spec.key];
            }
            spec.order = typeof spec.order === 'number' ? spec.order : 100;
            _registry.push(spec);
            _registryByKey[spec.key] = spec;
            // Keep sorted by order
            _registry.sort(function(a, b) { return a.order - b.order; });
            console.log('[SnapshotRegistry] registered:', spec.key, '(order=' + spec.order + ')');
        },

        /** 遍历所有注册项收集快照 → { key: data, ... } */
        collectAll: async function() {
            var snapshot = {};
            for (var i = 0; i < _registry.length; i++) {
                var entry = _registry[i];
                try {
                    var data = entry.collect();
                    if (data && typeof data.then === 'function') {
                        data = await data;
                    }
                    if (data !== undefined && data !== null) {
                        snapshot[entry.key] = data;
                    }
                } catch (e) {
                    console.error('[SnapshotRegistry] collect failed for:', entry.key, e);
                }
            }
            return snapshot;
        },

        /** 遍历所有注册项应用快照（按 order 排序）。
         *  @param skipKeys - 可选，要跳过的 key 数组 */
        applyAll: async function(snapshot, ctx, skipKeys) {
            if (!snapshot) return;
            var skipSet = {};
            if (skipKeys) { for (var s = 0; s < skipKeys.length; s++) { skipSet[skipKeys[s]] = true; } }
            for (var i = 0; i < _registry.length; i++) {
                var entry = _registry[i];
                if (skipSet[entry.key]) continue;
                var data = snapshot[entry.key];
                if (data === undefined || data === null) continue;
                try {
                    var result = entry.apply(data, ctx);
                    if (result && typeof result.then === 'function') {
                        await result;
                    }
                } catch (e) {
                    console.error('[SnapshotRegistry] apply failed for:', entry.key, e);
                }
            }
        },

        /** 遍历所有注册项生成摘要行 HTML */
        summarizeAll: function(snapshot) {
            if (!snapshot) return '';
            var html = '';
            for (var i = 0; i < _registry.length; i++) {
                var entry = _registry[i];
                var data = snapshot[entry.key];
                if (data === undefined || data === null) continue;
                try {
                    if (typeof entry.summarize !== 'function') continue;
                    var val = entry.summarize(data);
                    if (!val && val !== 0) continue;
                    if (Array.isArray(val) && val.length === 0) continue;
                    html += _buildSummaryRow(entry.label, entry.key, val, entry.icon);
                } catch (e) {
                    console.error('[SnapshotRegistry] summarize failed for:', entry.key, e);
                }
            }
            html += _summarizeBackendBacktestSettings(snapshot);
            return html;
        },

        /** 获取所有已注册的 key 列表 */
        keys: function() {
            return _registry.map(function(r) { return r.key; });
        }
    };

    async function _applyEntriesWhere(snapshot, ctx, predicate) {
        if (!snapshot) return;
        for (var i = 0; i < _registry.length; i++) {
            var entry = _registry[i];
            if (!predicate(entry)) continue;
            var data = snapshot[entry.key];
            if (data === undefined || data === null) continue;
            try {
                var result = entry.apply(data, ctx);
                if (result && typeof result.then === 'function') {
                    await result;
                }
            } catch (e) {
                console.error('[SnapshotRegistry] apply failed for:', entry.key, e);
            }
        }
    }

    /** 构建一条摘要行 HTML */
    function _buildSummaryRow(label, key, value, icon) {
        var chipKeys = { group_settings: 1 };
        var useChips = chipKeys.hasOwnProperty(key);
        var valStr = '';
        if (Array.isArray(value)) {
            valStr = value.map(function(v) {
                var safeVal = escapeHtml(String(v));
                if (useChips) {
                    // Split 'key=val, key2=val2' into individual chips
                    var chips = safeVal.split(', ');
                    return '<div style="display:flex;flex-wrap:wrap;gap:3px;padding:1px 0;">'
                        + chips.map(function(c) {
                            return '<span style="display:inline-block;padding:1px 6px;font-size:10px;line-height:1.6;'
                                + 'background:#eef2ff;color:#4338ca;border-radius:999px;white-space:nowrap;">'
                                + c + '</span>';
                        }).join('')
                        + '</div>';
                }
                return '<div style="font-size:11px;color:#555;padding:1px 0;">' + safeVal + '</div>';
            }).join('');
        } else {
            valStr = '<span style="font-size:11px;color:#555;">' + escapeHtml(String(value)) + '</span>';
        }
        return '<div style="display:flex;align-items:flex-start;gap:8px;padding:3px 0;border-bottom:1px dotted #e5e7eb;">'
            + '<span style="font-size:12px;flex-shrink:0;min-width:18px;">' + (icon || '') + '</span>'
            + '<span style="font-size:12px;font-weight:500;color:#333;flex-shrink:0;min-width:70px;">' + escapeHtml(label) + '</span>'
            + '<span style="flex:1;min-width:0;">' + valStr + '</span>'
            + '</div>';
    }

    function _deepClone(obj) {
        if (obj === undefined || obj === null) return obj;
        try {
            return JSON.parse(JSON.stringify(obj));
        } catch (e) {
            return obj;
        }
    }

    function _asArray(value) {
        return Array.isArray(value) ? value : [];
    }

    function _firstNonEmpty(values, fallback) {
        for (var i = 0; i < values.length; i++) {
            if (values[i] !== undefined && values[i] !== null && String(values[i]).trim() !== '') {
                return String(values[i]).trim();
            }
        }
        return fallback || '';
    }

    function _formatDateTime(dateValue, timeValue) {
        var d = dateValue || '';
        var t = timeValue || '';
        return (d && t) ? (d + ' ' + t) : (d || t || '未设置');
    }

    function _summarizeBackendBacktestSettings(snapshot) {
        var local = snapshot && snapshot.local_settings;
        var html = '';
        if (!local) return html;
        var index = window.GroupTest && window.GroupTest.backendSettings && window.GroupTest.backendSettings._state
            ? window.GroupTest.backendSettings._state.index
            : null;
        if (index && index.defaults && index.tab_lists) {
            var values = {};
            Object.keys(index.defaults).forEach(function(key) {
                values[key] = index.defaults[key].value;
            });
            Object.keys(local).forEach(function(key) { values[key] = local[key]; });
            (index.tab_lists['local-settings'] || []).forEach(function(tab) {
                if (!tab.summary_template) return;
                var keys = Array.isArray(tab.summary_keys) && tab.summary_keys.length
                    ? tab.summary_keys
                    : Object.keys(index.defaults).filter(function(key) {
                        return index.defaults[key].tab_key === tab.key;
                    });
                if (!keys.some(function(key) { return Object.prototype.hasOwnProperty.call(local, key); })) return;
                var text = String(tab.summary_template).replace(/\{([^}]+)\}/g, function(_, key) {
                    return values[key] === undefined || values[key] === null ? '' : String(values[key]);
                }).replace(/\s+/g, ' ').trim();
                html += _buildSummaryRow(tab.label || tab.key, 'local_settings', text, '⚙️');
            });
        }
        var mounted = [];
        var summarized = {};
        if (index && index.defaults && index.tab_lists) {
            (index.tab_lists['local-settings'] || []).forEach(function(tab) {
                if (!tab.summary_template) return;
                (tab.summary_keys || []).forEach(function(key) { summarized[key] = true; });
            });
        }
        var keys = Object.keys(local).filter(function(key) { return !summarized[key]; });
        if ((Array.isArray(mounted) && mounted.length) || keys.length) {
            var parts = [];
            if (Array.isArray(mounted) && mounted.length) parts.push('显示页签: ' + mounted.join(', '));
            if (keys.length) parts.push('显式字段: ' + keys.join(', '));
            html += _buildSummaryRow('回测设置', 'local_settings', parts, '⚙️');
        }
        return html;
    }

    function _hasOwn(obj, key) {
        return Object.prototype.hasOwnProperty.call(obj || {}, key);
    }

    function _hasGroupSettingsSnapshot(gs) {
        if (!gs) return false;
        return (_asArray(gs.groups).length > 0) ||
            (_asArray(gs.lsConfigs).length > 0) ||
            (_asArray(gs.baseGroups).length > 0) ||
            (_asArray(gs.derivedGraph).length > 0);
    }

    // 暴露注册表
    window._snapshotRegistry = SnapshotRegistry;

    // ═══════════════════════════════════════════════════════════════════════
    // 注册 6 个内置模块（order 控制 apply 顺序）
    // ═══════════════════════════════════════════════════════════════════════

    // ── 1. params_list (order=20) ──
    SnapshotRegistry.register({
        key: 'params_list',
        order: 20,
        label: '参数设置',
        icon: '⚙️',
        collect: function() {
            try {
                var pl = [];
                var tbodyEl = document.getElementById('factor_table_body');
                var moduleElem = document.getElementById('parameter_module');
                var paramAliases = [];
                if (moduleElem) {
                    var aliasesAttr = moduleElem.getAttribute('data-param-aliases');
                    if (aliasesAttr) { try { paramAliases = JSON.parse(aliasesAttr); } catch(e) {} }
                }
                if (tbodyEl && paramAliases.length > 0) {
                    var rows = tbodyEl.querySelectorAll('tr');
                    rows.forEach(function(row) {
                        if (row.id === 'add_row') return;
                        var cells = row.querySelectorAll('td');
                        if (cells.length >= paramAliases.length + 1) {
                            var rowParams = {};
                            for (var i = 0; i < paramAliases.length; i++) {
                                var tdText = (cells[i + 1].textContent || '').trim();
                                if (tdText) rowParams[paramAliases[i]] = tdText;
                            }
                            if (Object.keys(rowParams).length > 0) pl.push(rowParams);
                        }
                    });
                }
                return pl;
            } catch (e) { return []; }
        },
        apply: async function(params_list, ctx) {
            if (!params_list || params_list.length === 0) return;
            try {
                var replaceResp = await fetch('/replace_params', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ factor_family_alias: FF_ALIAS, params_list: params_list })
                });
                var replaceData = await replaceResp.json();
                if (!replaceData.success) {
                    alert('恢复参数失败: ' + (replaceData.error || ''));
                    return;
                }
                if (typeof window._renderParamFactorRows === 'function' && Array.isArray(replaceData.factor_rows)) {
                    window._renderParamFactorRows(replaceData.factor_rows);
                } else if (typeof window.reloadParamModule === 'function') {
                    await new Promise(function(resolve) { window.reloadParamModule(resolve); });
                }
                if (typeof window.refreshICModule === 'function') window.refreshICModule();
            } catch (e) { alert('恢复参数异常: ' + e.message); }
        },
        summarize: function(pl) {
            return pl.map(function(row, idx) {
                var parts = [];
                Object.keys(row || {}).forEach(function(k) {
                    parts.push(k + '=' + row[k]);
                });
                return '参数组' + (idx + 1) + ': ' + (parts.join(', ') || '未设置');
            });
        }
    });

    // ── 6+7. GroupTest 依赖的 adapter 延迟注册（等 GroupTest 脚本加载后再注册） ──
    var _gtAdaptersRegistered = false;
    async function _ensureGroupTestAdapters() {
        if (_gtAdaptersRegistered) return;

        // If GT modules aren't ready yet, trigger lazy load and wait
        var GT = window.GroupTest;
        if (!GT || !GT.groupSettings || !GT.localSettings) {
            if (typeof window._loadGTDeferredScripts === 'function') {
                console.log('[global_template] waiting for GT deferred scripts...');
                await window._loadGTDeferredScripts();
                GT = window.GroupTest;  // re-read after load
            }
        }
        if (_gtAdaptersRegistered) return;  // lazy loader already called us

        // 6. group_settings (order=50)
        if (GT && GT.groupSettings && GT.groupSettings.settings) {
            var base = GT.groupSettings.settings;
            SnapshotRegistry.register({
                key: base.key,
                order: base.order,
                label: base.label,
                icon: base.icon,
                collect: base.collect,
                apply: function(gs, ctx) {
                    var working = base.normalize ? base.normalize(_deepClone(gs) || {}) : (_deepClone(gs) || {});
                    var applyResult = base.apply(working);
                    if (applyResult.errors && applyResult.errors.length > 0) {
                        console.warn('[global_template] group_settings apply warnings:', applyResult.errors);
                    }
                    console.log('[global_template] group_settings applied: ' + (applyResult.applied ? applyResult.applied.groups : '?') + ' groups');
                    if (GT.backendSettings && typeof GT.backendSettings.applyFlatSnapshot === 'function') {
                        GT.backendSettings.applyFlatSnapshot((ctx && ctx.snapshot) || { group_settings: working });
                    }
                    if (GT.tabs && typeof GT.tabs.mountTab === 'function') {
                        GT.tabs.mountTab('list');
                    }
                },
                summarize: base.summarize,
            });
        }

        // 7. local_settings (order=50, GroupTest 本地 UI 状态)
        var LS = GT && GT.localSettings;
        if (LS) {
            SnapshotRegistry.register({
                key: LS.key,
                order: 15,
                label: LS.label,
                icon: LS.icon,
                collect: LS.collect,
                apply: async function(localSettings) {
                    var working = _deepClone(localSettings) || {};
                    if (GT.backendSettings && typeof GT.backendSettings.applyFlatSnapshot === 'function') {
                        await GT.backendSettings.applyFlatSnapshot({ local_settings: working });
                    }
                    var result = LS.apply(working);
                    if (result.errors && result.errors.length > 0) {
                        console.warn('[global_template] local_settings apply warnings:', result.errors);
                    }
                },
                summarize: LS.summarize,
            });
        }

        _gtAdaptersRegistered = true;
    }

    // 暴露给全局，供 lazy loader 在脚本加载完成后调用
    window._ensureGroupTestAdapters = _ensureGroupTestAdapters;

    // ── 收集当前所有设置快照（通过注册表） ──────────────────────────────
    async function collectSnapshot() {
        await _ensureGroupTestAdapters();
        var snapshot = await SnapshotRegistry.collectAll();
        if (window.GroupTest && GroupTest.backendSettings && typeof GroupTest.backendSettings.collectLocalSettings === 'function') {
            snapshot.local_settings = Object.assign(
                {},
                snapshot.local_settings || {},
                GroupTest.backendSettings.collectLocalSettings()
            );
            if (!Object.keys(snapshot.local_settings).length) delete snapshot.local_settings;
        }
        return snapshot;
    }

    // ── 应用快照（通过注册表，按 order 顺序） ───────────────────────────
    // tplId: 因子家族设置模板 ID
    async function applySnapshot(snapshot, tplId) {
        if (!snapshot) return;
        await _ensureGroupTestAdapters();

        var ctx = { tplId: tplId, snapshot: snapshot };
        var hasGroups = _hasGroupSettingsSnapshot(snapshot.group_settings);
        if (!hasGroups) _clearGroupTestData();
        await SnapshotRegistry.applyAll(snapshot, ctx);

        refreshOuterSummaries();
    }

    /** 清空分组测试数据（分组组合列表和 LS 组表），用于模板无 group_settings 时重置。 */
    function _clearGroupTestData() {
        try {
            var gs = window.GroupTest && window.GroupTest.groupSettings;
            if (gs) {
                if (gs.groups && typeof gs.groups._reset === 'function') {
                    gs.groups._reset();
                }
                if (gs.lsConfigs && typeof gs.lsConfigs._reset === 'function') {
                    gs.lsConfigs._reset();
                }
            }
        } catch (e) {
            console.warn('[global_template] _clearGroupTestData failed:', e);
        }
    }

    function refreshOuterSummaries() {
        setTimeout(function() {
            if (typeof window._updateParamSummary === 'function') window._updateParamSummary();
            if (typeof window.updateTimeSummary === 'function') window.updateTimeSummary();
            if (typeof window.updateCategorySummary === 'function') window.updateCategorySummary();
            if (typeof window.updateFreqSummary === 'function') window.updateFreqSummary();
        }, 0);
    }

    // ── 保存模板 ──────────────────────────────────────────────────────────
    async function saveTemplate() {
        const nameInput = document.getElementById('global-tpl-save-name');
        const statusEl = templateStatusEl();
        let name = (nameInput?.value || '').trim();
        if (!name) {
            // 默认使用当前时间戳
            const now = new Date();
            name = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')} ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
        }
        const snapshot = await collectSnapshot();

        setTransientStatus(statusEl, '保存中...', '#0078d4', 60000);
        try {
            const data = await restoreScrollAfter(function() {
                return requestJSON(TEMPLATE_API_BASE + encodeURIComponent(FF_ALIAS), {
                    method: 'POST',
                    body: JSON.stringify({
                        name: name,
                        ff_alias: FF_ALIAS,
                        snapshot: snapshot
                    })
                });
            });
            if (data.success) {
                rememberLoadedTemplateName(name);
                setTransientStatus(statusEl, '已保存', '#28a745');
                if (nameInput) nameInput.value = '';
                await restoreScrollAfter(loadTemplateList);
            } else {
                setTransientStatus(statusEl, '保存失败', '#d40000');
            }
        } catch (e) {
            setTransientStatus(statusEl, '网络错误', '#d40000');
        }
    }

    // ── 加载模板列表 ──────────────────────────────────────────────────────
    async function loadTemplateList() {
        if (_templateListRequest) return _templateListRequest;
        _templateListRequest = _loadTemplateListOnce();
        try {
            return await _templateListRequest;
        } finally {
            _templateListRequest = null;
        }
    }

    async function _loadTemplateListOnce() {
        const listEl = document.getElementById('global-tpl-list');
        if (!listEl) return;
        try {
            const data = await requestJSON(TEMPLATE_API_BASE + encodeURIComponent(FF_ALIAS));
            if (!data.success || !data.templates || data.templates.length === 0) {
                listEl.innerHTML = '<div class="global-template-empty">暂无已保存的模板</div>';
                return;
            }
            let html = '';
            data.templates.forEach(tpl => {
                const tplId = tpl.id;

                html += `
                <div class="tpl-row" style="border-bottom:1px solid #eef2f7;">
                    <div class="tpl-row-header" data-tpl-id="${tplId}" style="display:flex;align-items:center;justify-content:space-between;padding:8px 10px;gap:8px;">
                        <div class="tpl-name-area" style="flex:1;min-width:0;">
                            <div style="font-size:13px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(tpl.name)}</div>
                        </div>
                        <button type="button" class="btn btn-sm global-tpl-summary-btn" data-tpl-id="${tplId}" style="flex-shrink:0;font-size:12px;padding:3px 10px;color:#475569;border:1px solid #cbd5e1;background:#fff;border-radius:4px;cursor:pointer;">摘要</button>
                        <button type="button" class="btn btn-sm btn-outline-primary global-tpl-load-btn" data-tpl-id="${tplId}" style="flex-shrink:0;font-size:12px;padding:3px 10px;">加载</button>
                        <button type="button" class="btn btn-sm global-tpl-overwrite-btn" data-tpl-id="${tplId}" data-tpl-name="${escapeHtml(tpl.name)}" style="flex-shrink:0;font-size:12px;padding:3px 10px;color:#7a4b00;border:1px solid #f5c26b;background:#fff8e6;border-radius:4px;cursor:pointer;">覆盖</button>
                        <button type="button" class="btn btn-sm global-tpl-delete-btn" data-tpl-id="${tplId}" style="flex-shrink:0;font-size:12px;padding:3px 10px;color:#d40000;border:1px solid #faa;background:transparent;border-radius:4px;cursor:pointer;">删除</button>
                    </div>
                </div>`;
            });
            listEl.innerHTML = html;
            listEl.querySelectorAll('.global-tpl-summary-btn, .global-tpl-load-btn, .global-tpl-overwrite-btn, .global-tpl-delete-btn').forEach(btn => {
                btn.addEventListener('pointerdown', function(e) {
                    e.preventDefault();
                });
                btn.addEventListener('mousedown', function(e) {
                    e.preventDefault();
                });
            });
            listEl.querySelectorAll('.global-tpl-summary-btn').forEach(btn => {
                btn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    this.blur();
                    showTemplateSummary(this.getAttribute('data-tpl-id'));
                });
            });
            // 绑定加载按钮（阻止冒泡，避免触发展开/收起）
            listEl.querySelectorAll('.global-tpl-load-btn').forEach(btn => {
                btn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    loadTemplate(this.getAttribute('data-tpl-id'));
                });
            });
            // 绑定覆盖按钮（用当前页面设置覆盖已有模板）
            listEl.querySelectorAll('.global-tpl-overwrite-btn').forEach(btn => {
                btn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    overwriteTemplate(this.getAttribute('data-tpl-id'), this.getAttribute('data-tpl-name'));
                });
            });
            // 绑定删除按钮（阻止冒泡）
            listEl.querySelectorAll('.global-tpl-delete-btn').forEach(btn => {
                btn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    deleteTemplate(this.getAttribute('data-tpl-id'));
                });
            });
        } catch (e) {
            listEl.innerHTML = '<div style="color:#d40000;text-align:center;padding:10px;">加载失败: ' + e.message + '</div>';
        }
    }

    function fetchTemplateDetail(tplId) {
        if (_templateDetailCache[tplId]) return _templateDetailCache[tplId];
        _templateDetailCache[tplId] = requestJSON(TEMPLATE_API_BASE + encodeURIComponent(FF_ALIAS) + '/' + tplId)
            .then(function(data) {
                if (!data.template) {
                    throw new Error(data.error || '模板不存在');
                }
                return data.template;
            })
            .catch(function(error) {
                delete _templateDetailCache[tplId];
                throw error;
            });
        return _templateDetailCache[tplId];
    }

    function ensureSummaryOverlay() {
        var overlay = document.getElementById('global-tpl-summary-overlay');
        if (overlay) return overlay;
        overlay = document.createElement('div');
        overlay.id = 'global-tpl-summary-overlay';
        overlay.className = 'global-template-summary-overlay';
        overlay.innerHTML = ''
            + '<div class="global-template-summary-panel">'
            + '<div class="global-template-summary-header">'
            + '<strong id="global-tpl-summary-title">模板摘要</strong>'
            + '<button type="button" id="global-tpl-summary-close">关闭</button>'
            + '</div>'
            + '<div id="global-tpl-summary-body" class="global-template-summary-body"></div>'
            + '</div>';
        document.body.appendChild(overlay);
        overlay.addEventListener('click', function(event) {
            if (event.target === overlay || event.target.id === 'global-tpl-summary-close') {
                overlay.style.display = 'none';
            }
        });
        return overlay;
    }

    async function showTemplateSummary(tplId) {
        var overlay = ensureSummaryOverlay();
        var title = document.getElementById('global-tpl-summary-title');
        var body = document.getElementById('global-tpl-summary-body');
        overlay.style.display = 'flex';
        if (title) title.textContent = '模板摘要';
        if (body) body.innerHTML = '<div class="global-template-empty">加载中...</div>';
        try {
            var template = await fetchTemplateDetail(tplId);
            if (title) title.textContent = template.name || '模板摘要';
            var summaryHtml = SnapshotRegistry.summarizeAll(template.snapshot || {});
            if (body) body.innerHTML = summaryHtml || '<div class="global-template-empty">无设置信息</div>';
        } catch (error) {
            if (body) body.innerHTML = '<div class="global-template-empty" style="color:#d40000;">摘要加载失败: ' + escapeHtml(error.message) + '</div>';
        }
    }

    // ── 覆盖已有模板 ──────────────────────────────────────────────────────
    async function overwriteTemplate(tplId, tplName) {
        if (!confirm('用当前设置覆盖模板「' + (tplName || tplId) + '」？')) return;
        const statusEl = templateStatusEl();
        setTransientStatus(statusEl, '覆盖中...', '#7a4b00', 60000);
        try {
            const snapshot = await collectSnapshot();
            const data = await requestJSON(TEMPLATE_API_BASE + encodeURIComponent(FF_ALIAS) + '/' + tplId, {
                method: 'PUT',
                body: JSON.stringify({ snapshot: snapshot })
            });
            if (data.success) {
                delete _templateDetailCache[tplId];
                setTransientStatus(statusEl, '已覆盖', '#28a745');
                await loadTemplateList();
            } else {
                setTransientStatus(statusEl, '覆盖失败', '#d40000');
            }
        } catch (e) {
            setTransientStatus(statusEl, '网络错误', '#d40000');
        }
    }

    // ── 加载单个模板 ──────────────────────────────────────────────────────
    async function loadTemplate(tplId) {
        const statusEl = templateStatusEl();
        setTransientStatus(statusEl, '加载中...', '#0078d4', 60000);
        try {
            const scrollX = window.scrollX;
            const scrollY = window.scrollY;
            const template = await fetchTemplateDetail(tplId);
            await applySnapshot(template.snapshot, tplId);
            rememberLoadedTemplateName(template.name);
            requestAnimationFrame(function() { window.scrollTo(scrollX, scrollY); });
            setTransientStatus(statusEl, '已加载', '#28a745');
            // 关闭抽屉
            const drawer = document.getElementById('global-tpl-drawer');
            if (drawer) drawer.classList.remove('open');
            const badge = document.getElementById('user-badge');
            if (badge) badge.style.display = '';
        } catch (e) {
            setTransientStatus(statusEl, '网络错误', '#d40000');
        }
    }

    // ── 删除模板 ──────────────────────────────────────────────────────────
    async function deleteTemplate(tplId) {
        if (!confirm('确定要删除此模板吗？')) return;
        const statusEl = templateStatusEl();
        try {
            const data = await requestJSON(TEMPLATE_API_BASE + encodeURIComponent(FF_ALIAS) + '/' + tplId, { method: 'DELETE' });
            if (data.success) {
                delete _templateDetailCache[tplId];
                setTransientStatus(statusEl, '已删除', '#28a745');
                await loadTemplateList();
            } else {
                setTransientStatus(statusEl, '删除失败', '#d40000');
            }
        } catch (e) {
            setTransientStatus(statusEl, '网络错误', '#d40000');
        }
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ── 初始化 ────────────────────────────────────────────────────────────
    function initGlobalTemplateModule() {
        const saveBtn = document.getElementById('global-tpl-save-btn');
        if (saveBtn) saveBtn.onclick = saveTemplate;

        // 抽屉打开时加载模板列表
        const drawer = document.getElementById('global-tpl-drawer');
        if (drawer) {
            const observer = new MutationObserver(() => {
                if (drawer.classList.contains('open')) {
                    loadTemplateList();
                }
            });
            observer.observe(drawer, { attributes: true, attributeFilter: ['class'] });
            // 如果绑定 observer 时抽屉已处于打开状态（脚本加载慢，用户先点了），立即加载
            if (drawer.classList.contains('open')) {
                loadTemplateList();
            }
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initGlobalTemplateModule);
    } else {
        initGlobalTemplateModule();
    }

    // 暴露给外部
    window._collectSnapshot = collectSnapshot;
    window._applySnapshot = applySnapshot;
    window._loadGlobalTemplateList = loadTemplateList;
})();
