/** User-mounted, backend-registered, per-tab lazy backtest settings. */
(function() {
    var GT = window.GroupTest;
    if (!GT) { console.warn('[GT backend-settings] bootstrap missing'); return; }

    var LOCAL = 'local-settings';
    var GROUP = 'group-settings';
    var state = {
        application: 'group_test',
        index: null,
        tabCache: Object.create(null),
        tabRequests: Object.create(null),
        mountedTabs: { 'local-settings': [], 'group-settings': [] },
        localValues: Object.create(null),
        groupValues: Object.create(null),
        activeGroup: null,
        groupTabsAttached: false,
    };

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

    function availableTabs(mount) {
        return state.index && state.index.tab_lists ? (state.index.tab_lists[mount] || []) : [];
    }

    function tabURL(tabKey) {
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

    function defaultsForTab(tabKey) {
        var out = [];
        var defaults = state.index && state.index.defaults || {};
        Object.keys(defaults).forEach(function(key) {
            if (defaults[key].tab_key === tabKey) out.push({ key: key, value: defaults[key].value });
        });
        return out;
    }

    function groupStore() {
        if (!state.activeGroup) return null;
        if (!state.groupValues[state.activeGroup]) state.groupValues[state.activeGroup] = Object.create(null);
        return state.groupValues[state.activeGroup];
    }

    function effectiveValue(setting, mount) {
        var groups = groupStore();
        if (mount === GROUP && groups && Object.prototype.hasOwnProperty.call(groups, setting.key)) {
            return groups[setting.key];
        }
        if (Object.prototype.hasOwnProperty.call(state.localValues, setting.key)) {
            return state.localValues[setting.key];
        }
        return state.index.defaults[setting.key].value;
    }

    function writeValue(setting, mount, value) {
        if (mount === GROUP) {
            var groups = groupStore();
            if (!groups) throw new Error('编辑组合设置前必须选择组合');
            groups[setting.key] = value;
        } else {
            state.localValues[setting.key] = value;
        }
    }

    function chip(text, muted) {
        var node = document.createElement('span');
        node.textContent = text;
        node.style.cssText = 'padding:3px 7px;border-radius:999px;font-size:11px;' + (
            muted ? 'background:#f1f5f9;color:#64748b;' : 'background:#eef2ff;color:#3730a3;'
        );
        return node;
    }

    function makeControl(setting, mount, rerenderChips) {
        var control;
        if (setting.control_template === 'select') {
            control = document.createElement('select');
            (setting.options || []).forEach(function(item) {
                var option = document.createElement('option');
                option.value = item.value;
                option.textContent = item.label;
                control.appendChild(option);
            });
        } else if (setting.control_template === 'number' || setting.control_template === 'date') {
            control = document.createElement('input');
            control.type = setting.control_template;
            [['min', 'minimum'], ['max', 'maximum'], ['step', 'step']].forEach(function(pair) {
                if (setting[pair[1]] !== null && setting[pair[1]] !== undefined) control.setAttribute(pair[0], setting[pair[1]]);
            });
        } else {
            throw new Error('不支持的控件模板: ' + setting.control_template);
        }
        control.value = effectiveValue(setting, mount);
        control.disabled = mount === GROUP && !state.activeGroup;
        control.addEventListener('change', function() {
            writeValue(setting, mount, setting.control_template === 'number' ? Number(control.value) : control.value);
            rerenderChips();
        });
        return control;
    }

    function renderManifest(manifest, mount, container) {
        if (!manifest.tab || manifest.tab.layout_template !== 'settings-grid') {
            throw new Error('不支持的页签布局模板: ' + (manifest.tab && manifest.tab.layout_template));
        }
        container.innerHTML = '';
        var chips = document.createElement('div');
        chips.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;';
        var grid = document.createElement('div');
        grid.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px;';

        function renderChips() {
            chips.innerHTML = '';
            (manifest.settings || []).forEach(function(setting) {
                if (!setting.chip_template) return;
                if (mount === GROUP) {
                    var values = groupStore();
                    if (!values || !Object.prototype.hasOwnProperty.call(values, setting.key)) return;
                }
                chips.appendChild(chip(
                    setting.chip_template.replace('{value}', String(effectiveValue(setting, mount))),
                    false
                ));
            });
            chips.style.display = chips.childNodes.length ? 'flex' : 'none';
        }

        (manifest.settings || []).forEach(function(setting) {
            var row = document.createElement('label');
            row.style.cssText = 'display:flex;flex-direction:column;gap:6px;padding:10px;border:1px solid #e5e7eb;border-radius:6px;background:#fcfcfd;';
            var title = document.createElement('span');
            title.textContent = setting.label;
            title.style.fontWeight = '600';
            row.appendChild(title);
            row.appendChild(makeControl(setting, mount, renderChips));
            grid.appendChild(row);
        });
        renderChips();
        container.appendChild(chips);
        container.appendChild(grid);
    }

    function activateTab(tabKey, mount, container) {
        container.innerHTML = '<span style="color:#64748b;font-size:12px;">正在加载...</span>';
        return loadTab(tabKey).then(function(manifest) {
            renderManifest(manifest, mount, container);
            return manifest;
        }).catch(function(error) {
            container.textContent = '加载失败：' + error.message;
            throw error;
        });
    }

    function isMounted(mount, tabKey) {
        return state.mountedTabs[mount].indexOf(tabKey) >= 0;
    }

    function toggleMounted(mount, tabKey, enabled) {
        var tabs = state.mountedTabs[mount];
        var index = tabs.indexOf(tabKey);
        if (enabled && index < 0) tabs.push(tabKey);
        if (!enabled && index >= 0) tabs.splice(index, 1);
        if (mount === LOCAL) renderLocalTabs();
        if (mount === GROUP && GT.tabs && GT.tabs.refreshTabBar) GT.tabs.refreshTabBar();
    }

    function renderChooser(mount, container) {
        container.innerHTML = '';
        var intro = document.createElement('div');
        intro.textContent = '选择要挂载到此栏的回测设置。未挂载项继续使用下列默认值。';
        intro.style.cssText = 'font-size:12px;color:#64748b;margin-bottom:10px;';
        container.appendChild(intro);
        availableTabs(mount).forEach(function(tab) {
            var row = document.createElement('label');
            row.style.cssText = 'display:flex;align-items:flex-start;gap:8px;padding:8px 0;border-top:1px solid #eef2f7;';
            var checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.checked = isMounted(mount, tab.key);
            checkbox.addEventListener('change', function() { toggleMounted(mount, tab.key, checkbox.checked); });
            var body = document.createElement('div');
            var title = document.createElement('div');
            title.textContent = tab.label;
            title.style.fontWeight = '600';
            body.appendChild(title);
            var defaults = document.createElement('div');
            defaults.style.cssText = 'display:flex;gap:5px;flex-wrap:wrap;margin-top:5px;';
            defaultsForTab(tab.key).forEach(function(item) {
                defaults.appendChild(chip(item.key + ': ' + item.value, true));
            });
            body.appendChild(defaults);
            row.appendChild(checkbox);
            row.appendChild(body);
            container.appendChild(row);
        });
    }

    function localHost() { return document.getElementById('gt-backtest-local-host'); }

    function deactivateLocal() {
        var host = localHost();
        if (host) host.style.display = 'none';
        document.querySelectorAll('[data-backtest-local-tab]').forEach(function(button) {
            button.classList.remove('active');
        });
    }

    function openLocal(tabKey) {
        document.querySelectorAll('[data-local-settings-tab-panel]').forEach(function(panel) { panel.style.display = 'none'; });
        document.querySelectorAll('[data-local-settings-tab-btn]').forEach(function(button) { button.classList.remove('active'); });
        var host = localHost();
        host.style.display = '';
        document.querySelectorAll('[data-backtest-local-tab]').forEach(function(button) {
            button.classList.toggle('active', button.getAttribute('data-backtest-local-tab') === tabKey);
        });
        if (tabKey === '__manage__') renderChooser(LOCAL, host);
        else activateTab(tabKey, LOCAL, host).catch(function(error) { console.error(error); });
    }

    function renderLocalTabs() {
        var bar = document.getElementById('gt-local-settings-tab-bar');
        if (!bar || !state.index) return;
        bar.querySelectorAll('[data-backtest-local-tab]').forEach(function(node) { node.remove(); });
        availableTabs(LOCAL).forEach(function(tab) {
            if (!isMounted(LOCAL, tab.key)) return;
            var button = document.createElement('button');
            button.type = 'button';
            button.className = 'btn btn-sm btn-outline-secondary';
            button.textContent = tab.label;
            button.setAttribute('data-backtest-local-tab', tab.key);
            button.addEventListener('click', function() { openLocal(tab.key); });
            bar.appendChild(button);
        });
        var manage = document.createElement('button');
        manage.type = 'button';
        manage.className = 'btn btn-sm btn-outline-secondary';
        manage.textContent = '+ 回测设置';
        manage.setAttribute('data-backtest-local-tab', '__manage__');
        manage.addEventListener('click', function() { openLocal('__manage__'); });
        bar.appendChild(manage);
    }

    function setActiveGroupFromUI() {
        var registry = window.GT_CONFIG_REGISTRY;
        var group = registry && registry.getReferenceGroup ? registry.getReferenceGroup() : null;
        state.activeGroup = group && group.id ? String(group.id) : null;
    }

    function groupPanel(tabKey) {
        return {
            mount: function(container) {
                setActiveGroupFromUI();
                activateTab(tabKey, GROUP, container).catch(function(error) { console.error(error); });
            },
            unmount: function() {},
        };
    }

    function attachGroupTabs() {
        if (state.groupTabsAttached || !state.index || !GT.tabs) return;
        state.groupTabsAttached = true;
        availableTabs(GROUP).forEach(function(tab) {
            GT.tabs.registerPanel({
                name: 'backend-' + tab.key,
                label: tab.label,
                containerId: 'gt-backend-group-' + tab.key,
                category: 3,
                visible: function() { return isMounted(GROUP, tab.key); },
                panel: groupPanel(tab.key),
            });
        });
        GT.tabs.registerPanel({
            name: 'backend-settings-manage',
            label: '+ 回测设置',
            containerId: 'gt-backend-group-manage',
            category: 3,
            panel: {
                mount: function(container) { renderChooser(GROUP, container); },
                unmount: function() {},
            },
        });
    }

    function init() {
        var root = localHost();
        if (root) state.application = root.getAttribute('data-application') || state.application;
        var pageUuid = encodeURIComponent(window._pageUuid || '');
        return requestJSON('/api/backtest/settings/' + encodeURIComponent(state.application) + '?page_uuid=' + pageUuid).then(function(index) {
            state.index = index;
            Object.keys(index.defaults || {}).forEach(function(key) {
                if (!Object.prototype.hasOwnProperty.call(state.localValues, key)) {
                    state.localValues[key] = index.defaults[key].value;
                }
            });
            var defaults = index.default_mounted_tabs || {};
            [LOCAL, GROUP].forEach(function(mount) {
                if (!state.mountedTabs[mount].length && Array.isArray(defaults[mount])) {
                    state.mountedTabs[mount] = defaults[mount].slice();
                }
            });
            renderLocalTabs();
            attachGroupTabs();
            return index;
        });
    }

    function apply(snapshot) {
        snapshot = snapshot || {};
        [LOCAL, GROUP].forEach(function(mount) {
            state.mountedTabs[mount] = Array.isArray(snapshot.mounted_tabs && snapshot.mounted_tabs[mount])
                ? snapshot.mounted_tabs[mount].slice()
                : [];
        });
        state.localValues = Object.assign(Object.create(null), snapshot.local_values || {});
        state.groupValues = Object.assign(Object.create(null), snapshot.group_values || {});
        renderLocalTabs();
        if (GT.tabs && GT.tabs.refreshTabBar) GT.tabs.refreshTabBar();
    }

    function registerSnapshot() {
        if (!GT.localSettings || state.snapshotRegistered) return;
        state.snapshotRegistered = true;
        GT.localSettings.register({
            key: 'backendBacktestSettings',
            order: 90,
            collect: collect,
            apply: apply,
            summarize: function() { return null; },
        });
    }

    function collect() {
        return JSON.parse(JSON.stringify({
            application: state.application,
            mounted_tabs: state.mountedTabs,
            local_values: state.localValues,
            group_values: state.groupValues,
        }));
    }

    function runPayload() {
        var values = state.localValues || {};
        var calendar = String(values.calendar_frequency || 'auto');
        return {
            start_date: values.start_date,
            end_date: values.end_date,
            precision: values.time_precision || 'exact',
            timezone: values.timezone || 'Asia/Shanghai',
            initial_capital: values.initial_capital,
            base_currency: values.base_currency || 'CNY',
            currency_conversion_fee_rate: values.currency_conversion_fee_rate || 0,
            auto_group_calendar_freq: calendar === 'auto',
            group_calendar_freq: calendar === 'auto' ? null : calendar,
        };
    }

    GT.backendSettings = {
        init: init,
        attachGroupTabs: attachGroupTabs,
        deactivateLocal: deactivateLocal,
        registerSnapshot: registerSnapshot,
        collect: collect,
        runPayload: runPayload,
        _state: state,
    };
})();
