(function() {
    if (window.openSharedFactorParamPicker) return;

    function esc(value) {
        const d = document.createElement('div');
        d.textContent = value == null ? '' : String(value);
        return d.innerHTML;
    }

    let items = [];
    let setter = null;

    function ensureOverlay() {
        let overlay = document.getElementById('shared-factor-param-picker-overlay');
        if (overlay) return overlay;
        overlay = document.createElement('div');
        overlay.id = 'shared-factor-param-picker-overlay';
        overlay.style.cssText = 'display:none;position:fixed;inset:0;z-index:3000;background:rgba(15,23,42,.35);align-items:center;justify-content:center;padding:24px;';
        overlay.innerHTML = '<div style="width:min(980px,96vw);max-height:86vh;background:#fff;border-radius:8px;box-shadow:0 18px 48px rgba(15,23,42,.25);display:flex;flex-direction:column;overflow:hidden;">' +
            '<div style="display:flex;align-items:center;gap:12px;padding:14px 18px;border-bottom:1px solid #e5e7eb;">' +
            '<strong style="font-size:16px;">选择因子</strong><input id="shared-factor-param-picker-search" type="search" placeholder="搜索因子/家族/参数/用户" style="flex:1;min-width:180px;">' +
            '<button type="button" class="param-btn" id="shared-factor-param-picker-close">关闭</button></div>' +
            '<div id="shared-factor-param-picker-body" style="overflow:auto;padding:14px 18px;"></div></div>';
        document.body.appendChild(overlay);
        overlay.addEventListener('click', event => {
            if (event.target === overlay || event.target.id === 'shared-factor-param-picker-close') {
                overlay.style.display = 'none';
            }
            const btn = event.target.closest('[data-shared-factor-param-pick]');
            if (btn) {
                if (typeof setter === 'function') setter(btn.dataset.sharedFactorParamPick || '');
                overlay.style.display = 'none';
            }
        });
        overlay.querySelector('#shared-factor-param-picker-search').addEventListener('input', render);
        return overlay;
    }

    function render() {
        const body = document.getElementById('shared-factor-param-picker-body');
        const q = (document.getElementById('shared-factor-param-picker-search')?.value || '').trim().toLowerCase();
        const visible = items.filter(item => {
            if (!q) return true;
            return [item.factor_alias, item.factor_family_alias, item.factor_family_name, item.chinese_name, item.owner_alias, item.owner_username, item.scope_key]
                .join(' ').toLowerCase().includes(q);
        });

        // 按 scope_key 分组
        const scopes = {};
        visible.forEach(item => {
            const sk = item.scope_key || '默认';
            if (!scopes[sk]) scopes[sk] = [];
            scopes[sk].push(item);
        });
        const scopeKeys = Object.keys(scopes).sort((a, b) => {
            if (a === 'default' || a === '默认') return 1;
            if (b === 'default' || b === '默认') return -1;
            return a.localeCompare(b);
        });

        if (!visible.length) {
            body.innerHTML = '<div style="color:#888;text-align:center;padding:28px;">暂无可选因子。请先在因子库保存参数配置。</div>';
            return;
        }

        const hasSearch = q.length > 0;
        let html = '';
        scopeKeys.forEach((sk, si) => {
            const groupItems = scopes[sk];
            // 有搜索时全部展开
            const expanded = hasSearch || (si === 0 && scopeKeys.length === 1);
            const caretClass = expanded ? 'caret-open' : 'caret-closed';
            const bodyStyle = expanded ? '' : 'display:none;';
            html += '<div class="picker-scope-node">';
            html += '<div class="picker-scope-header" data-scope-toggle="' + esc(sk) + '" style="display:flex;align-items:center;gap:8px;padding:8px 0;cursor:pointer;border-bottom:1px solid #f0f0f0;">';
            html += '<span class="picker-caret ' + caretClass + '" data-scope="' + esc(sk) + '"></span>';
            html += '<strong style="font-size:14px;color:#1e293b;">' + esc(sk) + '</strong>';
            html += '<span style="color:#888;font-size:12px;">(' + groupItems.length + ')</span>';
            html += '</div>';
            html += '<div class="picker-scope-body" data-scope-body="' + esc(sk) + '" style="' + bodyStyle + '">';
            html += '<table class="param-table" style="width:100%;"><thead><tr><th>因子</th><th>家族</th><th>参数</th><th>所有者</th><th>操作</th></tr></thead><tbody>';
            groupItems.forEach(item => {
                const params = (item.params || []).map(p => '<span style="display:inline-block;margin:1px 4px 1px 0;color:#667085;">' + esc(p.alias) + ':' + esc(p.value) + '</span>').join('');
                html += '<tr><td><strong>' + esc(item.factor_alias) + '</strong></td><td>' + esc(item.factor_family_alias || item.factor_family_name) + '<div style="color:#888;font-size:12px;">' + esc(item.chinese_name) + '</div></td><td>' + (params || '<span style="color:#aaa;">无</span>') + '</td><td>' + esc(item.owner_alias || item.owner_username) + '</td><td><button type="button" class="param-btn" data-shared-factor-param-pick="' + esc(item.factor_alias) + '">选择</button></td></tr>';
            });
            html += '</tbody></table></div></div>';
        });
        body.innerHTML = html;

        // 绑定折叠事件
        body.querySelectorAll('[data-scope-toggle]').forEach(header => {
            header.addEventListener('click', function() {
                const sk = this.dataset.scopeToggle;
                const caret = body.querySelector('.picker-caret[data-scope="' + CSS.escape(sk) + '"]');
                const scopeBody = body.querySelector('[data-scope-body="' + CSS.escape(sk) + '"]');
                if (!scopeBody) return;
                const isOpen = scopeBody.style.display !== 'none';
                if (isOpen) {
                    scopeBody.style.display = 'none';
                    if (caret) { caret.classList.remove('caret-open'); caret.classList.add('caret-closed'); }
                } else {
                    scopeBody.style.display = '';
                    if (caret) { caret.classList.remove('caret-closed'); caret.classList.add('caret-open'); }
                }
            });
        });
    }

    window.openSharedFactorParamPicker = async function(alias, onPick) {
        setter = onPick;
        const overlay = ensureOverlay();
        const body = document.getElementById('shared-factor-param-picker-body');
        overlay.style.display = 'flex';
        body.innerHTML = '<div style="color:#888;text-align:center;padding:28px;">加载因子库...</div>';
        try {
            const resp = await fetch('/custom-factors/api/param-factor-overview?include_subordinates=1');
            const data = await resp.json();
            if (!data.success) throw new Error(data.error || '加载失败');
            items = data.factors || [];
            render();
        } catch (e) {
            body.innerHTML = '<div style="color:#d40000;text-align:center;padding:28px;">加载失败: ' + esc(e.message) + '</div>';
        }
    };
})();
