(function() {
    var APP = 'single_factor_page';
    var LOCAL = 'local-settings';
    var state = {
        manifest: null,
        mountedTabs: [],
        activeTab: null,
        containers: {},
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

    function defaults() {
        return state.manifest && state.manifest.defaults ? state.manifest.defaults : {};
    }

    function settingKeysForTab(tabKey) {
        var out = [];
        var defs = defaults();
        Object.keys(defs).forEach(function(key) {
            if (defs[key] && defs[key].tab_key === tabKey) out.push(key);
        });
        return out;
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

    function makeChip(tabKey, text) {
        var chip = document.createElement('span');
        chip.className = 'gt-backend-chip';
        chip.innerHTML = renderChipHtml(text);
        chip.title = '打开' + ((tabMeta(tabKey) && tabMeta(tabKey).label) || tabKey);
        chip.style.cursor = 'pointer';
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

    function paramSummaryText() {
        var tbody = document.getElementById('factor_table_body');
        var rows = tbody ? Array.from(tbody.querySelectorAll('tr')).filter(function(row) {
            return row.id !== 'add_row' && row.style.display !== 'none';
        }) : [];
        var settingCount = 0;
        var module = document.getElementById('parameter_module');
        if (module) {
            try {
                settingCount = (JSON.parse(module.getAttribute('data-param-aliases') || '[]') || []).length;
            } catch (error) {
                settingCount = 0;
            }
        }
        return '参数: 已设置' + rows.length + '/设置数' + settingCount;
    }

    function timeSummaryText() {
        var src = document.getElementById('time-summary-text');
        var text = src ? (src.textContent || '').trim() : '';
        if (!text || text === '加载中…') return '时间: 默认';
        return '时间: ' + text;
    }

    function templateSummaryText() {
        var status = document.getElementById('global-tpl-load-status');
        var text = status ? (status.textContent || '').trim() : '';
        return text ? '模板: ' + text.replace(/^✓\s*/, '') : '模板: 无';
    }

    function chipTextForTab(tabKey) {
        if (tabKey === 'setting_template') return templateSummaryText();
        if (tabKey === 'parameters') return paramSummaryText();
        if (tabKey === 'time') return timeSummaryText();
        var key = settingKeysForTab(tabKey)[0];
        var def = key ? defaults()[key] : null;
        return ((def && def.label) || (tabMeta(tabKey) && tabMeta(tabKey).label) || tabKey) + ': 无';
    }

    function renderChips() {
        var row = document.getElementById('single-factor-page-settings-chips');
        if (!row) return;
        row.innerHTML = '';
        state.mountedTabs.forEach(function(tabKey) {
            row.appendChild(makeChip(tabKey, chipTextForTab(tabKey)));
        });
    }

    function renderTabs() {
        var bar = document.getElementById('single-factor-page-settings-tabs');
        if (!bar) return;
        bar.innerHTML = '';
        state.mountedTabs.forEach(function(tabKey) {
            var meta = tabMeta(tabKey);
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.textContent = meta ? meta.label : tabKey;
            btn.className = state.activeTab === tabKey ? 'active' : '';
            btn.addEventListener('click', function() {
                openTab(state.activeTab === tabKey ? null : tabKey);
            });
            bar.appendChild(btn);
        });
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
        state.mountedTabs.forEach(function(tabKey) {
            var panel = document.createElement('div');
            panel.className = 'single-factor-page-settings-panel';
            panel.setAttribute('data-page-settings-tab-panel', tabKey);
            panel.style.display = 'none';
            host.appendChild(panel);
            state.containers[tabKey] = panel;
        });
        movePanelContent('global-tpl-drawer', 'setting_template');
        movePanelContent('param-drawer', 'parameters');
        movePanelContent('time-range-drawer', 'time');
        hideLegacyRows();
        renderTabs();
        renderChips();
    }

    function openTab(tabKey) {
        state.activeTab = tabKey || null;
        Object.keys(state.containers).forEach(function(key) {
            state.containers[key].style.display = key === state.activeTab ? '' : 'none';
        });
        var host = document.getElementById('single-factor-page-settings-host');
        if (host) host.style.display = state.activeTab ? '' : 'none';
        renderTabs();
        renderChips();
        if (tabKey === 'parameters' && window.MathJax && window.MathJax.typesetPromise) {
            window.MathJax.typesetPromise([document.getElementById('pm-math-block')].filter(Boolean)).then(function() {
                if (window.fitMathJaxToContainer) window.fitMathJaxToContainer(document.getElementById('pm-math-block'));
            });
        }
    }

    function observeSummaries() {
        ['global-tpl-load-status', 'time-summary-text', 'factor_table_body'].forEach(function(id) {
            var node = document.getElementById(id);
            if (!node || !window.MutationObserver) return;
            new MutationObserver(renderChips).observe(node, { childList: true, characterData: true, subtree: true });
        });
    }

    function init() {
        requestJSON('/api/backtest/settings/' + APP).then(function(manifest) {
            state.manifest = manifest;
            state.mountedTabs = (manifest.default_mounted_tabs && manifest.default_mounted_tabs[LOCAL] || []).slice();
            renderShell();
            observeSummaries();
            openTab(null);
        }).catch(function(error) {
            console.error('[single-factor-page-settings] init failed:', error);
        });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
