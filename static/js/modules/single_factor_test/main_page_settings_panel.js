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

    function makeChip(tabKey, label, value) {
        var chip = document.createElement('span');
        chip.className = 'gt-backend-chip';
        chip.innerHTML = renderChipHtml(label, value);
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
        if (tabKey === 'parameters') {
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

    function paramSummaryValue() {
        var tbody = document.getElementById('factor_table_body');
        var rows = tbody ? Array.from(tbody.querySelectorAll('tr')).filter(function(row) {
            return row.id !== 'add_row' && row.style.display !== 'none';
        }) : [];
        return '已设置' + rows.length;
    }

    function templateSummaryValue() {
        return window._currentSingleFactorTemplateName || '无';
    }

    function displayValue(setting, value) {
        if (setting && Array.isArray(setting.options)) {
            for (var i = 0; i < setting.options.length; i++) {
                if (String(setting.options[i].value) === String(value)) return setting.options[i].label;
            }
        }
        return value === undefined || value === null || value === '' ? '默认' : String(value);
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
        if (tabKey === 'parameters') return [{ label: '参数组合', value: paramSummaryValue() }];
        return registeredTabChipParts(tabKey);
    }

    function renderChips() {
        var row = document.getElementById('single-factor-page-settings-chips');
        if (!row) return;
        row.innerHTML = '';
        state.mountedTabs.forEach(function(tabKey) {
            chipPartsForTab(tabKey).forEach(function(parts) {
                row.appendChild(makeChip(tabKey, parts.label, parts.value));
            });
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
                openTab(tabKey);
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
        var visibleWhen = setting && setting.visible_when || {};
        return Object.keys(visibleWhen).every(function(key) {
            var allowed = visibleWhen[key];
            if (!Array.isArray(allowed)) allowed = [allowed];
            return allowed.map(String).indexOf(String(values[key])) >= 0;
        });
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
            syncRegisteredTimeRange();
            renderChips();
        });
        return control;
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
            status.textContent = '正在同步页面默认时间范围...';
            status.style.color = '#2563eb';
        }
        fetch('/set_time_range', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }).then(function(res) { return res.json(); }).then(function(data) {
            if (!data.success) throw new Error(data.error || '保存失败');
            if (data.page_uuid && typeof window.rememberSingleFactorPageUuid === 'function') {
                window.rememberSingleFactorPageUuid(data.page_uuid);
            }
            if (typeof window.applySharedRuntimeTimeRange === 'function') {
                window.applySharedRuntimeTimeRange(payload, { persist: false });
            }
            document.dispatchEvent(new CustomEvent('pageTimeRangeChanged', { detail: payload }));
            if (status) {
                status.textContent = '已同步';
                status.style.color = '#16a34a';
            }
            renderChips();
        }).catch(function(error) {
            if (status) {
                status.textContent = error.message;
                status.style.color = '#dc2626';
            }
        });
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

    function observeSummaries() {
        ['global-tpl-save-status', 'time-summary-text', 'factor_table_body'].forEach(function(id) {
            var node = document.getElementById(id);
            if (!node || !window.MutationObserver) return;
            new MutationObserver(renderChips).observe(node, { childList: true, characterData: true, subtree: true });
        });
        document.addEventListener('singleFactorTemplateChanged', renderChips);
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
            openTab(null);
        }).catch(function(error) {
            console.error('[single-factor-page-settings] init failed:', error);
        });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
