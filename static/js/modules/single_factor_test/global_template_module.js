/**
 * 全局设置模板模块
 * 保存/加载所有设置：参数、时间范围、品种分类、收益率频率、分组测试设置
 */
(function() {
    const FF_ALIAS = window.factorFamilyAlias || '';

    // ── 收集当前所有设置快照 ──────────────────────────────────────────────
    async function collectSnapshot() {
        const snapshot = {};

        // 1. 参数设置 — 从后端API获取（避免DOM展示值与原始值不一致）
        try {
            const resp = await fetch('/api/current_params/' + encodeURIComponent(FF_ALIAS));
            const data = await resp.json();
            snapshot.params_list = (data.success && data.params_list) ? data.params_list : [];
        } catch (e) {
            snapshot.params_list = [];
        }

        // 2. 时间范围（完整字段，与 /set_time_range 对齐）
        // DOM id 使用下划线：start_year, start_month, ...（见 time_range_module.html）
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
        snapshot.time_data = {
            start_date: sY ? sY.value + '-' + pad(sM?.value||1) + '-' + pad(sD?.value||1) : '',
            start_time: sH ? pad(sH?.value||9) + ':' + pad(sMin?.value||0) : '09:00',
            end_date: eY ? (eY.value||(sY?sY.value:'')) + '-' + pad(eM?.value||1) + '-' + pad(eD?.value||1) : '',
            end_time: eH ? pad(eH?.value||15) + ':' + pad(eMin?.value||0) : '15:00',
            is_trading_day: isTd ? isTd.checked : false,
            is_cn_futures_day: isCfd ? isCfd.checked : false,
            is_cn_futures_night: isCfn ? isCfn.checked : false,
            timezone: tz ? tz.value : 'Asia/Shanghai',
            // 保留旧格式兼容
            start: '',
            end: ''
        };

        // 3. 品种分类
        if (window._getCurrentSubmissions) {
            snapshot.submissions = window._getCurrentSubmissions();
        } else {
            // fallback: try reading from fancytree
            snapshot.submissions = [];
        }

        // 4. 收益率频率
        const freqRows = document.querySelectorAll('#ic-freq-table-body tr');
        const returnFreqs = [];
        freqRows.forEach(row => {
            const cb = row.querySelector('.factor-checkbox');
            const inp = row.querySelector('.factor-return-freq-input');
            if (cb) {
                returnFreqs.push({
                    alias: cb.getAttribute('data-factor-alias'),
                    checked: cb.checked,
                    return_freq: inp ? inp.value.trim() : ''
                });
            }
        });
        snapshot.return_freqs = returnFreqs;

        // 5. 分组测试设置
        snapshot.group_settings = {
            group_count: document.getElementById('group_count')?.value || '5',
            fee_mode: document.querySelector('input[name="fee_mode"]:checked')?.value || 'none',
            fee_rate: document.getElementById('fee_rate')?.value || '0.03',
            use_closetoday: document.getElementById('use_closetoday_btn')?.textContent?.includes('平今') || false,
            group_start_year: document.getElementById('group_start_year')?.value || '',
            group_start_month: document.getElementById('group_start_month')?.value || '',
            group_start_day: document.getElementById('group_start_day')?.value || '',
            group_end_year: document.getElementById('group_end_year')?.value || '',
            group_end_month: document.getElementById('group_end_month')?.value || '',
            group_end_day: document.getElementById('group_end_day')?.value || ''
        };

        // 6. 费率修改（按品种费率的手动编辑值）
        if (window._getFeeModifications) {
            snapshot.fee_modifications = window._getFeeModifications();
        } else {
            snapshot.fee_modifications = {};
        }

        return snapshot;
    }

    // ── 应用快照 ──────────────────────────────────────────────────────────
    // 顺序很重要：先设时间范围（影响tester创建），再设参数，最后重建tester
    async function applySnapshot(snapshot) {
        if (!snapshot) return;

        // 1. 先设置时间范围（后端 /set_time_range 会更新 shared.start_point/end_point，
        //    创建 tester 时需要用到）
        if (snapshot.time_data) {
            var td = snapshot.time_data;
            // 恢复到时间模块的 DOM 输入框（id 用下划线）
            var setVal = function(id, val) { var el = document.getElementById(id); if (el && val !== null && val !== undefined) el.value = val; };
            if (td.start_date) {
                var parts = td.start_date.split('-');
                setVal('start_year', parts[0]);
                setVal('start_month', parts[1]);
                setVal('start_day', parts[2]);
            }
            if (td.start_time) {
                var parts = td.start_time.split(':');
                setVal('start_hour', parts[0]);
                setVal('start_minute', parts[1]);
            }
            if (td.end_date) {
                var parts = td.end_date.split('-');
                setVal('end_year', parts[0]);
                setVal('end_month', parts[1]);
                setVal('end_day', parts[2]);
            }
            if (td.end_time) {
                var parts = td.end_time.split(':');
                setVal('end_hour', parts[0]);
                setVal('end_minute', parts[1]);
            }
            setVal('timezone_input', td.timezone);
            // 恢复复选框状态
            var isTdCb = document.getElementById('is_trading_day');
            var isCfdCb = document.getElementById('is_cn_futures_day');
            var isCfnCb = document.getElementById('is_cn_futures_night');
            if (isTdCb) isTdCb.checked = !!td.is_trading_day;
            if (isCfdCb) isCfdCb.checked = !!td.is_cn_futures_day;
            if (isCfnCb) isCfnCb.checked = !!td.is_cn_futures_night;
            // 根据复选框状态恢复时间输入框 disabled 状态
            var timeDisabled = !!(td.is_trading_day || td.is_cn_futures_day || td.is_cn_futures_night);
            [document.getElementById('start_hour'), document.getElementById('start_minute'),
             document.getElementById('end_hour'), document.getElementById('end_minute')].forEach(function(el) {
                if (el) {
                    el.disabled = timeDisabled;
                    el.style.background = timeDisabled ? '#ccc' : '#eee';
                }
            });
            // 触发时间模块的 current_settings 更新
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
            // 更新摘要行
            if (typeof updateTimeSummary === 'function') updateTimeSummary();
            // 提交到后端
            try {
                await fetch('/set_time_range', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        factor_family_alias: FF_ALIAS,
                        start_date: td.start_date || '',
                        start_time: td.start_time || '09:00',
                        end_date: td.end_date || '',
                        end_time: td.end_time || '15:00',
                        is_trading_day: td.is_trading_day || false,
                        is_cn_futures_day: td.is_cn_futures_day || false,
                        is_cn_futures_night: td.is_cn_futures_night || false,
                        timezone: td.timezone || 'Asia/Shanghai'
                    })
                });
            } catch (e) {
                console.error('恢复时间范围失败:', e);
            }
        }

        // 2. 恢复参数设置（通过参数模板的保存/加载链路，复用参数模块的成熟恢复流程）
        if (snapshot.params_list && snapshot.params_list.length > 0) {
            try {
                // 先清空现有参数，然后通过参数模板方式加载（去重合并=直接替换）
                await fetch('/replace_params', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ factor_family_alias: FF_ALIAS, params_list: [] })
                });
                // 保存一个临时参数模板
                var saveResp = await fetch('/api/params_templates/' + encodeURIComponent(FF_ALIAS), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: '__global_restore__', params_list: snapshot.params_list })
                });
                var saveData = await saveResp.json();
                if (saveData.success && saveData.id) {
                    // 把下拉框设到这个临时模板
                    var pSel = document.getElementById('params-tpl-select');
                    if (pSel) {
                        var found = false;
                        for (var i = 0; i < pSel.options.length; i++) {
                            if (pSel.options[i].value === String(saveData.id)) { found = true; break; }
                        }
                        if (!found) {
                            var opt = document.createElement('option');
                            opt.value = saveData.id;
                            opt.textContent = '__global_restore__';
                            pSel.appendChild(opt);
                        }
                        pSel.value = String(saveData.id);
                        var pLbl = document.getElementById('params-tpl-name-label');
                        if (pLbl) { pLbl.textContent = '__global_restore__'; pLbl.style.display = ''; }
                    }
                    // 调用参数模块的加载函数（去重合并→因为已清空，等于直接替换）
                    if (typeof window._loadParamsTemplate === 'function') {
                        await window._loadParamsTemplate();
                    }
                } else {
                    alert('恢复参数失败: 无法创建临时参数模板 - ' + (saveData.error || ''));
                }
            } catch (e) {
                alert('恢复参数异常: ' + e.message);
            }
        }

        // 3. 清除旧 tester，为每个 submission 重新提交以重建后端 tester
        if (snapshot.submissions && snapshot.submissions.length > 0) {
            // 先清空后端旧 tester
            try {
                await fetch('/clear_all_submissions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
            } catch (e) {
                console.error('清空旧测试器失败:', e);
            }
            // 按 submisssion_id 顺序重新提交
            var restoredSubmissions = [];
            for (var i = 0; i < snapshot.submissions.length; i++) {
                var sub = snapshot.submissions[i];
                if (!sub.paths || sub.paths.length === 0) continue;
                var id_time = (sub.id !== undefined && sub.id !== null) ? sub.id : Date.now() + i;
                try {
                    var resp = await fetch('/submit_selected_products', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            selected_paths: sub.paths,
                            id_time: id_time
                        })
                    });
                    var result = await resp.json();
                    if (result.success) {
                        restoredSubmissions.push({
                            id: id_time,
                            label: sub.label || result.factor_tester_serial || '',
                            paths: result.selected_paths || sub.paths,
                            pathsDescMap: sub.pathsDescMap || {},
                            factor_tester_name: result.factor_tester_name || sub.factor_tester_name,
                            factor_tester_serial: result.factor_tester_serial || sub.factor_tester_serial,
                            count_desc: result.count_desc || sub.count_desc,
                            timestamp: sub.timestamp || '',
                            start_date: sub.start_date || '',
                            end_date: sub.end_date || '',
                            start_time: sub.start_time || '',
                            end_time: sub.end_time || ''
                        });
                    }
                } catch (e) {
                    console.error('重新提交测试器失败:', sub.id, e);
                }
            }
            // 用新的 submissions 更新全局状态
            if (restoredSubmissions.length > 0 && typeof window._applySubmissions === 'function') {
                window._applySubmissions(restoredSubmissions);
            }
        }

        // 4. 恢复收益率频率
        if (snapshot.return_freqs && snapshot.return_freqs.length > 0) {
            snapshot.return_freqs.forEach(fr => {
                const cb = document.querySelector(`#ic-freq-table-body .factor-checkbox[data-factor-alias="${fr.alias}"]`);
                const inp = document.querySelector(`#ic-freq-table-body .factor-return-freq-input[data-factor-alias="${fr.alias}"]`);
                if (cb) cb.checked = fr.checked !== false;
                if (inp) inp.value = fr.return_freq || '';
            });
            // 触发摘要更新
            const tbody = document.getElementById('ic-freq-table-body');
            if (tbody) {
                tbody.querySelectorAll('.factor-return-freq-input').forEach(inp => inp.dispatchEvent(new Event('input', { bubbles: true })));
            }
        }

        // 5. 恢复分组测试设置
        if (snapshot.group_settings) {
            const gs = snapshot.group_settings;
            if (gs.group_count) {
                const gc = document.getElementById('group_count');
                if (gc) gc.value = gs.group_count;
            }
            if (gs.fee_mode) {
                const radio = document.querySelector(`input[name="fee_mode"][value="${gs.fee_mode}"]`);
                if (radio) radio.checked = true;
                // trigger change event to show/hide fee inputs
                document.querySelectorAll('input[name="fee_mode"]').forEach(r => r.dispatchEvent(new Event('change', { bubbles: true })));
            }
            if (gs.fee_rate) {
                const fr = document.getElementById('fee_rate');
                if (fr) fr.value = gs.fee_rate;
            }
            ['group_start_year','group_start_month','group_start_day','group_end_year','group_end_month','group_end_day'].forEach(id => {
                if (gs[id]) {
                    const el = document.getElementById(id);
                    if (el) el.value = gs[id];
                }
            });
        }

        // 6. 恢复费率修改
        if (snapshot.fee_modifications && window._applyFeeModifications) {
            window._applyFeeModifications(snapshot.fee_modifications);
        }
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

        // 同步保存参数模板，用于加载时通过参数模块的恢复流程来恢复参数
        if (typeof window._saveCurrentParamsAsTemplate === 'function') {
            try {
                await window._saveCurrentParamsAsTemplate('__global_restore__');
            } catch(e) {}
        }

        statusEl.textContent = '保存中...';
        statusEl.style.color = '#0078d4';
        try {
            const resp = await fetch('/api/global_templates', {
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
        const listEl = document.getElementById('global-tpl-list');
        if (!listEl) return;
        try {
            const resp = await fetch('/api/global_templates');
            const data = await resp.json();
            if (!data.success || !data.templates || data.templates.length === 0) {
                listEl.innerHTML = '<div style="color:#888;text-align:center;padding:10px;">暂无已保存的模板</div>';
                return;
            }
            let html = '';
            data.templates.forEach(tpl => {
                const tplId = tpl.id;
                const summary = tpl.summary || {};

                // 构建类似外部 summary-row 的摘要行
                function buildSummaryRow(label, value, icon) {
                    if (!value) return '';
                    var valStr = '';
                    if (Array.isArray(value)) {
                        // 每个元素一行，多组参数时换行展示
                        valStr = value.map(function(v) {
                            return '<div style="font-size:11px;color:#555;padding:1px 0;">' + escapeHtml(v) + '</div>';
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

                var summaryHtml = '';
                summaryHtml += buildSummaryRow('时间范围', summary.time_range, '📅');
                summaryHtml += buildSummaryRow('参数设置', summary.params, '⚙️');
                summaryHtml += buildSummaryRow('品种分类', summary.products, '🌳');
                summaryHtml += buildSummaryRow('因子参数', summary.return_freqs, '📈');
                summaryHtml += buildSummaryRow('分组测试', summary.group_test, '🧪');

                if (!summaryHtml) {
                    summaryHtml = '<div style="font-size:11px;color:#999;padding:4px 0;">无设置信息</div>';
                }

                html += `
                <div class="tpl-row" style="border-bottom:1px solid #eef2f7;">
                    <div class="tpl-row-header" data-tpl-id="${tplId}" style="display:flex;align-items:center;justify-content:space-between;padding:8px 10px;cursor:pointer;gap:8px;">
                        <div style="flex:1;min-width:0;">
                            <div style="font-size:13px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(tpl.name)}</div>
                            <div style="font-size:11px;color:#888;">${escapeHtml(tpl.ff_alias || '')}</div>
                        </div>
                        <span class="tpl-expand-icon" style="font-size:11px;color:#888;transition:transform 0.2s;">▼</span>
                    </div>
                    <div class="tpl-row-detail" style="display:none;padding:6px 10px 10px 10px;background:#f8fafc;">
                        ${summaryHtml}
                        <div style="margin-top:8px;display:flex;gap:6px;">
                            <button class="btn btn-sm btn-outline-primary global-tpl-load-btn" data-tpl-id="${tplId}">加载</button>
                            <button class="btn btn-sm btn-outline-danger global-tpl-delete-btn" data-tpl-id="${tplId}" style="color:#d40000;border-color:#d40000;">删除</button>
                        </div>
                    </div>
                </div>`;
            });
            listEl.innerHTML = html;
            // 绑定展开/收起
            listEl.querySelectorAll('.tpl-row-header').forEach(function(header) {
                header.addEventListener('click', function() {
                    var detail = header.nextElementSibling;
                    var icon = header.querySelector('.tpl-expand-icon');
                    if (detail.style.display === 'none') {
                        detail.style.display = 'block';
                        icon.style.transform = 'rotate(180deg)';
                    } else {
                        detail.style.display = 'none';
                        icon.style.transform = 'rotate(0deg)';
                    }
                });
            });
            // 绑定加载按钮（阻止冒泡，避免触发展开/收起）
            listEl.querySelectorAll('.global-tpl-load-btn').forEach(btn => {
                btn.addEventListener('click', function(e) {
                    e.stopPropagation();
                    loadTemplate(this.getAttribute('data-tpl-id'));
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

    // ── 加载单个模板 ──────────────────────────────────────────────────────
    async function loadTemplate(tplId) {
        const statusEl = document.getElementById('global-tpl-load-status');
        statusEl.textContent = '加载中...';
        statusEl.style.color = '#0078d4';
        try {
            const resp = await fetch('/api/global_templates/' + tplId);
            const data = await resp.json();
            if (!data.success) {
                statusEl.textContent = '✗ 加载失败: ' + (data.error || '未知错误');
                statusEl.style.color = '#d40000';
                return;
            }
            await applySnapshot(data.template.snapshot);
            statusEl.textContent = '✓ 已加载: ' + data.template.name;
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
            const resp = await fetch('/api/global_templates/' + tplId, { method: 'DELETE' });
            const data = await resp.json();
            if (data.success) {
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
    document.addEventListener('DOMContentLoaded', () => {
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
        }
    });

    // 暴露给外部
    window._collectSnapshot = collectSnapshot;
    window._applySnapshot = applySnapshot;
})();
