/**
 * parameter_module.js
 * 共享参数模块 — 处理因子参数的增删改、拖拽排序、自动同步后端。
 *
 * 后端 API：
 *   POST /add_params     — 添加一组参数值
 *   POST /delete_params  — 删除指定行参数
 *   POST /reorder_params — 拖拽排序参数行
 *
 * 数据流：
 *   前端操作 → fetch API → 后端 session 存储 → 返回更新后的 factor_rows → 重新渲染
 */
(function() {
    function initParameterModule() {
        const moduleElem = document.getElementById('parameter_module');
        if (!moduleElem) return;

        const tbody = document.getElementById('factor_table_body');
        const factorAlias = moduleElem.getAttribute('data-factor-alias');
        const factorType = moduleElem.getAttribute('data-factor-type') || 'public';

        let paramAliases = [];
        const aliasesAttr = moduleElem.getAttribute('data-param-aliases');
        if (aliasesAttr) {
            try {
                paramAliases = JSON.parse(aliasesAttr);
            } catch(e) {
                console.error('Failed to parse param-aliases:', e);
            }
        }

        let paramMetas = [];
        const metasAttr = moduleElem.getAttribute('data-param-metas');
        if (metasAttr) {
            try {
                paramMetas = JSON.parse(metasAttr);
            } catch(e) {
                console.error('Failed to parse param-metas:', e);
            }
        }

        // 构建 URL 查询参数
        function _buildFactorUrl(alias) {
            var params = '?factor=' + encodeURIComponent(alias);
            if (factorType === 'custom') {
                params += '&type=custom';
            }
            return params;
        }

        function _escapeHtml(str) {
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        function getParamMeta(alias) {
            return (paramMetas || []).find(function(p) { return p.alias === alias; }) || {};
        }

        function getFactorProductGroup(item) {
            return item.product_group || item.scope_key || 'default';
        }

        function formatProductGroupLabel(productGroup) {
            return (!productGroup || productGroup === 'default' || productGroup === '默认') ? '默认产品组' : productGroup;
        }

        function readParamControl(alias) {
            const control = document.getElementById('param_' + alias);
            if (!control) return '';
            const meta = getParamMeta(alias);
            if (meta.input_mode === 'enum_custom' && control.value === '__custom__') {
                const custom = document.getElementById('param_custom_' + alias);
                return custom ? custom.value : '';
            }
            return control.value;
        }

        function writeParamControl(alias, value) {
            const control = document.getElementById('param_' + alias);
            if (!control) return;
            const meta = getParamMeta(alias);
            const options = Array.isArray(meta.options) ? meta.options : [];
            const values = options.map(function(opt) { return String(opt.value); });
            if (meta.input_mode === 'enum_custom' && values.indexOf(String(value)) === -1) {
                control.value = '__custom__';
                const custom = document.getElementById('param_custom_' + alias);
                if (custom) {
                    custom.value = value || '';
                    custom.style.display = '';
                }
                return;
            }
            control.value = value;
            const custom = document.getElementById('param_custom_' + alias);
            if (custom) custom.style.display = 'none';
        }

        let factorParamPickerTarget = '';
        let factorParamPickerItems = [];
        let factorParamPickerSetter = null;

        function ensureFactorParamPicker() {
            let overlay = document.getElementById('factor-param-picker-overlay');
            if (overlay) return overlay;
            overlay = document.createElement('div');
            overlay.id = 'factor-param-picker-overlay';
            overlay.style.cssText = 'display:none;position:fixed;inset:0;z-index:3000;background:rgba(15,23,42,.35);align-items:center;justify-content:center;padding:24px;';
            overlay.innerHTML = '<div style="width:min(980px,96vw);max-height:86vh;background:#fff;border-radius:8px;box-shadow:0 18px 48px rgba(15,23,42,.25);display:flex;flex-direction:column;overflow:hidden;">' +
                '<div style="display:flex;align-items:center;gap:12px;padding:14px 18px;border-bottom:1px solid #e5e7eb;">' +
                '<strong style="font-size:16px;">选择因子</strong>' +
                '<input id="factor-param-picker-search" type="search" placeholder="搜索因子/家族/参数/用户" style="flex:1;min-width:180px;">' +
                '<button type="button" class="param-btn" id="factor-param-picker-close">关闭</button>' +
                '</div><div id="factor-param-picker-body" style="overflow:auto;padding:14px 18px;"></div></div>';
            document.body.appendChild(overlay);
            overlay.addEventListener('click', function(e) {
                if (e.target === overlay || e.target.id === 'factor-param-picker-close') {
                    overlay.style.display = 'none';
                }
                const btn = e.target.closest('[data-factor-param-pick]');
                if (btn) {
                    const picked = btn.getAttribute('data-factor-param-pick') || '';
                    if (typeof factorParamPickerSetter === 'function') {
                        factorParamPickerSetter(picked);
                    } else {
                        writeParamControl(factorParamPickerTarget, picked);
                    }
                    overlay.style.display = 'none';
                }
            });
            overlay.querySelector('#factor-param-picker-search').addEventListener('input', renderFactorParamPickerItems);
            return overlay;
        }

        function renderFactorParamPickerItems() {
            const body = document.getElementById('factor-param-picker-body');
            const search = (document.getElementById('factor-param-picker-search')?.value || '').trim().toLowerCase();
            if (!body) return;
            const items = factorParamPickerItems.filter(function(item) {
                if (!search) return true;
                const haystack = [
                    item.factor_alias,
                    item.factor_family_alias,
                    item.factor_family_name,
                    item.chinese_name,
                    item.owner_alias,
                    item.owner_username,
                    item.product_group,
                    item.scope_key,
                    (item.params || []).map(function(p) { return p.alias + ':' + p.value; }).join(' '),
                ].join(' ').toLowerCase();
                return haystack.indexOf(search) !== -1;
            });
            if (!items.length) {
                body.innerHTML = '<div style="color:#888;text-align:center;padding:28px;">暂无可选因子。请先在因子库保存参数配置。</div>';
                return;
            }
            let html = '<table class="param-table" style="width:100%;"><thead><tr><th>因子</th><th>家族</th><th>参数</th><th>所有者</th><th>操作</th></tr></thead><tbody>';
            items.forEach(function(item) {
                const params = (item.params || []).map(function(p) {
                    return '<span style="display:inline-block;margin:1px 4px 1px 0;color:#667085;">' + _escapeHtml(p.alias) + ':' + _escapeHtml(p.value) + '</span>';
                }).join('');
                html += '<tr><td><strong>' + _escapeHtml(item.factor_alias || '') + '</strong></td>' +
                    '<td>' + _escapeHtml(item.factor_family_alias || item.factor_family_name || '') + '<div style="color:#888;font-size:12px;">' + _escapeHtml(item.chinese_name || '') + '</div></td>' +
                    '<td>' + (params || '<span style="color:#aaa;">无</span>') + '</td>' +
                    '<td>' + _escapeHtml(item.owner_alias || item.owner_username || '') + '</td>' +
                    '<td><button type="button" class="param-btn" data-factor-param-pick="' + _escapeHtml(item.factor_alias || '') + '">选择</button></td></tr>';
            });
            html += '</tbody></table>';
            body.innerHTML = html;
        }

        async function openFactorParamPicker(alias, setter) {
            factorParamPickerTarget = alias;
            factorParamPickerSetter = typeof setter === 'function' ? setter : null;
            const overlay = ensureFactorParamPicker();
            const body = document.getElementById('factor-param-picker-body');
            overlay.style.display = 'flex';
            if (body) body.innerHTML = '<div style="color:#888;text-align:center;padding:28px;">加载因子库...</div>';
            try {
                const resp = await fetch('/custom-factors/api/param-factor-overview?include_subordinates=1');
                const data = await resp.json();
                if (!data.success) throw new Error(data.error || '加载失败');
                factorParamPickerItems = data.factors || [];
                renderFactorParamPickerItems();
            } catch (e) {
                if (body) body.innerHTML = '<div style="color:#d40000;text-align:center;padding:28px;">加载失败: ' + _escapeHtml(e.message) + '</div>';
            }
        }
        window.openSharedFactorParamPicker = openFactorParamPicker;

        // ── 从因子库批量导入（多选版） ──────────────────────────────────────
        var multiImportItems = [];
        var multiImportChecked = {};

        function ensureMultiImportOverlay() {
            var ov = document.getElementById('factor-library-import-overlay');
            if (ov) return ov;
            ov = document.createElement('div');
            ov.id = 'factor-library-import-overlay';
            ov.style.cssText = 'display:none;position:fixed;inset:0;z-index:3100;background:rgba(15,23,42,.35);align-items:center;justify-content:center;padding:24px;';
            ov.innerHTML =
                '<div style="width:min(980px,96vw);max-height:86vh;background:#fff;border-radius:8px;box-shadow:0 18px 48px rgba(15,23,42,.25);display:flex;flex-direction:column;overflow:hidden;">' +
                '<div style="display:flex;align-items:center;gap:12px;padding:14px 18px;border-bottom:1px solid #e5e7eb;">' +
                '<strong style="font-size:16px;">从因子库导入参数</strong>' +
                '<input id="multi-import-search" type="search" placeholder="搜索因子/家族/参数/用户" style="flex:1;min-width:180px;">' +
                '<button type="button" class="param-btn" id="multi-import-toggle-all">全选</button>' +
                '<button type="button" id="multi-import-confirm" class="param-btn" style="background:#6c63ff;color:#fff;border:none;">确认导入</button>' +
                '<button type="button" class="param-btn" id="multi-import-close">关闭</button>' +
                '</div>' +
                '<div id="multi-import-body" style="overflow:auto;padding:14px 18px;"></div>' +
                '<div style="padding:8px 18px;border-top:1px solid #e5e7eb;font-size:11px;color:#888;text-align:right;">' +
                '已选择 <span id="multi-import-count">0</span> 个因子' +
                '</div></div>';
            document.body.appendChild(ov);

            ov.querySelector('#multi-import-close').addEventListener('click', function() {
                ov.style.display = 'none';
            });
            ov.addEventListener('click', function(e) {
                if (e.target === ov) ov.style.display = 'none';
            });

            ov.querySelector('#multi-import-search').addEventListener('input', renderMultiImportTable);

            var toggleAll = ov.querySelector('#multi-import-toggle-all');
            toggleAll.addEventListener('click', function() {
                var visible = getVisibleMultiImportItems();
                var allChecked = visible.every(function(item) { return !!(item._id && multiImportChecked[item._id]); });
                visible.forEach(function(item) {
                    if (item._id) multiImportChecked[item._id] = !allChecked;
                });
                renderMultiImportTable();
            });

            ov.querySelector('#multi-import-confirm').addEventListener('click', function() {
                var selected = multiImportItems.filter(function(item) {
                    return item._id && multiImportChecked[item._id];
                });
                if (!selected.length) { alert('请至少选择一个因子'); return; }
                ov.style.display = 'none';
                batchAddParams(selected);
            });

            return ov;
        }

        function getVisibleMultiImportItems() {
            var search = (document.getElementById('multi-import-search')?.value || '').trim().toLowerCase();
            return multiImportItems.filter(function(item) {
                if (!search) return true;
                var haystack = [
                    item.factor_alias,
                    item.factor_family_alias,
                    item.chinese_name,
                    item.owner_alias,
                    item.owner_username,
                    item.product_group,
                    item.scope_key,
                    (item.params || []).map(function(p) { return p.alias + ':' + p.value; }).join(' '),
                ].join(' ').toLowerCase();
                return haystack.indexOf(search) !== -1;
            });
        }

        function renderMultiImportTable() {
            var body = document.getElementById('multi-import-body');
            if (!body) return;
            var visible = getVisibleMultiImportItems();
            var countEl = document.getElementById('multi-import-count');
            var totalChecked = visible.reduce(function(sum, item) {
                return sum + (item._id && multiImportChecked[item._id] ? 1 : 0);
            }, 0);
            if (countEl) countEl.textContent = String(totalChecked);

            if (!visible.length) {
                body.innerHTML = '<div style="color:#888;text-align:center;padding:28px;">该因子家族暂无已保存的参数配置。</div>';
                return;
            }

            var html = '<table class="param-table" style="width:100%;"><thead><tr>' +
                '<th style="width:36px;"><input type="checkbox" id="multi-import-check-all-visible"></th>' +
                '<th>因子</th><th>参数</th><th>所有者</th><th>产品组</th>' +
                '</tr></thead><tbody>';
            visible.forEach(function(item) {
                var checked = item._id && multiImportChecked[item._id] ? ' checked' : '';
                var params = (item.params || []).map(function(p) {
                    return '<span style="display:inline-block;margin:1px 4px 1px 0;color:#667085;">' +
                        _escapeHtml(p.alias) + ':' + _escapeHtml(p.value) + '</span>';
                }).join('');
                html += '<tr>' +
                    '<td><input type="checkbox" class="multi-import-check"' +
                    ' data-id="' + _escapeHtml(item._id || '') + '"' + checked + '></td>' +
                    '<td><strong>' + _escapeHtml(item.factor_alias || '') + '</strong>' +
                    '<div style="color:#888;font-size:12px;">' + _escapeHtml(item.chinese_name || '') + '</div></td>' +
                    '<td>' + (params || '<span style="color:#aaa;">无</span>') + '</td>' +
                    '<td style="font-size:12px;">' + _escapeHtml(item.owner_alias || item.owner_username || '') + '</td>' +
                    '<td style="font-size:11px;color:#888;">' + _escapeHtml(formatProductGroupLabel(getFactorProductGroup(item))) + '</td>' +
                    '</tr>';
            });
            html += '</tbody></table>';
            body.innerHTML = html;

            // 绑定全选 checkbox
            var allCheck = document.getElementById('multi-import-check-all-visible');
            if (allCheck) {
                allCheck.checked = (totalChecked === visible.length && visible.length > 0);
                allCheck.addEventListener('change', function() {
                    var checked = this.checked;
                    visible.forEach(function(item) {
                        if (item._id) multiImportChecked[item._id] = checked;
                    });
                    renderMultiImportTable();
                });
            }

            // 绑定单个 checkbox
            body.querySelectorAll('.multi-import-check').forEach(function(cb) {
                cb.addEventListener('change', function() {
                    var id = this.dataset.id;
                    if (id) multiImportChecked[id] = this.checked;
                    renderMultiImportTable();
                });
            });
        }

        // 顺序添加因子（category 仅用于前端筛选，不传给后端）
        async function batchAddParams(selectedItems) {
            var statusEl = document.getElementById('import-factors-from-library-status');
            if (statusEl) statusEl.textContent = '导入中...';
            var added = 0;
            for (var i = 0; i < selectedItems.length; i++) {
                var item = selectedItems[i];
                var body = { factor_family_alias: factorAlias };
                if (item.params) {
                    body.params = {};
                    item.params.forEach(function(p) {
                        if (p.alias) body.params[p.alias] = p.value;
                    });
                }
                try {
                    var resp = await fetch('/add_params', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body)
                    });
                    var data = await resp.json();
                    if (data.success) {
                        renderFactorRows(data.factor_rows || []);
                        added++;
                    }
                } catch(e) {}
            }
            if (statusEl) statusEl.textContent = added > 0 ? '已导入 ' + added + ' 个因子' : '';
            if (typeof window.refreshICModule === 'function') window.refreshICModule();
            setTimeout(function() { if (statusEl && statusEl.textContent.indexOf('导入') >= 0) statusEl.textContent = ''; }, 3000);
        }

        async function openMultiFactorImport() {
            multiImportChecked = {};
            var ov = ensureMultiImportOverlay();
            var body = document.getElementById('multi-import-body');
            ov.style.display = 'flex';
            if (body) body.innerHTML = '<div style="color:#888;text-align:center;padding:28px;">加载因子库...</div>';
            try {
                // 按当前 factor_family_alias 过滤
                var url = '/custom-factors/api/param-factor-overview?include_subordinates=1';
                if (factorAlias) url += '&factor_family_alias=' + encodeURIComponent(factorAlias);
                var resp = await fetch(url);
                var data = await resp.json();
                if (!data.success) throw new Error(data.error || '加载失败');
                multiImportItems = (data.factors || []).map(function(item, idx) {
                    item._id = item.factor_alias + '__' + String(item.row_index || idx) + '__' + (item.owner_username || item.owner_alias || '') + '__' + getFactorProductGroup(item);
                    return item;
                });
                renderMultiImportTable();
            } catch (e) {
                if (body) body.innerHTML = '<div style="color:#d40000;text-align:center;padding:28px;">加载失败: ' + _escapeHtml(e.message) + '</div>';
            }
        }

        // 绑定导入按钮：找到 HTML 中的按钮，否则在 bindEvents 后动态创建
        document.querySelectorAll('#import-factors-from-library-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                openMultiFactorImport();
            });
        });

        function renderFactorRows(rows) {
            const tableBody = document.getElementById('factor_table_body');
            if (!tableBody) return;
            const addRow = document.getElementById('add_row');
            Array.from(tableBody.querySelectorAll('tr')).forEach(function(tr) {
                if (tr.id !== 'add_row') tr.remove();
            });
            if (!Array.isArray(rows) || rows.length === 0) {
                if (typeof window._updateParamSummary === 'function') window._updateParamSummary();
                return;
            }
            rows.forEach(function(row) {
                const tr = document.createElement('tr');
                tr.setAttribute('draggable', 'true');
                tr.setAttribute('data-factor-idx', String(row.index));

                let html = '<td>' + _escapeHtml(row.factor_alias || '') + '</td>';
                paramAliases.forEach(function(alias) {
                    const v = row.params && row.params[alias] !== undefined ? row.params[alias] : '';
                    html += '<td>' + _escapeHtml(v) + '</td>';
                });
                html += '<td><button class="param-btn param-btn-danger delete_factor_btn" data-factor-idx="' + String(row.index) + '">删除</button></td>';
                tr.innerHTML = html;
                tableBody.appendChild(tr);
            });
            if (addRow && addRow.parentNode === tableBody) {
                tableBody.insertBefore(addRow, tableBody.firstChild);
            }
            if (typeof window._updateParamSummary === 'function') window._updateParamSummary();
        }

        window._renderParamFactorRows = renderFactorRows;

        // 刷新参数模块：优先复用单因子页官方重载入口，确保当前因子上下文一致。
        window.reloadParamModule = function reloadParamModule(callback) {
            var snapshot = {
                paramDrawerOpen: false,
                time: null,
                submissions: null,
            };

            try {
                var paramDrawer = document.getElementById('param-drawer');
                snapshot.paramDrawerOpen = !!(paramDrawer && paramDrawer.classList.contains('open'));
            } catch (e) {}
            try {
                if (typeof window.getSharedRuntimeTimeRange === 'function') {
                    snapshot.time = JSON.parse(JSON.stringify(window.getSharedRuntimeTimeRange()));
                }
            } catch (e) {}
            try {
                if (typeof window._getCurrentSubmissions === 'function') {
                    var curSubs = window._getCurrentSubmissions() || [];
                    console.log('[DEBUG param snapshot] _getCurrentSubmissions count=' + curSubs.length + ', first_has_products=' + (curSubs.length ? (curSubs[0].products ? curSubs[0].products.length : 'undefined') : 'empty'));
                    snapshot.submissions = JSON.parse(JSON.stringify(curSubs));
                }
            } catch (e) {}

            var finish = function() {
                try {
                    if (snapshot.time) {
                        var setVal = function(id, val) {
                            var el = document.getElementById(id);
                            if (el && val !== null && val !== undefined) el.value = val;
                        };
                        if (snapshot.time.start_date) {
                            var sp = snapshot.time.start_date.split('-');
                            setVal('start_year', sp[0]); setVal('start_month', sp[1]); setVal('start_day', sp[2]);
                        }
                        if (snapshot.time.end_date) {
                            var ep = snapshot.time.end_date.split('-');
                            setVal('end_year', ep[0]); setVal('end_month', ep[1]); setVal('end_day', ep[2]);
                        }
                        if (snapshot.time.start_time) {
                            var st = snapshot.time.start_time.split(':');
                            setVal('start_hour', st[0]); setVal('start_minute', st[1]);
                        }
                        if (snapshot.time.end_time) {
                            var et = snapshot.time.end_time.split(':');
                            setVal('end_hour', et[0]); setVal('end_minute', et[1]);
                        }
                        setVal('timezone_input', snapshot.time.timezone);
                        var isTd = document.getElementById('is_trading_day');
                        var isDay = document.getElementById('is_cn_futures_day');
                        var isNight = document.getElementById('is_cn_futures_night');
                        if (isTd) isTd.checked = !!snapshot.time.is_trading_day;
                        if (isDay) isDay.checked = !!snapshot.time.is_cn_futures_day;
                        if (isNight) isNight.checked = !!snapshot.time.is_cn_futures_night;
                        if (typeof window.updateTimeSummary === 'function') window.updateTimeSummary();
                    }
                    if (snapshot.submissions && typeof window._applySubmissions === 'function') {
                        console.log('[DEBUG param finish] _applySubmissions count=' + snapshot.submissions.length + ', first_has_products=' + (snapshot.submissions.length ? (snapshot.submissions[0].products ? snapshot.submissions[0].products.length : 'undefined') : 'empty'));
                        window._applySubmissions(snapshot.submissions);
                    }
                    if (snapshot.paramDrawerOpen) {
                        var drawer = document.getElementById('param-drawer');
                        var badge = document.getElementById('user-badge');
                        if (drawer) drawer.classList.add('open');
                        if (badge) badge.style.display = 'none';
                    }
                    if (typeof window._updateParamSummary === 'function') window._updateParamSummary();
                } catch (e) {
                    console.error('参数模块刷新后状态恢复失败:', e);
                }
                if (typeof callback === 'function') callback();
            };

            if (typeof window.reloadSingleFactorContent === 'function') {
                return window.reloadSingleFactorContent(finish);
            }

            return fetch(window.location.pathname + _buildFactorUrl(factorAlias))
                .then(res => res.text())
                .then(html => {
                    const parser = new DOMParser();
                    const doc = parser.parseFromString(html, 'text/html');
                    const newModule = doc.getElementById('parameter_module');
                    const oldModule = document.getElementById('parameter_module');
                    if (!newModule || !oldModule || !oldModule.parentNode) {
                        throw new Error('未找到参数模块节点，无法局部刷新');
                    }
                    const imported = document.importNode(newModule, true);
                    oldModule.parentNode.replaceChild(imported, oldModule);
                    window.initParameterModule();
                })
                .catch(err => {
                    console.error('刷新参数模块失败:', err);
                })
                .finally(finish);
        }

        // 绑定事件
        function bindEvents() {
            // 收集当前输入框参数
            function collectParams() {
                const params = {};
                paramAliases.forEach(function(alias) {
                    params[alias] = readParamControl(alias);
                });
                return params;
            }

            // 执行新增因子（暴露为全局函数，供 HTML onclick 调用）
            function doAdd() {
                const params = collectParams();
                fetch('/add_params', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        factor_family_alias: factorAlias,
                        params: params
                    })
                })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        renderFactorRows(data.factor_rows || []);
                        if (data.added_params) {
                            paramAliases.forEach(function(alias) {
                                if (data.added_params[alias] !== undefined) {
                                    writeParamControl(alias, data.added_params[alias]);
                                }
                            });
                        }
                        if (typeof window.refreshICModule === 'function') {
                            window.refreshICModule();
                        }
                    } else {
                        alert('添加失败: ' + data.error);
                    }
                });
            }
            window._doAddParam = doAdd;

            // 新增按钮
            const addBtn = document.querySelector('.add_factor_btn');
            if (addBtn) {
                addBtn.addEventListener('click', doAdd);
            }

            document.querySelectorAll('.factor-param-picker-btn').forEach(function(btn) {
                btn.addEventListener('click', function() {
                    openFactorParamPicker(btn.getAttribute('data-param-alias') || '');
                });
            });

            // 输入框回车键触发新增
            paramAliases.forEach(function(alias) {
                const control = document.getElementById('param_' + alias);
                if (control) {
                    control.addEventListener('keydown', function(e) {
                        if (e.key === 'Enter') {
                            e.preventDefault();
                            doAdd();
                        }
                    });
                }
            });

            // 删除按钮（事件委托）
            if (tbody) {
                tbody.addEventListener('click', function(e) {
                    const btn = e.target.closest('.delete_factor_btn');
                    if (!btn) return;
                    const idx = btn.getAttribute('data-factor-idx');
                    fetch('/delete_params', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            factor_family_alias: factorAlias,
                            factor_idx: idx
                        })
                    })
                    .then(res => res.json())
                    .then(data => {
                        if (data.success) {
                            renderFactorRows(data.factor_rows || []);
                            if (typeof window.refreshICModule === 'function') {
                                window.refreshICModule();
                            }
                        } else {
                            alert('删除失败: ' + data.error);
                        }
                    });
                });
            }

            // 拖拽排序（事件委托）
            if (tbody) {
                let dragStartIdx = null;
                let dragOverIdx = null;

                tbody.addEventListener('dragstart', function(e) {
                    const row = e.target.closest('tr[draggable="true"]');
                    if (!row) return;
                    dragStartIdx = parseInt(row.getAttribute('data-factor-idx'));
                    row.style.opacity = '0.5';
                    e.dataTransfer.effectAllowed = 'move';
                });

                tbody.addEventListener('dragend', function(e) {
                    const row = e.target.closest('tr[draggable="true"]');
                    if (row) row.style.opacity = '';
                    dragStartIdx = null;
                    dragOverIdx = null;
                });

                tbody.addEventListener('dragover', function(e) {
                    const row = e.target.closest('tr[draggable="true"]');
                    if (!row) return;
                    e.preventDefault();
                    dragOverIdx = parseInt(row.getAttribute('data-factor-idx'));
                    row.classList.add('drag-over');
                });

                tbody.addEventListener('dragleave', function(e) {
                    const row = e.target.closest('tr[draggable="true"]');
                    if (row) row.classList.remove('drag-over');
                });

                tbody.addEventListener('drop', function(e) {
                    const row = e.target.closest('tr[draggable="true"]');
                    if (!row) return;
                    e.preventDefault();
                    row.classList.remove('drag-over');
                    if (dragStartIdx !== null && dragOverIdx !== null && dragStartIdx !== dragOverIdx) {
                        fetch('/reorder_params', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                factor_family_alias: factorAlias,
                                from_idx: dragStartIdx,
                                to_idx: dragOverIdx
                            })
                        })
                        .then(res => res.json())
                        .then(data => {
                            if (data.success) {
                                renderFactorRows(data.factor_rows || []);
                                if (typeof window.refreshICModule === 'function') {
                                    window.refreshICModule();
                                }
                            } else {
                                alert('排序失败: ' + data.error);
                            }
                        });
                    }
                });
            }
        }

        bindEvents();

        // 更新外部参数摘要行
        if (typeof window._updateParamSummary === 'function') {
            window._updateParamSummary();
        }

        // ── 参数模板管理 ─────────────────────────────────────────────────────
        var $pSel   = document.getElementById('params-tpl-select');
        var $pLbl   = document.getElementById('params-tpl-name-label');
        var $pInp   = document.getElementById('params-tpl-name-input');
        var $pStat  = document.getElementById('params-tpl-status');

        if (!$pSel) return;  // 模板栏未渲染时跳过

        function pTplStatus(msg, ok) {
            $pStat.textContent = msg;
            $pStat.style.color = ok ? '#28a745' : '#d40000';
            setTimeout(function() { if ($pStat.textContent === msg) $pStat.textContent = ''; }, 2500);
        }

        function populateParamsTplSelect() {
            var prev = $pSel.value;
            fetch('/api/params_templates/' + encodeURIComponent(factorAlias))
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    while ($pSel.options.length > 1) $pSel.remove(1);
                    if (data.success && data.templates) {
                        data.templates.forEach(function(t) {
                            if ((t.name || '').indexOf('__global_') === 0) return;
                            var opt = document.createElement('option');
                            opt.value = t.id; opt.textContent = t.name;
                            $pSel.appendChild(opt);
                        });
                    }
                    if (prev) $pSel.value = prev;
                    updateParamsTplNameDisplay();
                });
        }

        function updateParamsTplNameDisplay() {
            var id = $pSel.value;
            var name = id ? $pSel.options[$pSel.selectedIndex].text : '';
            if (id) { $pLbl.textContent = name; $pLbl.style.display = ''; }
            else    { $pLbl.style.display = 'none'; }
        }

        $pSel.addEventListener('change', function() {
            $pInp.style.display = 'none';
            updateParamsTplNameDisplay();
        });

        $pLbl.addEventListener('dblclick', function() {
            var id = $pSel.value; if (!id) return;
            var name = $pLbl.textContent;
            if (name.indexOf('__global_') === 0) { pTplStatus('设置快照关联参数模板不允许重命名', false); return; }
            $pInp.value = name;
            $pInp.style.display = ''; $pInp.focus();
            $pLbl.style.display = 'none';
        });

        function commitParamsRename(e) {
            if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== 'Escape') return;
            if (e.key === 'Escape') { $pInp.style.display = 'none'; $pLbl.style.display = ''; return; }
            var id = $pSel.value; if (!id) { $pInp.style.display = 'none'; return; }
            if (($pLbl.textContent || '').indexOf('__global_') === 0) {
                $pInp.style.display = 'none'; $pLbl.style.display = '';
                pTplStatus('设置快照关联参数模板不允许重命名', false); return;
            }
            var newName = $pInp.value.trim();
            if (!newName) { $pInp.style.display = 'none'; $pLbl.style.display = ''; return; }
            fetch('/api/params_templates/' + encodeURIComponent(factorAlias) + '/' + id, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ name: newName })
            }).then(function(r) { return r.json(); }).then(function(data) {
                $pInp.style.display = 'none';
                if (data.success) {
                    pTplStatus('✓ 重命名成功', true);
                    populateParamsTplSelect();
                    setTimeout(function() { $pSel.value = id; updateParamsTplNameDisplay(); }, 300);
                } else {
                    $pLbl.style.display = ''; pTplStatus('重命名失败: ' + data.error, false);
                }
            });
        }
        $pInp.addEventListener('keydown', commitParamsRename);
        $pInp.addEventListener('blur',    commitParamsRename);

        document.getElementById('params-tpl-load-btn').addEventListener('click', function() {
            loadSelectedParamsTemplate();
        });

        // 暴露参数模板加载函数，供单因子设置快照等外部模块调用
        // 用法：window._loadParamsTemplate() 加载下拉框选中的模板
        window._loadParamsTemplate = function() {
            return loadSelectedParamsTemplate();
        };

        // 暴露参数模板保存函数，供单因子设置快照等外部模块调用
        // 用法：window._saveCurrentParamsAsTemplate(name) 返回 Promise<{success, id}>
        window._saveCurrentParamsAsTemplate = function(name) {
            return fetch('/api/current_params/' + encodeURIComponent(factorAlias))
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    var params_list = data.params_list || [];
                    if (params_list.length === 0) {
                        var tbodyEl = document.getElementById('factor_table_body');
                        if (tbodyEl && paramAliases.length > 0) {
                            var rows = tbodyEl.querySelectorAll('tr');
                            rows.forEach(function(row) {
                                if (row.id === 'add_row') {
                                    var rowParams = {};
                                    var hasValue = false;
                                    paramAliases.forEach(function(alias) {
                                        var inp = document.getElementById('param_' + alias);
                                        if (inp && inp.value !== '') {
                                            rowParams[alias] = inp.value;
                                            hasValue = true;
                                        }
                                    });
                                    if (hasValue) params_list.push(rowParams);
                                } else {
                                    var cells = row.querySelectorAll('td');
                                    if (cells.length >= paramAliases.length + 1) {
                                        var rowParams = {};
                                        for (var i = 0; i < paramAliases.length; i++) {
                                            var tdText = (cells[i + 1].textContent || '').trim();
                                            if (tdText) rowParams[paramAliases[i]] = tdText;
                                        }
                                        if (Object.keys(rowParams).length > 0) {
                                            params_list.push(rowParams);
                                        }
                                    }
                                }
                            });
                        }
                    }
                    if (params_list.length === 0) {
                        return { success: false, error: '当前没有参数可保存' };
                    }
                    return fetch('/api/params_templates/' + encodeURIComponent(factorAlias), {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ name: name, params_list: params_list })
                    }).then(function(r) { return r.json(); });
                });
        };

        function loadSelectedParamsTemplate() {
            var id = $pSel.value;
            if (!id) { pTplStatus('请先选择一个模板', false); return Promise.resolve(); }
            // 先获取当前参数列表，再与模板参数去重合并
            return Promise.all([
                fetch('/api/params_templates/' + encodeURIComponent(factorAlias) + '/' + id).then(function(r) { return r.json(); }),
                fetch('/api/current_params/' + encodeURIComponent(factorAlias)).then(function(r) { return r.json(); })
            ]).then(function(results) {
                var tplData = results[0];
                var curData = results[1];
                if (!tplData.success) { pTplStatus('加载失败: ' + (tplData.error || '未知错误'), false); return; }
                
                var tplList = tplData.template.params_list || [];
                var curList = (curData.success && curData.params_list) ? curData.params_list : [];
                
                // 去重合并：将模板参数追加到当前参数（跳过已存在的）
                var merged = curList.slice();  // 先复制当前参数
                tplList.forEach(function(tplParams) {
                    // 检查是否已存在相同的参数组合
                    var isDuplicate = merged.some(function(existing) {
                        var keys = Object.keys(tplParams);
                        if (keys.length === 0) return false;
                        return keys.every(function(k) {
                            return String(existing[k] || '') === String(tplParams[k] || '');
                        });
                    });
                    if (!isDuplicate) {
                        merged.push(tplParams);
                    }
                });
                
                if (merged.length === curList.length) {
                    pTplStatus('模板中的参数组合已全部存在，无需添加', true); return;
                }
                
                var addedCount = merged.length - curList.length;
                return fetch('/replace_params', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ factor_family_alias: factorAlias, params_list: merged })
                }).then(function(r) { return r.json(); }).then(function(res) {
                    if (!res.success) { pTplStatus('加载失败: ' + res.error, false); return; }
                    renderFactorRows(res.factor_rows || []);
                    pTplStatus('✓ 已加载，新增 ' + addedCount + ' 组参数（跳过 ' + (tplList.length - addedCount) + ' 组重复）', true);
                    if (typeof window.refreshICModule === 'function') window.refreshICModule();
                });
            });
        }

        document.getElementById('params-tpl-save-btn').addEventListener('click', function() {
            // 优先从后端获取，如果后端为空则从DOM收集
            fetch('/api/current_params/' + encodeURIComponent(factorAlias))
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    var params_list = data.params_list || [];
                    // 后端为空时从DOM收集：
                    // 1) 从已渲染的因子行（tbody中除add_row外的tr）收集，
                    //    每行的td文本按paramAliases顺序对应各参数值
                    // 2) 如果add_row输入框有值，也收集为新组合
                    if (params_list.length === 0) {
                        var tbodyEl = document.getElementById('factor_table_body');
                        if (tbodyEl && paramAliases.length > 0) {
                            var rows = tbodyEl.querySelectorAll('tr');
                            rows.forEach(function(row) {
                                if (row.id === 'add_row') {
                                    // 从新增行的输入框收集（id="param_<alias>"）
                                    var rowParams = {};
                                    var hasValue = false;
                                    paramAliases.forEach(function(alias) {
                                        var inp = document.getElementById('param_' + alias);
                                        if (inp && inp.value !== '') {
                                            rowParams[alias] = inp.value;
                                            hasValue = true;
                                        }
                                    });
                                    if (hasValue) params_list.push(rowParams);
                                } else {
                                    // 从已渲染因子行收集（td文本顺序 = paramAliases顺序）
                                    var cells = row.querySelectorAll('td');
                                    if (cells.length >= paramAliases.length + 1) {
                                        var rowParams = {};
                                        for (var i = 0; i < paramAliases.length; i++) {
                                            var tdText = (cells[i + 1].textContent || '').trim();
                                            if (tdText) rowParams[paramAliases[i]] = tdText;
                                        }
                                        if (Object.keys(rowParams).length > 0) {
                                            params_list.push(rowParams);
                                        }
                                    }
                                }
                            });
                        }
                    }
                    if (params_list.length === 0) {
                        pTplStatus('当前没有参数可保存', false); return;
                    }
                    var name = prompt('请输入模板名称：');
                    if (!name || !name.trim()) return;
                    fetch('/api/params_templates/' + encodeURIComponent(factorAlias), {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ name: name.trim(), params_list: params_list })
                    }).then(function(r) { return r.json(); }).then(function(res) {
                        if (res.success) {
                            pTplStatus('✓ 模板已保存', true);
                            populateParamsTplSelect();
                            setTimeout(function() { $pSel.value = res.id; updateParamsTplNameDisplay(); }, 300);
                        } else { pTplStatus('保存失败: ' + res.error, false); }
                    });
                });
        });

        document.getElementById('params-tpl-update-btn').addEventListener('click', function() {
            var id = $pSel.value;
            if (!id) { pTplStatus('请先选择一个模板', false); return; }
            fetch('/api/current_params/' + encodeURIComponent(factorAlias))
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    var params_list = data.params_list || [];
                    if (params_list.length === 0) {
                        var tbodyEl = document.getElementById('factor_table_body');
                        if (tbodyEl && paramAliases.length > 0) {
                            var rows = tbodyEl.querySelectorAll('tr');
                            rows.forEach(function(row) {
                                if (row.id === 'add_row') {
                                    var rowParams = {};
                                    var hasValue = false;
                                    paramAliases.forEach(function(alias) {
                                        var inp = document.getElementById('param_' + alias);
                                        if (inp && inp.value !== '') {
                                            rowParams[alias] = inp.value;
                                            hasValue = true;
                                        }
                                    });
                                    if (hasValue) params_list.push(rowParams);
                                } else {
                                    var cells = row.querySelectorAll('td');
                                    if (cells.length >= paramAliases.length + 1) {
                                        var rowParams = {};
                                        for (var i = 0; i < paramAliases.length; i++) {
                                            var tdText = (cells[i + 1].textContent || '').trim();
                                            if (tdText) rowParams[paramAliases[i]] = tdText;
                                        }
                                        if (Object.keys(rowParams).length > 0) {
                                            params_list.push(rowParams);
                                        }
                                    }
                                }
                            });
                        }
                    }
                    if (params_list.length === 0) {
                        pTplStatus('当前没有参数可保存', false); return;
                    }
                    fetch('/api/params_templates/' + encodeURIComponent(factorAlias) + '/' + id, {
                        method: 'PUT',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ params_list: params_list })
                    }).then(function(r) { return r.json(); }).then(function(res) {
                        pTplStatus(res.success ? '✓ 模板已更新' : '更新失败: ' + res.error, res.success);
                    });
                });
        });

        document.getElementById('params-tpl-delete-btn').addEventListener('click', function() {
            var id = $pSel.value;
            if (!id) { pTplStatus('请先选择一个模板', false); return; }
            var name = $pSel.options[$pSel.selectedIndex].text;
            if (!confirm('确定删除模板「' + name + '」？')) return;
            fetch('/api/params_templates/' + encodeURIComponent(factorAlias) + '/' + id, { method: 'DELETE' })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.success) { pTplStatus('✓ 模板已删除', true); populateParamsTplSelect(); }
                    else { pTplStatus('删除失败: ' + data.error, false); }
                });
        });

        populateParamsTplSelect();
        // ── 参数模板管理 END ──────────────────────────────────────────────────
    }

    window.initParameterModule = initParameterModule;

    // 动态加载单因子测试内容时，后续内联脚本会依赖这个全局函数。
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initParameterModule);
    } else {
        initParameterModule();
    }
})();
