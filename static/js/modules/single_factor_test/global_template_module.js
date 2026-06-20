/**
 * 单因子测试的因子家族设置模板模块。
 * 保存/加载当前因子家族的测试设置：参数、时间范围、品种分类、收益率频率、分组测试设置。
 *
 * ── Snapshot Registry（快照注册表）─────────────────────────────────────
 * 扩展方式：调用 window._snapshotRegistry.register({ key, order, label, icon,
 *   collect(), apply(data, ctx), summarize(data) })
 * - key:       快照字段名（如 "params", "group_settings"）
 * - order:     应用顺序（数字越小越先 apply），默认 100
 * - label:     摘要行中文标签
 * - icon:      摘要行 emoji 图标
 * - collect(): 返回当前模块状态的纯数据对象（同步或 async）
 * - apply():   接收快照数据 + ctx{tplId, oldToNewTesterId}，恢复到页面（同步或 async）
 * - summarize(): 接收快照数据，返回摘要字符串（或字符串数组，多行展示）
 */
(function() {
    const FF_ALIAS = window.factorFamilyAlias || '';
    const TEMPLATE_API_BASE = '/api/single_factor_setting_templates/';
    var _templateListRequest = null;
    var _templateDetailCache = {};

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

    function _normalizeSubmissionForTemplate(s) {
        var paths = _asArray(s && (s.selected_paths || s.paths)).slice();
        return {
            id: s && s.id,
            label: (s && s.label) || '',
            product_group: (s && s.product_group) || '',
            paths: paths.slice(),
            selected_paths: paths.slice(),
            factor_tester_name: (s && (s.factor_tester_name || s.name)) || '',
            factor_tester_serial: (s && s.factor_tester_serial) || '',
            product_count: (s && s.product_count) || 0,
            products: _asArray(s && s.products).slice()
        };
    }

    function _normalizeServerSubmission(s) {
        var paths = _asArray(s && (s.selected_paths || s.paths)).slice();
        return {
            id: s && s.id,
            label: (s && s.label) || '',
            product_group: (s && s.product_group) || '',
            paths: paths.slice(),
            selected_paths: paths.slice(),
            pathsDescMap: {},
            factor_tester_name: (s && (s.name || s.factor_tester_name)) || '',
            factor_tester_serial: (s && s.factor_tester_serial) || '',
            product_count: (s && s.product_count) || 0,
            products: _asArray(s && s.products).slice(),
            count_desc: ((s && s.product_count) || 0) + ' 个产品',
            timestamp: '',
            start_date: '',
            end_date: '',
            start_time: '',
            end_time: ''
        };
    }

    function _submissionTitle(s, index) {
        return _firstNonEmpty([
            s && s.product_group,
            s && s.label,
            s && s.factor_tester_serial,
            s && s.id
        ], '#' + (index + 1));
    }

    function _findCreatedSubmission(serverSubs, expectedId, oldSub, usedIds) {
        var subs = _asArray(serverSubs);
        var expected = expectedId !== undefined && expectedId !== null ? String(expectedId) : '';
        for (var i = 0; i < subs.length; i++) {
            if (subs[i] && String(subs[i].id) === expected) return subs[i];
        }
        var oldPaths = JSON.stringify(_asArray(oldSub && (oldSub.selected_paths || oldSub.paths)).slice().sort());
        var oldName = (oldSub && (oldSub.product_group || oldSub.label)) || '';
        for (var j = subs.length - 1; j >= 0; j--) {
            var candidate = subs[j];
            if (!candidate || !candidate.id || usedIds[String(candidate.id)]) continue;
            var candPaths = JSON.stringify(_asArray(candidate.selected_paths || candidate.paths).slice().sort());
            var candName = candidate.product_group || candidate.label || '';
            if (candPaths === oldPaths && (!oldName || !candName || oldName === candName)) return candidate;
        }
        for (var k = subs.length - 1; k >= 0; k--) {
            if (subs[k] && subs[k].id && !usedIds[String(subs[k].id)]) return subs[k];
        }
        return null;
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

    // ── 1. time_data (order=10, 最先：影响 tester 创建) ──
    SnapshotRegistry.register({
        key: 'time_data',
        order: 10,
        label: '时间范围',
        icon: '📅',
        collect: function() {
            var sY = document.getElementById('start_year');
            var sM = document.getElementById('start_month');
            var sD = document.getElementById('start_day');
            var sH = document.getElementById('start_hour');
            var sMin = document.getElementById('start_minute');
            var eY = document.getElementById('end_year');
            var eM = document.getElementById('end_month');
            var eD = document.getElementById('end_day');
            var eH = document.getElementById('end_hour');
            var eMin = document.getElementById('end_minute');
            var isTd = document.getElementById('is_trading_day');
            var isCfd = document.getElementById('is_cn_futures_day');
            var isCfn = document.getElementById('is_cn_futures_night');
            var tz = document.getElementById('timezone_input');
            var pad = function(n) { return (parseInt(n) < 10 ? '0' : '') + parseInt(n); };
            return {
                start_date: sY ? sY.value + '-' + pad(sM?.value||1) + '-' + pad(sD?.value||1) : '',
                start_time: sH ? pad(sH?.value||9) + ':' + pad(sMin?.value||0) : '09:00',
                end_date: eY ? (eY.value||(sY?sY.value:'')) + '-' + pad(eM?.value||1) + '-' + pad(eD?.value||1) : '',
                end_time: eH ? pad(eH?.value||15) + ':' + pad(eMin?.value||0) : '15:00',
                is_trading_day: isTd ? isTd.checked : false,
                is_cn_futures_day: isCfd ? isCfd.checked : false,
                is_cn_futures_night: isCfn ? isCfn.checked : false,
                timezone: tz ? tz.value : 'Asia/Shanghai',
                start: '', end: ''
            };
        },
        apply: async function(td) {
            var setVal = function(id, val) { var el = document.getElementById(id); if (el && val !== null && val !== undefined) el.value = val; };
            if (td.start_date) { var parts = td.start_date.split('-'); setVal('start_year', parts[0]); setVal('start_month', parts[1]); setVal('start_day', parts[2]); }
            if (td.start_time) { var parts = td.start_time.split(':'); setVal('start_hour', parts[0]); setVal('start_minute', parts[1]); }
            if (td.end_date) { var parts = td.end_date.split('-'); setVal('end_year', parts[0]); setVal('end_month', parts[1]); setVal('end_day', parts[2]); }
            if (td.end_time) { var parts = td.end_time.split(':'); setVal('end_hour', parts[0]); setVal('end_minute', parts[1]); }
            setVal('timezone_input', td.timezone);
            var isTdCb = document.getElementById('is_trading_day');
            var isCfdCb = document.getElementById('is_cn_futures_day');
            var isCfnCb = document.getElementById('is_cn_futures_night');
            if (isTdCb) isTdCb.checked = !!td.is_trading_day;
            if (isCfdCb) isCfdCb.checked = !!td.is_cn_futures_day;
            if (isCfnCb) isCfnCb.checked = !!td.is_cn_futures_night;
            var timeDisabled = !!(td.is_trading_day || td.is_cn_futures_day || td.is_cn_futures_night);
            [document.getElementById('start_hour'), document.getElementById('start_minute'),
             document.getElementById('end_hour'), document.getElementById('end_minute')].forEach(function(el) {
                if (el) { el.disabled = timeDisabled; el.style.background = timeDisabled ? '#ccc' : '#eee'; }
            });
            var currentSettingsSpan = document.getElementById('current_settings');
            if (currentSettingsSpan) {
                var padFn = function(n) { n = parseInt(n); return n < 10 ? '0' + n : String(n); };
                var sy = document.getElementById('start_year')?.value || '';
                var sm = padFn(document.getElementById('start_month')?.value || 1);
                var sd = padFn(document.getElementById('start_day')?.value || 1);
                var sh = padFn(document.getElementById('start_hour')?.value || 0);
                var smin = padFn(document.getElementById('start_minute')?.value || 0);
                var ey = document.getElementById('end_year')?.value || '';
                var em = padFn(document.getElementById('end_month')?.value || 1);
                var ed = padFn(document.getElementById('end_day')?.value || 1);
                var eh = padFn(document.getElementById('end_hour')?.value || 0);
                var emin = padFn(document.getElementById('end_minute')?.value || 0);
                var suffix = td.is_trading_day ? ' (交易日)' : (td.is_cn_futures_day ? ' (期货日盘)' : (td.is_cn_futures_night ? ' (期货夜盘)' : ''));
                currentSettingsSpan.innerText = '起始时间: ' + sy + '-' + sm + '-' + sd + ' ' + sh + ':' + smin + ', 终末时间: ' + ey + '-' + em + '-' + ed + ' ' + eh + ':' + emin + suffix;
            }
            if (typeof updateTimeSummary === 'function') updateTimeSummary();
            try {
                var resp = await fetch('/set_time_range', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ factor_family_alias: FF_ALIAS, page_uuid: window._pageUuid || '', start_date: td.start_date || '', start_time: td.start_time || '09:00', end_date: td.end_date || '', end_time: td.end_time || '15:00', is_trading_day: td.is_trading_day || false, is_cn_futures_day: td.is_cn_futures_day || false, is_cn_futures_night: td.is_cn_futures_night || false, timezone: td.timezone || 'Asia/Shanghai' })
                });
                var data = await resp.json();
                if (data.page_uuid) window._pageUuid = data.page_uuid;
            } catch (e) { console.error('恢复时间范围失败:', e); }
        },
        summarize: function(td) {
            var mode = td.is_trading_day ? '交易日' : (td.is_cn_futures_day ? '期货日盘' : (td.is_cn_futures_night ? '期货夜盘' : '自然时间'));
            return [
                '起始: ' + _formatDateTime(td.start_date, td.start_time),
                '终止: ' + _formatDateTime(td.end_date, td.end_time),
                '时区: ' + (td.timezone || 'Asia/Shanghai') + ' · ' + mode
            ];
        }
    });

    // ── 2. params_list (order=20, 在 time_data 之后) ──
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

    // ── 3. submissions (order=30, 在参数之后) ──
    SnapshotRegistry.register({
        key: 'submissions',
        order: 30,
        label: '产品类别筛选',
        icon: '🌳',
        collect: function() {
            var raw = (window._getCurrentSubmissions) ? window._getCurrentSubmissions() : [];
            // 返回深拷贝，避免引用共享 + 按 id 去重
            var seen = {};
            var deduped = [];
            for (var i = 0; i < raw.length; i++) {
                var s = _normalizeSubmissionForTemplate(raw[i]);
                var sid = s.id;
                if (!sid || seen[sid]) continue;
                seen[sid] = true;
                deduped.push(s);
            }
            return deduped;
        },
        apply: async function(subs, ctx) {
            ctx = ctx || {};
            var savedSubs = _asArray(subs);
            var oldToNewTesterId = {};
            var latestServerSubmissions = [];

            // 先清空
            try {
                var clearResp = await fetch('/clear_all_submissions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ page_uuid: window._pageUuid || '' }) });
                var clearData = await clearResp.json();
                if (clearData && clearData.submissions) latestServerSubmissions = clearData.submissions;
                if (typeof window._applySubmissions === 'function') window._applySubmissions([]);
            } catch (e) { console.error('清空旧测试器失败:', e); }
            if (!savedSubs.length) {
                ctx.oldToNewTesterId = oldToNewTesterId;
                ctx.newSubmissions = [];
                return { oldToNewTesterId: oldToNewTesterId, submissions: [] };
            }

            var usedNewIds = {};
            for (var i = 0; i < savedSubs.length; i++) {
                var sub = _normalizeSubmissionForTemplate(savedSubs[i]);
                var paths = sub.selected_paths || sub.paths || [];
                if (!paths.length) continue;
                var id_time = 'tpl-' + Date.now() + '-' + i;
                try {
                    var resp = await fetch('/submit_selected_products', {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ selected_paths: paths, id_time: id_time, group_name: sub.product_group || '', page_uuid: window._pageUuid || '' })
                    });
                    var result = await resp.json();
                    if (result.success) {
                        latestServerSubmissions = result.submissions || latestServerSubmissions;
                        var created = _findCreatedSubmission(latestServerSubmissions, id_time, sub, usedNewIds);
                        var newId = created && created.id ? String(created.id) : String(id_time);
                        if (sub.id) oldToNewTesterId[String(sub.id)] = newId;
                        usedNewIds[newId] = true;
                        if (sub.label) {
                            try {
                                var renameResp = await fetch('/rename_submission', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id_time: newId, new_name: sub.label, page_uuid: window._pageUuid || '' }) });
                                var renameData = await renameResp.json();
                                if (renameData && renameData.submissions) latestServerSubmissions = renameData.submissions;
                            } catch (e) {}
                        }
                    }
                } catch (e) { console.error('重新提交测试器失败:', sub.id, e); }
            }
            try {
                var listResp = await fetch('/api/list_submissions?page_uuid=' + encodeURIComponent(window._pageUuid || ''));
                var listData = await listResp.json();
                if (listData.success && listData.submissions) latestServerSubmissions = listData.submissions;
            } catch (e) {}
            var normalized = _asArray(latestServerSubmissions).map(_normalizeServerSubmission);
            if (latestServerSubmissions && typeof window._applySubmissions === 'function') {
                window._applySubmissions(normalized);
            }
            ctx.oldToNewTesterId = oldToNewTesterId;
            ctx.newSubmissions = normalized;
            return { oldToNewTesterId: oldToNewTesterId, submissions: normalized };
        },
        summarize: function(subs) {
            return _asArray(subs).map(function(s, idx) {
                var paths = _asArray(s.selected_paths || s.paths);
                var count = s.product_count ? (s.product_count + ' 个产品') : '产品数待计算';
                var pathText = paths.length ? ('路径: ' + paths.join('；')) : '未选择路径';
                return _submissionTitle(s, idx) + ' · ' + count + ' · ' + pathText;
            });
        }
    });

    // ── 4. return_freqs (order=40) ──
    SnapshotRegistry.register({
        key: 'return_freqs',
        order: 40,
        label: '收益率频率',
        icon: '📈',
        collect: function() {
            var rows = document.querySelectorAll('#ic-freq-table-body tr');
            var result = [];
            rows.forEach(function(row) {
                var cb = row.querySelector('.factor-checkbox');
                var inp = row.querySelector('.factor-return-freq-input');
                if (cb) result.push({ alias: cb.getAttribute('data-factor-alias'), checked: cb.checked, return_freq: inp ? inp.value.trim() : '' });
            });
            return result;
        },
        apply: function(freqs) {
            if (!freqs || freqs.length === 0) return;
            freqs.forEach(function(fr) {
                var cb = document.querySelector('#ic-freq-table-body .factor-checkbox[data-factor-alias="' + fr.alias + '"]');
                var inp = document.querySelector('#ic-freq-table-body .factor-return-freq-input[data-factor-alias="' + fr.alias + '"]');
                if (cb) cb.checked = fr.checked !== false;
                if (inp) inp.value = fr.return_freq || '';
            });
            var tbody = document.getElementById('ic-freq-table-body');
            if (tbody) tbody.querySelectorAll('.factor-return-freq-input').forEach(function(inp) { inp.dispatchEvent(new Event('input', { bubbles: true })); });
        },
        summarize: function(freqs) {
            var checked = freqs.filter(function(f) { return f.checked; });
            return checked.map(function(f) { return (f.alias || '未命名因子') + ' · 收益率频率 ' + (f.return_freq || '未设置'); });
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

        // 6. group_settings (order=50, 依赖 submissions 的 testerId 重映射)
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
                    var oldToNew = (ctx && ctx.oldToNewTesterId) ? ctx.oldToNewTesterId : {};
                    var remappedCount = 0;
                    var unmappedCount = 0;
                    if (working && working.groups) {
                        var curSubs = (typeof window._getCurrentSubmissions === 'function') ? window._getCurrentSubmissions() : (window.submissions || []);
                        var fallbackNewId = (curSubs.length === 1 && curSubs[0].id) ? String(curSubs[0].id) : null;
                        working.groups.forEach(function(g) {
                            if (g.testerId && oldToNew.hasOwnProperty(String(g.testerId))) {
                                g.testerId = oldToNew[String(g.testerId)];
                                remappedCount++;
                            } else if (g.testerId && fallbackNewId) {
                                g.testerId = fallbackNewId;
                                remappedCount++;
                            } else if (g.testerId) {
                                unmappedCount++;
                            }
                        });
                        if (unmappedCount > 0) {
                            console.warn('[global_template] group_settings: ' + unmappedCount + ' groups have unmapped testerId (oldToNew keys: ' + Object.keys(oldToNew).length + ', fallback: ' + (fallbackNewId || 'none') + ')');
                        }
                    }
                    var applyResult = base.apply(working);
                    if (applyResult.errors && applyResult.errors.length > 0) {
                        console.warn('[global_template] group_settings apply warnings:', applyResult.errors);
                    }
                    console.log('[global_template] group_settings applied: ' + (applyResult.applied ? applyResult.applied.groups : '?') + ' groups, ' + remappedCount + ' remapped');
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
                order: LS.order,
                label: LS.label,
                icon: LS.icon,
                collect: LS.collect,
                apply: function(localSettings) {
                    var result = LS.apply(_deepClone(localSettings) || {});
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
        _commitGroupConfigDirty();
        return await SnapshotRegistry.collectAll();
    }

    // ── 应用快照（通过注册表，按 order 顺序） ───────────────────────────
    // tplId: 因子家族设置模板 ID
    async function applySnapshot(snapshot, tplId) {
        if (!snapshot) return;
        await _ensureGroupTestAdapters();

        // 构建 ctx：供注册项间传递数据（如 testerId 重映射）
        var ctx = { tplId: tplId };

        // 在 apply submissions 之后，构建 oldToNewTesterId 映射供 group_settings 使用
        // 这是跨注册项的依赖：group_settings(50) 依赖 submissions(30) 重映射后的 testerId
        // 通过 ctx 传递
        var subsEntry = SnapshotRegistry._registryByKey['submissions'];
        var hasSubsKey = _hasOwn(snapshot, 'submissions') && Array.isArray(snapshot.submissions);
        var hasGroups = _hasGroupSettingsSnapshot(snapshot.group_settings);

        if (hasSubsKey && subsEntry) {
            // 先恢复 time/params 等上游状态，确保 tester 重建时使用模板中的时间范围和参数。
            await _applyEntriesWhere(snapshot, ctx, function(entry) {
                return entry.key !== 'submissions' && entry.order < subsEntry.order;
            });
            // submissions 是 tester 的权威快照：随后清空旧 tester，再逐条重建并生成旧→新 ID 映射。
            await _applySubmissionsWithRemapping(snapshot.submissions || [], snapshot, ctx);
            // 最后恢复依赖 testerId 映射的模块（尤其 group_settings）。
            await _applyEntriesWhere(snapshot, ctx, function(entry) {
                return entry.key !== 'submissions' && entry.order > subsEntry.order;
            });
        } else {
            // 没有保存 submissions 的旧模板不主动删除当前 tester；但若也没有分组配置，就清空分组 UI 状态。
            if (!hasGroups) _clearGroupTestData();
            await SnapshotRegistry.applyAll(snapshot, ctx);
        }

        refreshOuterSummaries();
    }

    function _commitGroupConfigDirty() {
        try {
            var reg = window.GT_CONFIG_REGISTRY;
            if (reg && typeof reg.hasDirty === 'function' && reg.hasDirty() && typeof reg.commitDirty === 'function') {
                reg.commitDirty();
            }
        } catch (e) {
            console.warn('[global_template] commit group config dirty failed:', e);
        }
    }

    /** 专门处理 submissions apply + testerId 重映射 */
    async function _applySubmissionsWithRemapping(subs, snapshot, ctx) {
        // 记录旧的 submission ids 及其 product_group/label（用于匹配）
        var oldSubs = snapshot.submissions || [];

        // 先执行 submissions apply（清空 + 重建）
        var subsEntry = SnapshotRegistry._registryByKey['submissions'];
        var applyResult = null;
        if (subsEntry) {
            applyResult = await subsEntry.apply(subs, ctx);
        }
        if (applyResult && applyResult.oldToNewTesterId && Object.keys(applyResult.oldToNewTesterId).length > 0) {
            ctx.oldToNewTesterId = applyResult.oldToNewTesterId;
            return;
        }

        // apply 返回了空的 oldToNewTesterId 映射（submissions 重建可能失败），
        // 回到兜底逻辑按位置/product_group 匹配
        console.warn('[global_template] submissions apply returned empty oldToNewTesterId, falling back to position/label matching');

        // 构建 oldTesterId → newTesterId 映射
        // 优先按数组位置，兜底按 product_group/label 匹配
        var curSubmissions = (typeof window._getCurrentSubmissions === 'function') ? window._getCurrentSubmissions() : (window.submissions || []);
        var oldToNewTesterId = {};

        // 第一遍：按位置匹配
        for (var mi = 0; mi < oldSubs.length && mi < curSubmissions.length; mi++) {
            var oldId = oldSubs[mi].id;
            var newId = (curSubmissions[mi] && curSubmissions[mi].id) ? curSubmissions[mi].id : null;
            if (oldId && newId) {
                oldToNewTesterId[String(oldId)] = String(newId);
            }
        }

        // 第二遍：对未匹配的旧 submission，按 product_group/label 查找
        for (var oi = 0; oi < oldSubs.length; oi++) {
            var os = oldSubs[oi];
            var oid = String(os.id);
            if (oldToNewTesterId[oid]) continue; // 已匹配
            var oldGroup = os.product_group || os.label || '';
            if (!oldGroup) continue;
            for (var ci = 0; ci < curSubmissions.length; ci++) {
                var cs = curSubmissions[ci];
                var cid = String(cs.id);
                // 避免一个 newId 被匹配多次
                var alreadyUsed = false;
                var keys = Object.keys(oldToNewTesterId);
                for (var ki = 0; ki < keys.length; ki++) {
                    if (oldToNewTesterId[keys[ki]] === cid) { alreadyUsed = true; break; }
                }
                if (alreadyUsed) continue;
                var curGroup = cs.product_group || cs.label || '';
                if (oldGroup === curGroup) {
                    oldToNewTesterId[oid] = cid;
                    break;
                }
            }
        }

        ctx.oldToNewTesterId = oldToNewTesterId;
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
        const statusEl = document.getElementById('global-tpl-save-status');
        let name = (nameInput?.value || '').trim();
        if (!name) {
            // 默认使用当前时间戳
            const now = new Date();
            name = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')} ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
        }
        const snapshot = await collectSnapshot();

        statusEl.textContent = '保存中...';
        statusEl.style.color = '#0078d4';
        try {
            const resp = await fetch(TEMPLATE_API_BASE + encodeURIComponent(FF_ALIAS), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: name,
                    ff_alias: FF_ALIAS,
                    snapshot: snapshot
                })
            });
            const data = await resp.json();
            if (data.success) {
                statusEl.textContent = '✓ 已保存: ' + name;
                statusEl.style.color = '#28a745';
                if (nameInput) nameInput.value = '';
                await loadTemplateList();
            } else {
                statusEl.textContent = '✗ 保存失败: ' + (data.error || '未知错误');
                statusEl.style.color = '#d40000';
            }
        } catch (e) {
            statusEl.textContent = '✗ 网络错误: ' + e.message;
            statusEl.style.color = '#d40000';
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
            const resp = await fetch(TEMPLATE_API_BASE + encodeURIComponent(FF_ALIAS));
            const data = await resp.json();
            if (!data.success || !data.templates || data.templates.length === 0) {
                listEl.innerHTML = '<div style="color:#888;text-align:center;padding:10px;">暂无已保存的模板</div>';
                return;
            }
            let html = '';
            data.templates.forEach(tpl => {
                const tplId = tpl.id;

                html += `
                <div class="tpl-row" style="border-bottom:1px solid #eef2f7;">
                    <div class="tpl-row-header" data-tpl-id="${tplId}" style="display:flex;align-items:center;justify-content:space-between;padding:8px 10px;gap:8px;">
                        <div class="tpl-name-area" style="flex:1;min-width:0;cursor:pointer;">
                            <div style="font-size:13px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(tpl.name)}</div>
                            <div style="font-size:11px;color:#888;">${escapeHtml(tpl.ff_alias || '')}</div>
                        </div>
                        <span class="tpl-expand-icon" style="font-size:11px;color:#888;transition:transform 0.2s;cursor:pointer;">▼</span>
                        <button class="btn btn-sm btn-outline-primary global-tpl-load-btn" data-tpl-id="${tplId}" style="flex-shrink:0;font-size:12px;padding:3px 10px;">加载</button>
                        <button class="btn btn-sm global-tpl-overwrite-btn" data-tpl-id="${tplId}" data-tpl-name="${escapeHtml(tpl.name)}" style="flex-shrink:0;font-size:12px;padding:3px 10px;color:#7a4b00;border:1px solid #f5c26b;background:#fff8e6;border-radius:4px;cursor:pointer;">覆盖</button>
                        <button class="btn btn-sm global-tpl-delete-btn" data-tpl-id="${tplId}" style="flex-shrink:0;font-size:12px;padding:3px 10px;color:#d40000;border:1px solid #faa;background:transparent;border-radius:4px;cursor:pointer;">删除</button>
                    </div>
                    <div class="tpl-row-detail" data-loaded="false" style="display:none;padding:6px 10px 10px 10px;background:#f8fafc;">
                        <div style="font-size:11px;color:#999;padding:4px 0;">展开后加载详情</div>
                    </div>
                </div>`;
            });
            listEl.innerHTML = html;
            // 展开/收起：点击名称区域或展开图标
            listEl.querySelectorAll('.tpl-row-header').forEach(function(header) {
                var nameArea = header.querySelector('.tpl-name-area');
                var expandIcon = header.querySelector('.tpl-expand-icon');
                async function toggleDetail(e) {
                    if (e) e.stopPropagation();
                    var detail = header.nextElementSibling;
                    if (detail.style.display === 'none') {
                        detail.style.display = 'block';
                        expandIcon.style.transform = 'rotate(180deg)';
                        if (detail.getAttribute('data-loaded') !== 'true') {
                            detail.innerHTML = '<div style="font-size:11px;color:#888;padding:4px 0;">加载中...</div>';
                            try {
                                var template = await fetchTemplateDetail(header.getAttribute('data-tpl-id'));
                                await _ensureGroupTestAdapters();
                            var summaryHtml = SnapshotRegistry.summarizeAll(template.snapshot || {});
                                detail.innerHTML = summaryHtml || '<div style="font-size:11px;color:#999;padding:4px 0;">无设置信息</div>';
                                detail.setAttribute('data-loaded', 'true');
                            } catch (err) {
                                detail.innerHTML = '<div style="font-size:11px;color:#d40000;padding:4px 0;">详情加载失败: ' + escapeHtml(err.message) + '</div>';
                            }
                        }
                    } else {
                        detail.style.display = 'none';
                        expandIcon.style.transform = 'rotate(0deg)';
                    }
                }
                if (nameArea) nameArea.addEventListener('click', toggleDetail);
                if (expandIcon) expandIcon.addEventListener('click', toggleDetail);
            });
            // 绑定加载按钮（阻止冒泡，避免触发展开/收起）
            listEl.querySelectorAll('.global-tpl-load-btn').forEach(btn => {
                btn.addEventListener('click', function(e) {
                    e.stopPropagation();
                    loadTemplate(this.getAttribute('data-tpl-id'));
                });
            });
            // 绑定覆盖按钮（用当前页面设置覆盖已有模板）
            listEl.querySelectorAll('.global-tpl-overwrite-btn').forEach(btn => {
                btn.addEventListener('click', function(e) {
                    e.stopPropagation();
                    overwriteTemplate(this.getAttribute('data-tpl-id'), this.getAttribute('data-tpl-name'));
                });
            });
            // 绑定删除按钮（阻止冒泡）
            listEl.querySelectorAll('.global-tpl-delete-btn').forEach(btn => {
                btn.addEventListener('click', function(e) {
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
        _templateDetailCache[tplId] = fetch(TEMPLATE_API_BASE + encodeURIComponent(FF_ALIAS) + '/' + tplId)
            .then(function(resp) { return resp.json(); })
            .then(function(data) {
                if (!data.success || !data.template) {
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

    // ── 覆盖已有模板 ──────────────────────────────────────────────────────
    async function overwriteTemplate(tplId, tplName) {
        if (!confirm('用当前设置覆盖模板「' + (tplName || tplId) + '」？')) return;
        const statusEl = document.getElementById('global-tpl-load-status');
        statusEl.textContent = '覆盖中...';
        statusEl.style.color = '#7a4b00';
        try {
            const snapshot = await collectSnapshot();
            const resp = await fetch(TEMPLATE_API_BASE + encodeURIComponent(FF_ALIAS) + '/' + tplId, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ snapshot: snapshot })
            });
            const data = await resp.json();
            if (data.success) {
                delete _templateDetailCache[tplId];
                statusEl.textContent = '✓ 已覆盖: ' + (tplName || tplId);
                statusEl.style.color = '#28a745';
                await loadTemplateList();
            } else {
                statusEl.textContent = '✗ 覆盖失败: ' + (data.error || '未知错误');
                statusEl.style.color = '#d40000';
            }
        } catch (e) {
            statusEl.textContent = '✗ 网络错误: ' + e.message;
            statusEl.style.color = '#d40000';
        }
    }

    // ── 加载单个模板 ──────────────────────────────────────────────────────
    async function loadTemplate(tplId) {
        const statusEl = document.getElementById('global-tpl-load-status');
        statusEl.textContent = '加载中...';
        statusEl.style.color = '#0078d4';
        try {
            const template = await fetchTemplateDetail(tplId);
            await applySnapshot(template.snapshot, tplId);
            statusEl.textContent = '✓ 已加载: ' + template.name;
            statusEl.style.color = '#28a745';
            // 关闭抽屉
            const drawer = document.getElementById('global-tpl-drawer');
            if (drawer) drawer.classList.remove('open');
            const badge = document.getElementById('user-badge');
            if (badge) badge.style.display = '';
        } catch (e) {
            statusEl.textContent = '✗ 网络错误: ' + e.message;
            statusEl.style.color = '#d40000';
        }
    }

    // ── 删除模板 ──────────────────────────────────────────────────────────
    async function deleteTemplate(tplId) {
        if (!confirm('确定要删除此模板吗？')) return;
        const statusEl = document.getElementById('global-tpl-load-status');
        try {
            const resp = await fetch(TEMPLATE_API_BASE + encodeURIComponent(FF_ALIAS) + '/' + tplId, { method: 'DELETE' });
            const data = await resp.json();
            if (data.success) {
                delete _templateDetailCache[tplId];
                statusEl.textContent = '✓ 已删除';
                statusEl.style.color = '#28a745';
                await loadTemplateList();
            } else {
                statusEl.textContent = '✗ 删除失败: ' + (data.error || '未知错误');
                statusEl.style.color = '#d40000';
            }
        } catch (e) {
            statusEl.textContent = '✗ 网络错误: ' + e.message;
            statusEl.style.color = '#d40000';
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

    // ── Submission bus subscriptions ────────────────────────────────────────────
    (function() {
        var bus = window._submissionBus;
        if (!bus) return;

        // React to any change: refresh outer summaries
        bus.on('*', function(event) {
            refreshOuterSummaries();
        });
    })();

    // 暴露给外部
    window._collectSnapshot = collectSnapshot;
    window._applySnapshot = applySnapshot;
})();
