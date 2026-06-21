/** Backend-registered backtest settings with per-tab network lazy loading. */
(function() {
    var GT = window.GroupTest;
    if (!GT) { console.warn('[GT backend-settings] bootstrap missing'); return; }
    if (GT.backendSettings) { console.warn('[GT backend-settings] already loaded'); return; }

    var state = {
        application: null,
        index: null,
        activeTab: null,
        activeStrategy: null,
        tabCache: Object.create(null),
        tabRequests: Object.create(null),
        scopes: Object.create(null),
        sharedValues: Object.create(null),
        strategyValues: Object.create(null),
    };

    function element(id) { return document.getElementById(id); }

    function setStatus(message, isError) {
        var target = element('gt-backtest-settings-status');
        if (!target) return;
        target.textContent = message || '';
        target.style.color = isError ? '#b42318' : '#64748b';
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

    function tabURL(tabKey) {
        if (!state.index || !state.index.tab_url_template) throw new Error('设置目录缺少 tab_url_template');
        return state.index.tab_url_template.replace('{tab_key}', encodeURIComponent(tabKey));
    }

    function loadTab(tabKey) {
        if (state.tabCache[tabKey]) return Promise.resolve(state.tabCache[tabKey]);
        if (state.tabRequests[tabKey]) return state.tabRequests[tabKey];
        state.tabRequests[tabKey] = requestJSON(tabURL(tabKey)).then(function(manifest) {
            if (!manifest.tab || manifest.tab.key !== tabKey) throw new Error('后端返回了不匹配的设置页签');
            state.tabCache[tabKey] = manifest;
            delete state.tabRequests[tabKey];
            return manifest;
        }).catch(function(error) {
            delete state.tabRequests[tabKey];
            throw error;
        });
        return state.tabRequests[tabKey];
    }

    function strategyValues() {
        if (!state.activeStrategy) return null;
        if (!state.strategyValues[state.activeStrategy]) {
            state.strategyValues[state.activeStrategy] = Object.create(null);
        }
        return state.strategyValues[state.activeStrategy];
    }

    function settingScope(setting) {
        return state.scopes[setting.key] || setting.default_scope;
    }

    function settingValue(setting) {
        var scope = settingScope(setting);
        if (scope === 'strategy') {
            var values = strategyValues();
            if (values && Object.prototype.hasOwnProperty.call(values, setting.key)) return values[setting.key];
        }
        if (Object.prototype.hasOwnProperty.call(state.sharedValues, setting.key)) return state.sharedValues[setting.key];
        return setting.default;
    }

    function writeValue(setting, value) {
        if (settingScope(setting) === 'strategy') {
            var values = strategyValues();
            if (!values) throw new Error('按策略设置前必须选择策略');
            values[setting.key] = value;
        } else {
            state.sharedValues[setting.key] = value;
        }
    }

    function makeScopeSelect(setting, rerender) {
        if (setting.scope_policy !== 'selectable') return null;
        var select = document.createElement('select');
        select.setAttribute('aria-label', setting.label + '作用域');
        [['shared', '所有策略共用'], ['strategy', '每个策略']].forEach(function(item) {
            var option = document.createElement('option');
            option.value = item[0];
            option.textContent = item[1];
            select.appendChild(option);
        });
        select.value = settingScope(setting);
        select.addEventListener('change', function() {
            state.scopes[setting.key] = select.value;
            rerender();
        });
        return select;
    }

    function makeControl(setting) {
        var control;
        if (setting.control_template === 'select') {
            control = document.createElement('select');
            (setting.options || []).forEach(function(item) {
                var option = document.createElement('option');
                option.value = item.value;
                option.textContent = item.label;
                control.appendChild(option);
            });
        } else if (setting.control_template === 'number') {
            control = document.createElement('input');
            control.type = 'number';
            ['min', 'max', 'step'].forEach(function(attribute) {
                var source = attribute === 'min' ? 'minimum' : attribute === 'max' ? 'maximum' : 'step';
                if (setting[source] !== null && setting[source] !== undefined) control.setAttribute(attribute, setting[source]);
            });
        } else {
            throw new Error('不支持的控件模板: ' + setting.control_template);
        }
        control.id = 'gt-backtest-setting-' + setting.key;
        control.value = settingValue(setting);
        control.disabled = settingScope(setting) === 'strategy' && !state.activeStrategy;
        control.addEventListener('change', function() {
            var value = setting.control_template === 'number' ? Number(control.value) : control.value;
            writeValue(setting, value);
            if (state.activeTab && state.tabCache[state.activeTab]) renderChips(state.tabCache[state.activeTab]);
        });
        return control;
    }

    function renderChips(manifest) {
        var target = element('gt-backtest-settings-chips');
        if (!target) return;
        target.innerHTML = '';
        (manifest.settings || []).forEach(function(setting) {
            if (!setting.chip_template) return;
            var chip = document.createElement('span');
            chip.textContent = setting.chip_template.replace('{value}', String(settingValue(setting)));
            chip.style.cssText = 'padding:3px 7px;border-radius:999px;background:#eef2ff;color:#3730a3;font-size:11px;';
            target.appendChild(chip);
        });
        target.style.display = target.childNodes.length ? 'flex' : 'none';
    }

    function renderSettingsGrid(manifest, panel) {
        var grid = document.createElement('div');
        grid.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px;';
        (manifest.settings || []).forEach(function(setting) {
            var row = document.createElement('div');
            row.style.cssText = 'display:flex;flex-direction:column;gap:6px;padding:10px;border:1px solid #e5e7eb;border-radius:6px;background:#fcfcfd;';
            var header = document.createElement('div');
            header.style.cssText = 'display:flex;align-items:center;justify-content:space-between;gap:8px;';
            var label = document.createElement('label');
            label.htmlFor = 'gt-backtest-setting-' + setting.key;
            label.textContent = setting.label;
            label.style.fontWeight = '600';
            header.appendChild(label);
            var scope = makeScopeSelect(setting, function() { renderManifest(manifest); });
            if (scope) header.appendChild(scope);
            row.appendChild(header);
            row.appendChild(makeControl(setting));
            if (setting.help_text) {
                var help = document.createElement('span');
                help.textContent = setting.help_text;
                help.style.cssText = 'font-size:11px;color:#64748b;';
                row.appendChild(help);
            }
            grid.appendChild(row);
        });
        panel.appendChild(grid);
    }

    var layoutRenderers = {
        'settings-grid': renderSettingsGrid,
    };

    function renderManifest(manifest) {
        var panel = element('gt-backtest-settings-panel');
        if (!panel) return;
        var template = manifest.tab && manifest.tab.layout_template;
        var renderer = layoutRenderers[template];
        if (!renderer) throw new Error('不支持的页签布局模板: ' + template);
        panel.innerHTML = '';
        renderer(manifest, panel);
        renderChips(manifest);
    }

    function activateTab(tabKey) {
        state.activeTab = tabKey;
        document.querySelectorAll('[data-backtest-settings-tab]').forEach(function(button) {
            var active = button.getAttribute('data-backtest-settings-tab') === tabKey;
            button.classList.toggle('active', active);
            button.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        var panel = element('gt-backtest-settings-panel');
        if (panel) panel.textContent = '正在加载...';
        setStatus('正在加载页签...');
        return loadTab(tabKey).then(function(manifest) {
            if (state.activeTab !== tabKey) return manifest;
            renderManifest(manifest);
            setStatus('已加载');
            return manifest;
        }).catch(function(error) {
            if (state.activeTab === tabKey && panel) panel.textContent = '加载失败：' + error.message;
            setStatus('加载失败', true);
            throw error;
        });
    }

    function renderIndex(index) {
        var tabBar = element('gt-backtest-settings-tabs');
        if (!tabBar) return;
        tabBar.innerHTML = '';
        (index.tabs || []).forEach(function(tab) {
            var button = document.createElement('button');
            button.type = 'button';
            button.className = 'btn btn-sm btn-outline-secondary';
            button.textContent = tab.label;
            button.setAttribute('role', 'tab');
            button.setAttribute('aria-selected', 'false');
            button.setAttribute('data-backtest-settings-tab', tab.key);
            button.addEventListener('click', function() {
                activateTab(tab.key).catch(function(error) {
                    console.error('[GT backend-settings] tab load failed', error);
                });
            });
            tabBar.appendChild(button);
        });
    }

    function init() {
        var root = element('gt-backtest-settings');
        if (!root || state.index) return Promise.resolve(state.index);
        state.application = root.getAttribute('data-application');
        return requestJSON('/api/backtest/settings/' + encodeURIComponent(state.application)).then(function(index) {
            state.index = index;
            renderIndex(index);
            setStatus('选择页签后按需加载');
            return index;
        }).catch(function(error) {
            setStatus('设置目录加载失败：' + error.message, true);
            throw error;
        });
    }

    function setActiveStrategy(strategyId) {
        state.activeStrategy = strategyId === null || strategyId === undefined ? null : String(strategyId);
        if (state.activeTab && state.tabCache[state.activeTab]) renderManifest(state.tabCache[state.activeTab]);
    }

    function collect() {
        return {
            application: state.application,
            scopes: JSON.parse(JSON.stringify(state.scopes)),
            shared_values: JSON.parse(JSON.stringify(state.sharedValues)),
            strategy_values: JSON.parse(JSON.stringify(state.strategyValues)),
        };
    }

    GT.backendSettings = {
        init: init,
        activateTab: activateTab,
        setActiveStrategy: setActiveStrategy,
        collect: collect,
        _state: state,
    };
})();
