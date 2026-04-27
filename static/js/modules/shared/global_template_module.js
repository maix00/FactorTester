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

        // 2. 时间范围
        const startTimeInput = document.getElementById('start-time-input');
        const endTimeInput = document.getElementById('end-time-input');
        snapshot.time_data = {
            start: startTimeInput ? startTimeInput.value : '',
            end: endTimeInput ? endTimeInput.value : ''
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

        return snapshot;
    }

    // ── 应用快照 ──────────────────────────────────────────────────────────
    async function applySnapshot(snapshot) {
        if (!snapshot) return;

        // 1. 恢复参数设置
        if (snapshot.params_list && snapshot.params_list.length > 0) {
            // 兼容旧格式 [{factor_name, params}, ...] → 新格式 [{alias: value}, ...]
            var pl = snapshot.params_list;
            if (pl[0] && pl[0].params !== undefined) {
                pl = pl.map(function(p) { return p.params || {}; });
            }
            try {
                const resp = await fetch('/replace_params', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        factor_family_alias: FF_ALIAS,
                        params_list: pl
                    })
                });
                const data = await resp.json();
                if (data.success && typeof window.reloadParamModule === 'function') {
                    await window.reloadParamModule();
                }
            } catch (e) {
                console.error('恢复参数失败:', e);
            }
        }

        // 2. 恢复时间范围
        if (snapshot.time_data) {
            const startInp = document.getElementById('start-time-input');
            const endInp = document.getElementById('end-time-input');
            if (startInp && snapshot.time_data.start) startInp.value = snapshot.time_data.start;
            if (endInp && snapshot.time_data.end) endInp.value = snapshot.time_data.end;
            if (typeof updateTimeSummary === 'function') updateTimeSummary();
        }

        // 3. 恢复品种分类
        if (snapshot.submissions && snapshot.submissions.length > 0 && typeof window._applySubmissions === 'function') {
            window._applySubmissions(snapshot.submissions);
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
                html += `
                <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 10px;border-bottom:1px solid #eef2f7;gap:8px;">
                    <div style="flex:1;min-width:0;">
                        <div style="font-size:13px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(tpl.name)}</div>
                        <div style="font-size:11px;color:#888;">${escapeHtml(tpl.ff_alias || '')}</div>
                    </div>
                    <button class="btn btn-sm btn-outline-primary global-tpl-load-btn" data-tpl-id="${tpl.id}">加载</button>
                    <button class="btn btn-sm btn-outline-danger global-tpl-delete-btn" data-tpl-id="${tpl.id}" style="color:#d40000;border-color:#d40000;">删除</button>
                </div>`;
            });
            listEl.innerHTML = html;
            // 绑定加载按钮
            listEl.querySelectorAll('.global-tpl-load-btn').forEach(btn => {
                btn.onclick = () => loadTemplate(btn.getAttribute('data-tpl-id'));
            });
            // 绑定删除按钮
            listEl.querySelectorAll('.global-tpl-delete-btn').forEach(btn => {
                btn.onclick = () => deleteTemplate(btn.getAttribute('data-tpl-id'));
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
