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
        activeGroup: null,
        activeLocalTab: null,
        groupTabsAttached: false,
        settingDefs: Object.create(null),
        expandedProductMasks: Object.create(null),
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

    function tabExists(mount, tabKey) {
        return availableTabs(mount).some(function(tab) { return tab.key === tabKey; });
    }

    function ensureMounted(mount, tabKey) {
        if (!tabKey || !tabExists(mount, tabKey)) return;
        var tabs = state.mountedTabs[mount];
        if (tabs.indexOf(tabKey) < 0) tabs.push(tabKey);
    }

    function settingTab(key) {
        var def = state.index && state.index.defaults && state.index.defaults[key];
        return def ? def.tab_key : null;
    }

    function settingKeysForTab(tabKey) {
        var defaults = state.index && state.index.defaults || {};
        return Object.keys(defaults).filter(function(key) {
            return defaults[key] && defaults[key].tab_key === tabKey;
        });
    }

    function settingIsShownInMountedTab(mount, key) {
        var meta = state.index && state.index.defaults && state.index.defaults[key];
        var tabKey = meta && meta.tab_key;
        if (!tabKey) return false;
        return state.mountedTabs[mount] && state.mountedTabs[mount].indexOf(tabKey) >= 0;
    }

    function tabMeta(tabKey) {
        var tabs = []
            .concat(availableTabs(LOCAL))
            .concat(availableTabs(GROUP));
        for (var i = 0; i < tabs.length; i++) {
            if (tabs[i].key === tabKey) return tabs[i];
        }
        return null;
    }

    function formatTemplate(template, values) {
        return String(template || '').replace(/\{([^}]+)\}/g, function(_, key) {
            return values[key] === undefined || values[key] === null ? '' : String(values[key]);
        }).replace(/\s+/g, ' ').trim();
    }

    function displayValue(setting, value) {
        if (setting && Array.isArray(setting.options)) {
            for (var i = 0; i < setting.options.length; i++) {
                if (String(setting.options[i].value) === String(value)) return setting.options[i].label;
            }
        }
        return value === undefined || value === null ? '' : String(value);
    }

    function escapeHTML(str) {
        if (GT.escapeHTML) return GT.escapeHTML(str);
        return String(str == null ? '' : str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function chipText(setting, value) {
        var template = setting && setting.chip_template ? setting.chip_template : ((setting && setting.key || '') + ': {value}');
        return template.replace('{value}', displayValue(setting, value));
    }

    function chipParts(labelOrText, value) {
        if (value !== undefined && value !== null && value !== '') {
            return { label: String(labelOrText || ''), value: String(value) };
        }
        var text = String(labelOrText == null ? '' : labelOrText).trim();
        var match = text.match(/^([^:：]{1,16})[:：]\s*(.*)$/);
        if (match && match[2] && /^[A-Za-z0-9_\u4e00-\u9fa5 \-]+$/.test(match[1])) {
            return { label: match[1], value: match[2] };
        }
        return { label: '', value: text };
    }

    function renderChipHtml(labelOrText, value) {
        var parts = chipParts(labelOrText, value);
        if (!parts.label) return '<span class="gt-backend-chip-value">' + escapeHTML(parts.value) + '</span>';
        return '<span class="gt-backend-chip-label">' + escapeHTML(parts.label) + '</span>'
            + '<span class="gt-backend-chip-value">' + escapeHTML(parts.value) + '</span>';
    }

    function valuesEqual(left, right) {
        if (left === right) return true;
        if (left === undefined && right === null) return true;
        if (left === null && right === undefined) return true;
        if (typeof left === 'number' || typeof right === 'number') return Number(left) === Number(right);
        return String(left) === String(right);
    }

    function resolveRootGroup(group) {
        var current = group;
        var seen = {};
        while (current && current.parentId && GT.groupSettings && GT.groupSettings.groups && GT.groupSettings.groups.get) {
            if (seen[current.id]) break;
            seen[current.id] = true;
            current = GT.groupSettings.groups.get(current.parentId);
        }
        return current || group;
    }

    function testerProducts(testerId) {
        var subs = window.submissions || [];
        for (var si = 0; si < subs.length; si++) {
            if (String(subs[si].id) !== String(testerId)) continue;
            var raw = (Array.isArray(subs[si].products) && subs[si].products.length)
                ? subs[si].products
                : (subs[si].product_groups || []);
            return raw.map(function(item) {
                if (typeof item === 'string') return { name: item, desc: '' };
                return item && item.name ? { name: item.name, desc: item.desc || '' } : null;
            }).filter(Boolean);
        }
        return [];
    }

    function testerLabel(testerId) {
        var subs = window.submissions || [];
        for (var si = 0; si < subs.length; si++) {
            if (String(subs[si].id) === String(testerId)) {
                return subs[si].product_group || subs[si].label || ('测试器 #' + subs[si].id);
            }
        }
        return testerId ? String(testerId) : '';
    }

    function nodeProducts(group, seen) {
        if (!group) return [];
        seen = seen || {};
        if (group.id && seen[group.id]) return [];
        if (group.id) seen[group.id] = true;
        var inherited = [];
        if (group.parentId && GT.groupSettings && GT.groupSettings.groups) {
            inherited = nodeProducts(GT.groupSettings.groups.get(group.parentId), seen);
        } else {
            inherited = testerProducts(group.testerId);
        }
        var mask = group.productMask || {};
        if (!mask || Object.keys(mask).length === 0) return inherited;
        return inherited.filter(function(product) { return product && mask[product.name]; });
    }

    function sameProductNames(left, right) {
        var a = (left || []).map(function(p) { return p && p.name; }).filter(Boolean);
        var b = (right || []).map(function(p) { return p && p.name; }).filter(Boolean);
        if (a.length !== b.length) return false;
        for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
        return true;
    }

    function chipSourceGroup(group, chipDef) {
        return chipDef && chipDef.inherit_from_root ? resolveRootGroup(group) : group;
    }

    function resolveChipValue(name, group, source, resolvers) {
        var resolver = resolvers && resolvers[name];
        if (resolver === 'tester_label') return testerLabel(source && source.testerId);
        if (resolver === 'product_mask_count') return nodeProducts(group).length;
        if (resolver === 'product_mask_expand_symbol') return state.expandedProductMasks && state.expandedProductMasks[group.id] ? '▾' : '▸';
        return source && source[name] != null ? source[name] : '';
    }

    function renderChipTemplate(template, group, source, resolvers) {
        return String(template || '').replace(/\{([^}]+)\}/g, function(_, key) {
            return escapeHTML(resolveChipValue(key, group, source, resolvers));
        }).replace(/\s+/g, ' ').trim();
    }

    function summaryTabs() {
        return availableTabs(LOCAL).filter(function(tab) {
            return !!tab.summary_template;
        });
    }

    function summaryOverrides(values) {
        values = values || state.localValues || {};
        return summaryTabs().map(function(tab) {
            var keys = Array.isArray(tab.summary_keys) && tab.summary_keys.length
                ? tab.summary_keys
                : settingKeysForTab(tab.key);
            var hasAny = keys.some(function(key) {
                return Object.prototype.hasOwnProperty.call(values, key)
                    && values[key] !== ''
                    && values[key] !== null
                    && values[key] !== undefined;
            });
            if (!hasAny) return null;
            return {
                tab: tab,
                text: formatTemplate(tab.summary_template, effectiveLocalValues()),
            };
        }).filter(Boolean);
    }

    function clearTabOverrides(mount, tabKey) {
        var keys = settingKeysForTab(tabKey);
        if (!keys.length) return;
        if (mount === LOCAL) {
            keys.forEach(function(key) { delete state.localValues[key]; });
            return;
        }
        var groups = GT.groupSettings && GT.groupSettings.groups && GT.groupSettings.groups.getAll
            ? GT.groupSettings.groups.getAll()
            : [];
        groups.forEach(function(group) {
            var patch = {};
            keys.forEach(function(key) { patch[key] = undefined; });
            try { GT.groupSettings.groups.update(group.id, patch); } catch (error) {}
        });
    }

    function mountTabsForSnapshotValues(mount, values) {
        Object.keys(values || {}).forEach(function(key) {
            ensureMounted(mount, settingTab(key));
        });
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
            (manifest.settings || []).forEach(function(setting) {
                state.settingDefs[setting.key] = setting;
            });
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
        var values = effectiveLocalValues();
        Object.keys(defaults).forEach(function(key) {
            if (defaults[key].tab_key === tabKey && settingVisibleForValues(defaults[key], values)) {
                out.push({ key: key, value: defaults[key].value });
            }
        });
        return out;
    }

    function activeNode() {
        if (!state.activeGroup) return null;
        var groups = GT.groupSettings && GT.groupSettings.groups;
        var lsConfigs = GT.groupSettings && GT.groupSettings.lsConfigs;
        if (groups && groups.get) {
            var group = groups.get(state.activeGroup);
            if (group) return { kind: 'group', value: group };
        }
        if (lsConfigs && lsConfigs.get) {
            var ls = lsConfigs.get(state.activeGroup);
            if (ls) return { kind: 'ls', value: ls };
        }
        return null;
    }

    function effectiveValue(setting, mount) {
        var node = activeNode();
        if (mount === GROUP && node && Object.prototype.hasOwnProperty.call(node.value, setting.key)) {
            return node.value[setting.key];
        }
        if (Object.prototype.hasOwnProperty.call(state.localValues, setting.key)) {
            return state.localValues[setting.key];
        }
        return state.index.defaults[setting.key].value;
    }

    function effectiveLocalValues() {
        var values = Object.create(null);
        Object.keys(state.index && state.index.defaults || {}).forEach(function(key) {
            values[key] = state.index.defaults[key].value;
        });
        Object.keys(state.localValues || {}).forEach(function(key) {
            values[key] = state.localValues[key];
        });
        return values;
    }

    function effectiveValuesForNode(node) {
        var values = effectiveLocalValues();
        Object.keys((node && node.value) || node || {}).forEach(function(key) {
            values[key] = ((node && node.value) || node)[key];
        });
        return values;
    }

    function settingVisibleForValues(setting, values) {
        var visibleWhen = setting && setting.visible_when;
        if (!visibleWhen || !Object.keys(visibleWhen).length) return true;
        return Object.keys(visibleWhen).every(function(depKey) {
            var allowed = visibleWhen[depKey] || [];
            return allowed.map(String).indexOf(String(values[depKey])) >= 0;
        });
    }

    function settingVisible(setting, mount) {
        var node = mount === GROUP ? activeNode() : null;
        return settingVisibleForValues(setting, effectiveValuesForNode(node));
    }

    function writeValue(setting, mount, value) {
        if (mount === GROUP) {
            var node = activeNode();
            if (!node) throw new Error('编辑组合设置前必须选择组合');
            var patch = {};
            patch[setting.key] = value;
            if (node.kind === 'group') GT.groupSettings.groups.update(state.activeGroup, patch);
            else GT.groupSettings.lsConfigs.update(state.activeGroup, patch);
        } else {
            state.localValues[setting.key] = value;
            renderLocalSettingChips();
        }
    }

    function chip(text, muted) {
        var node = document.createElement('span');
        node.className = 'gt-backend-chip' + (muted ? ' is-muted' : '');
        node.innerHTML = renderChipHtml(text);
        return node;
    }

    function makeControl(setting, mount, rerenderAfterChange) {
        var control;
        if (setting.control_template === 'select') {
            control = document.createElement('select');
            (setting.options || []).forEach(function(item) {
                var option = document.createElement('option');
                option.value = item.value;
                option.textContent = item.label;
                control.appendChild(option);
            });
        } else if (setting.control_template === 'number' || setting.control_template === 'date' || setting.control_template === 'time') {
            control = document.createElement('input');
            control.type = setting.control_template;
            if (setting.control_template === 'time') control.step = '60';
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
            rerenderAfterChange();
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
        grid.style.cssText = 'display:flex;flex-direction:column;gap:0;';

        function renderChips() {
            chips.innerHTML = '';
            (manifest.settings || []).forEach(function(setting) {
                if (!setting.chip_template) return;
                if (!settingVisible(setting, mount)) return;
                if (mount === GROUP) {
                    var node = activeNode();
                    if (!node || !Object.prototype.hasOwnProperty.call(node.value, setting.key)) return;
                }
                chips.appendChild(chip(chipText(setting, effectiveValue(setting, mount)), false));
            });
            chips.style.display = chips.childNodes.length ? 'flex' : 'none';
        }

        (manifest.settings || []).forEach(function(setting) {
            if (!settingVisible(setting, mount)) return;
            var row = document.createElement('label');
            row.className = 'gt-backtest-setting-row';
            var title = document.createElement('span');
            title.textContent = setting.label;
            title.className = 'gt-backtest-setting-label';
            var controlWrap = document.createElement('span');
            controlWrap.className = 'gt-backtest-setting-control';
            controlWrap.appendChild(makeControl(setting, mount, function() {
                renderManifest(manifest, mount, container);
            }));
            row.appendChild(title);
            row.appendChild(controlWrap);
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
        if (!enabled && index >= 0) {
            tabs.splice(index, 1);
            clearTabOverrides(mount, tabKey);
        }
        if (mount === LOCAL) renderLocalTabs();
        if (mount === GROUP && GT.tabs && GT.tabs.refreshTabBar) GT.tabs.refreshTabBar();
    }

    function renderChooser(mount, container) {
        container.innerHTML = '';
        var intro = document.createElement('div');
        intro.className = 'gt-backtest-settings-chooser-intro';
        intro.textContent = '选择要挂载到此栏的回测设置。未挂载项继续使用下列默认值。';
        container.appendChild(intro);
        availableTabs(mount).forEach(function(tab) {
            var row = document.createElement('label');
            row.className = 'gt-backtest-settings-chooser-row';
            var checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.checked = isMounted(mount, tab.key);
            checkbox.addEventListener('change', function() { toggleMounted(mount, tab.key, checkbox.checked); });
            var body = document.createElement('div');
            body.className = 'gt-backtest-settings-chooser-body';
            var title = document.createElement('div');
            title.textContent = tab.label;
            title.className = 'gt-backtest-settings-chooser-title';
            body.appendChild(title);
            var defaults = document.createElement('div');
            defaults.className = 'gt-backtest-settings-chooser-defaults';
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

    function localChipRow() { return document.getElementById('gt-local-settings-chip-row'); }

    function renderLocalSettingChips() {
        var row = document.getElementById('gt-local-settings-chip-row');
        if (!row) return;
        row.innerHTML = '';
        if (!state.index) {
            row.style.display = 'none';
            return;
        }
        var missing = [];
        (state.mountedTabs[LOCAL] || []).forEach(function(tabKey) {
            var manifest = state.tabCache[tabKey];
            if (!manifest) {
                missing.push(tabKey);
                return;
            }
            (manifest.settings || []).forEach(function(setting) {
                if (!setting.chip_template) return;
                var value = effectiveValue(setting, LOCAL);
                if (value === undefined || value === null || value === '') return;
                var chipNode = chip(chipText(setting, value), false);
                chipNode.setAttribute('data-backtest-local-chip', setting.key);
                chipNode.title = '打开' + ((manifest.tab && manifest.tab.label) || setting.tab_key || tabKey);
                chipNode.style.cursor = 'pointer';
                chipNode.addEventListener('click', function() { openLocal(tabKey); });
                row.appendChild(chipNode);
            });
        });
        row.style.display = row.childNodes.length ? 'flex' : 'none';
        missing.forEach(function(tabKey) {
            loadTab(tabKey).then(function() {
                renderLocalSettingChips();
            }).catch(function(error) {
                console.error('[backend-settings] local chip load failed:', tabKey, error);
            });
        });
    }

    function deactivateLocal() {
        var host = localHost();
        if (host) host.style.display = 'none';
        state.activeLocalTab = null;
        document.querySelectorAll('[data-backtest-local-tab]').forEach(function(button) {
            button.classList.remove('active');
        });
    }

    function openLocal(tabKey) {
        var host = localHost();
        if (state.activeLocalTab === tabKey && host && host.style.display !== 'none') {
            deactivateLocal();
            return;
        }
        document.querySelectorAll('[data-local-settings-tab-panel]').forEach(function(panel) { panel.style.display = 'none'; });
        document.querySelectorAll('[data-local-settings-tab-btn]').forEach(function(button) { button.classList.remove('active'); });
        host.style.display = '';
        state.activeLocalTab = tabKey;
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
        renderLocalSettingChips();
    }

    function currentSelectionFirstId() {
        var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
        return sel && sel.getFirst ? sel.getFirst() : null;
    }

    function setActiveGroupFromUI() {
        state.activeGroup = currentSelectionFirstId();
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
        if (state.index) registerBackendFields(state.index);
        if (!state.groupTabsAttached && state.index && GT.tabs) {
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
    }

    function backendSettingChips(group) {
        if (!group) return [];
        var defaults = state.index && state.index.defaults || {};
        var values = effectiveValuesForNode(group);
        return Object.keys(defaults).filter(function(key) {
            return Object.prototype.hasOwnProperty.call(group, key);
        }).map(function(key) {
            var value = group[key];
            if (value === undefined || value === null || value === '') return null;
            var setting = state.settingDefs[key] || Object.assign({ key: key }, defaults[key] || {});
            var scope = setting.scope_policy || (defaults[key] && defaults[key].scope_policy);
            if (scope !== 'group_override' && scope !== 'group_only') return null;
            if (!settingVisibleForValues(setting, values)) return null;
            if (settingIsShownInMountedTab(GROUP, key)) return null;
            if (defaults[key] && valuesEqual(value, defaults[key].value)) return null;
            if (!setting.chip_template) return null;
            return {
                label: 'backtest-' + key,
                html: renderChipHtml(chipText(setting, value)),
                category: 'config',
                style: null,
            };
        }).filter(Boolean);
    }

    function manifestChips(group, categories) {
        if (!group || !state.index) return [];
        var filter = null;
        if (categories) {
            filter = {};
            (Array.isArray(categories) ? categories : [categories]).forEach(function(category) { filter[category] = true; });
        }
        var chips = [];
        (state.index.chip_fields || []).forEach(function(def) {
            if (filter && !filter[def.category]) return;
            var source = chipSourceGroup(group, def);
            if (!source) return;
            var missing = (def.source_keys || []).some(function(key) {
                return source[key] === undefined || source[key] === null || source[key] === '';
            });
            if (missing) return;
            if (def.key === 'product_mask') {
                var ownMask = group.productMask || {};
                if (!group.parentId || Object.keys(ownMask).length === 0) return;
                var products = nodeProducts(group);
                if (!products.length) return;
                var parent = GT.groupSettings && GT.groupSettings.groups ? GT.groupSettings.groups.get(group.parentId) : null;
                if (parent && sameProductNames(nodeProducts(parent), products)) return;
            }
            chips.push({
                label: def.key,
                html: renderChipHtml(renderChipTemplate(def.chip_template, group, source, def.value_resolvers || {})),
                category: def.category,
                clickable: !!def.clickable,
                action: def.key === 'tester' ? 'tester-products' : (def.key === 'product_mask' ? 'toggle-product-mask' : ''),
                style: null,
            });
        });
        return chips;
    }

    function getAllChips(group, categories) {
        var chips = manifestChips(group, categories);
        if (!categories || categories === 'config' || (Array.isArray(categories) && categories.indexOf('config') >= 0)) {
            chips = chips.concat(backendSettingChips(group));
        }
        return chips;
    }

    function getOverrideChips(group) {
        if (!group || !group.parentId || !GT.groupSettings || !GT.groupSettings.groups) return [];
        var parent = GT.groupSettings.groups.get(group.parentId);
        var base = {};
        getAllChips(parent, ['config', 'derived']).forEach(function(chip) { base[chip.label] = chip.html; });
        return getAllChips(group, ['config', 'derived']).filter(function(chip) {
            return base[chip.label] !== chip.html;
        });
    }

    function toggleProductMask(groupId) {
        state.expandedProductMasks[groupId] = !state.expandedProductMasks[groupId];
        return !!state.expandedProductMasks[groupId];
    }

    function isProductMaskExpanded(groupId) {
        return !!state.expandedProductMasks[groupId];
    }

    function init() {
        var root = localHost();
        if (root) state.application = root.getAttribute('data-application') || state.application;
        var pageUuid = encodeURIComponent(window._pageUuid || '');
        return requestJSON('/api/backtest/settings/' + encodeURIComponent(state.application) + '?page_uuid=' + pageUuid).then(function(index) {
            state.index = index;
            registerBackendFields(index);
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

    function registerBackendFields(index) {
        var api = GT.groupSettings;
        if (!api || typeof api.registerField !== 'function') return;
        Object.keys(index.defaults || {}).forEach(function(key) {
            var item = index.defaults[key] || {};
            var type = 'any';
            if (typeof item.value === 'number') type = 'number';
            else if (typeof item.value === 'boolean') type = 'boolean';
            else if (typeof item.value === 'string') type = 'string';
            api.registerField({
                key: key,
                type: type,
                default: item.value,
            });
        });
        (index.chip_fields || []).forEach(function(chipDef) {
            (chipDef.source_keys || []).forEach(function(key) {
                if (!key) return;
                api.registerField({
                    key: key,
                    type: key === 'productMask' ? 'object' : 'any',
                    default: key === 'productMask' ? null : '',
                });
            });
        });
    }

    function apply(snapshot) {
        snapshot = snapshot || {};
        var snapshotValues = Object.assign({}, snapshot || {});
        state.localValues = snapshotValues;
        mountTabsForSnapshotValues(LOCAL, snapshotValues);
        renderLocalTabs();
        if (GT.tabs && GT.tabs.refreshTabBar) GT.tabs.refreshTabBar();
    }

    function syncAppliedTimeRange() {
        var values = effectiveLocalValues();
        if (!values.start_date || !values.end_date) return Promise.resolve(null);
        var timePayload = {
            factor_family_alias: window.factorFamilyAlias || window._sftCurrentFactorId || '',
            page_uuid: window._pageUuid || '',
            start_date: values.start_date || '',
            start_time: values.start_time || '09:00',
            end_date: values.end_date || '',
            end_time: values.end_time || '15:00',
            timezone: values.timezone || 'Asia/Shanghai',
            time_precision: values.time_precision || 'exact',
            is_trading_day: false,
            is_cn_futures_day: false,
            is_cn_futures_night: false,
        };
        if (typeof window.applySharedRuntimeTimeRange === 'function') {
            window.applySharedRuntimeTimeRange(timePayload);
        }
        return fetch('/set_time_range', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(timePayload),
        }).then(function(response) {
            return response.json().catch(function() { return {}; });
        }).then(function(data) {
            if (data.page_uuid) {
                if (typeof window.rememberSingleFactorPageUuid === 'function') {
                    window.rememberSingleFactorPageUuid(data.page_uuid);
                } else {
                    window._pageUuid = data.page_uuid;
                }
            }
            document.dispatchEvent(new CustomEvent('pageTimeRangeChanged', {
                detail: {
                    start_date: values.start_date,
                    start_time: values.start_time,
                    end_date: values.end_date,
                    end_time: values.end_time,
                },
            }));
            return data;
        });
    }

    function applyFlatSnapshot(snapshot) {
        var groupSettings = snapshot && snapshot.group_settings ? snapshot.group_settings : snapshot;
        var groups = groupSettings && Array.isArray(groupSettings.groups) ? groupSettings.groups : [];
        var localSource = snapshot && snapshot.local_settings ? snapshot.local_settings : {};
        var local = {};
        Object.keys(state.index && state.index.defaults || {}).forEach(function(key) {
            var def = state.index.defaults[key];
            if (!def || def.scope_policy === 'group_only') return;
            if (Object.prototype.hasOwnProperty.call(localSource, key)) local[key] = localSource[key];
        });
        state.localValues = local;
        mountTabsForSnapshotValues(LOCAL, local);
        groups.concat(groupSettings && Array.isArray(groupSettings.lsConfigs) ? groupSettings.lsConfigs : []).forEach(function(item) {
            mountTabsForSnapshotValues(GROUP, item || {});
        });
        renderLocalTabs();
        if (GT.tabs && GT.tabs.refreshTabBar) GT.tabs.refreshTabBar();
        return syncAppliedTimeRange();
    }

    function flattenGroupForSnapshot(group) {
        var source = group || {};
        var out = {};
        var defaults = state.index && state.index.defaults || {};
        var values = effectiveValuesForNode(source);
        Object.keys(defaults).forEach(function(key) {
            var def = defaults[key];
            if (!def || !Object.prototype.hasOwnProperty.call(source, key)) return;
            if (def.scope_policy === 'local_only') return;
            if (!settingVisibleForValues(def, values)) return;
            if (source[key] === '' || source[key] === null || source[key] === undefined) return;
            if (valuesEqual(source[key], def.value)) return;
            out[key] = source[key];
        });
        return out;
    }

    function stripRegisteredSettings(group) {
        var out = Object.assign({}, group || {});
        var defaults = state.index && state.index.defaults || {};
        Object.keys(defaults).forEach(function(key) {
            delete out[key];
        });
        return out;
    }

    function groupPayloadForRun(group) {
        return Object.assign(stripRegisteredSettings(group), flattenGroupForSnapshot(group));
    }

    function collectLocalSettings() {
        var out = {};
        var defaults = state.index && state.index.defaults || {};
        var values = effectiveLocalValues();
        Object.keys(state.localValues || {}).forEach(function(key) {
            var def = defaults[key];
            if (!def || def.scope_policy === 'group_only') return;
            if (!settingVisibleForValues(def, values)) return;
            if (state.localValues[key] === '' || state.localValues[key] === null || state.localValues[key] === undefined) return;
            if (valuesEqual(state.localValues[key], def.value)) return;
            out[key] = state.localValues[key];
        });
        return out;
    }

    function registerSnapshot() {
        state.snapshotRegistered = true;
    }

    function collect() { return collectLocalSettings(); }

    function runPayload() {
        var values = effectiveLocalValues();
        var calendar = String(values.calendar_frequency || 'auto');
        return {
            start_date: values.start_date,
            end_date: values.end_date,
            start_time: values.start_time,
            end_time: values.end_time,
            precision: values.time_precision || 'exact',
            timezone: values.timezone || 'Asia/Shanghai',
            initial_capital: values.initial_capital,
            base_currency: values.base_currency || 'CNY',
            currency_conversion_fee_rate: values.currency_conversion_fee_rate || 0,
            auto_group_calendar_freq: calendar === 'auto',
            group_calendar_freq: calendar === 'auto' ? null : calendar,
        };
    }

    function groupOverrideValues(groupId) {
        var groups = GT.groupSettings && GT.groupSettings.groups;
        var group = groups && groups.get ? groups.get(groupId) : null;
        return group ? Object.assign({}, group) : null;
    }

    function syncPageTimeDefaults() {
        var pageUuid = encodeURIComponent(window._pageUuid || '');
        return requestJSON('/api/backtest/settings/' + encodeURIComponent(state.application) + '?page_uuid=' + pageUuid).then(function(index) {
            state.index = index;
            renderLocalTabs();
            return index;
        });
    }

    document.addEventListener('pageTimeRangeChanged', function() {
        syncPageTimeDefaults().catch(function(error) {
            console.error('[backend-settings] sync page time failed:', error);
        });
    });

    GT.backendSettings = {
        init: init,
        attachGroupTabs: attachGroupTabs,
        deactivateLocal: deactivateLocal,
        applyFlatSnapshot: applyFlatSnapshot,
        flattenGroupForSnapshot: flattenGroupForSnapshot,
        groupPayloadForRun: groupPayloadForRun,
        collectLocalSettings: collectLocalSettings,
        registerSnapshot: registerSnapshot,
        runPayload: runPayload,
        groupOverrideValues: groupOverrideValues,
        syncPageTimeDefaults: syncPageTimeDefaults,
        getAllChips: getAllChips,
        getOverrideChips: getOverrideChips,
        renderChipHtml: renderChipHtml,
        toggleProductMask: toggleProductMask,
        isProductMaskExpanded: isProductMaskExpanded,
        _state: state,
    };
})();
