/** User-mounted, backend-registered, per-tab lazy backtest settings. */
(function() {
    var GT = window.GroupTest;
    if (!GT) { console.warn('[GT backend-settings] bootstrap missing'); return; }

    var LOCAL = 'local-settings';
    var GROUP = 'group-settings';
    var RUN_WINDOW_KEYS = ['start_date', 'end_date', 'start_time', 'end_time', 'timezone', 'time_precision'];
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
        localDefaultProviders: Object.create(null),
        productPathSelections: [],
        productPathSelectionsLoaded: false,
        productPathTree: null,
        productPathTreeSelected: [],
        productPathDraftPaths: [],
        productPathTreeSizer: null,
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
        if (value === undefined || value === null || value === '') return '无';
        if (setting && setting.key === 'product_path_selection' && typeof value === 'object') {
            return productPathSelectionLabel(value) || selectionId(value) || '无';
        }
        if (setting && Array.isArray(setting.options)) {
            for (var i = 0; i < setting.options.length; i++) {
                if (String(setting.options[i].value) === String(value)) return setting.options[i].label;
            }
        }
        return String(value);
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

    function selectionId(selection) {
        return selection ? String(selection.product_path_selection_id || selection.selection_id || selection.id || '') : '';
    }

    function productPathSelectionProducts(selection) {
        var raw = selection && ((Array.isArray(selection.products) && selection.products.length)
            ? selection.products
            : (selection.product_groups || []));
        return (raw || []).map(function(item) {
            if (typeof item === 'string') return { name: item, desc: '' };
            return item && item.name ? { name: item.name, desc: item.desc || '' } : null;
        }).filter(Boolean);
    }

    function productPathSelectionLabel(selection) {
        if (!selection) return '';
        var label = selection.product_group || selection.label || selection.name || selectionId(selection);
        if (selection.product_group_template_id || selection.product_group || selection.product_group_name) return label + ' · 产品组';
        if (selection.path_id) return label + ' · 路径组';
        return label;
    }

    function productGroupToSelection(group) {
        group = group || {};
        var id = String(group.id || group.product_group_template_id || group.name || '');
        var products = (group.product_names || group.products || []).map(function(item) {
            return typeof item === 'string' ? { name: item, desc: '' } : item;
        }).filter(Boolean);
        return {
            id: id,
            product_path_selection_id: id,
            product_group_template_id: id,
            path_id: id,
            product_group: group.name || group.product_group || id,
            label: group.name || group.product_group || id,
            selected_paths: (group.paths || group.selected_paths || []).slice(),
            paths: (group.paths || group.selected_paths || []).slice(),
            products: products,
            product_groups: products,
        };
    }

    function loadProductPathSelections(force) {
        if (state.productPathSelectionsLoaded && !force) {
            return Promise.resolve(state.productPathSelections);
        }
        return requestJSON('/api/product-groups').then(function(payload) {
            state.productPathSelections = (payload.groups || []).map(productGroupToSelection);
            state.productPathSelectionsLoaded = true;
            document.dispatchEvent(new CustomEvent('groupTestProductPathSelectionsChanged'));
            return state.productPathSelections;
        });
    }

    function setDefaultProductPathSelection(selection) {
        if (selection) state.localValues.product_path_selection = selection;
        else delete state.localValues.product_path_selection;
        renderLocalSettingChips();
        document.dispatchEvent(new CustomEvent('groupTestProductPathSelectionsChanged'));
    }

    function positivePaths(paths) {
        return (paths || []).filter(function(path) { return String(path || '').charAt(0) !== '-'; });
    }

    function exclusionsCoveredBy(paths, positive) {
        return (paths || []).filter(function(path) {
            path = String(path || '');
            if (path.charAt(0) !== '-') return false;
            var leafPath = path.substring(1);
            return (positive || []).some(function(includedPath) {
                return leafPath === includedPath || leafPath.indexOf(includedPath + '/') === 0;
            });
        });
    }

    function negativeProductPath(parentPath, productName) {
        var basePath = String(parentPath || '').slice(-10) === '/_products'
            ? String(parentPath || '')
            : String(parentPath || '') + '/_products';
        return '-' + basePath + '/' + productName;
    }

    function addProductPathDraftPaths(paths, negative) {
        var next = state.productPathDraftPaths.slice();
        (paths || []).forEach(function(path) {
            path = String(path || '').trim();
            if (!path) return;
            if (negative && path.charAt(0) !== '-') path = '-' + path;
            if (!negative && path.charAt(0) === '-') path = path.substring(1);
            if (next.indexOf(path) < 0) next.push(path);
        });
        state.productPathDraftPaths = next;
    }

    function removeProductPathDraftPath(path) {
        state.productPathDraftPaths = state.productPathDraftPaths.filter(function(item) { return item !== path; });
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
            inherited = productPathSelectionProducts(group.product_path_selection);
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
        if (resolver === 'product_path_selection_label') return productPathSelectionLabel(source && source.product_path_selection);
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
            var def = defaults[key];
            if (def.tab_key === tabKey && settingVisibleForValues(def, values)) {
                out.push({
                    key: key,
                    label: def.label || key,
                    value: displayValue(def, def.value),
                });
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
        var meta = setting && setting.key && state.index && state.index.defaults
            ? state.index.defaults[setting.key]
            : null;
        var visibleWhen = (setting && setting.visible_when) || (meta && meta.visible_when);
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
        } else if (setting.control_template === 'date') {
            control = document.createElement('input');
            control.type = 'date';
        } else if (setting.control_template === 'number' || setting.control_template === 'time') {
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
            if (setting.control_template === 'date' && !/^\d{4}-\d{2}-\d{2}$/.test(control.value || '')) {
                return;
            }
            var nextValue = setting.control_template === 'number'
                ? Number(control.value)
                : normalizeControlValue(setting, control.value);
            control.value = nextValue;
            writeValue(setting, mount, nextValue);
            rerenderAfterChange();
        });
        return control;
    }

    function mountProductPathTree(container) {
        var treeEl = container.querySelector('#gt-pps-tree');
        if (!treeEl || !window.ProductSelector || !window.jQuery) return;
        treeEl.style.fontSize = '11px';
        treeEl.style.lineHeight = '1.35';
        window.ProductSelector.createTree(window.jQuery(treeEl), {
            onInit: function(tree) {
                state.productPathTree = tree;
            },
            onSelect: function(paths) {
                state.productPathTreeSelected = paths || [];
            },
        });
        if (typeof window.setupResizableTreeContainer === 'function') {
            if (state.productPathTreeSizer && typeof state.productPathTreeSizer.destroy === 'function') {
                state.productPathTreeSizer.destroy();
            }
            state.productPathTreeSizer = window.setupResizableTreeContainer({
                outerElement: container.querySelector('#gt-pps-tree-panel'),
                innerElement: treeEl,
                minWidth: 240,
                initialWidth: 320,
                minHeight: 180,
                initialHeight: 300,
                maxWidth: 'min(52vw, 620px)',
                maxWidthFallback: 620,
                resizeDirection: 'both',
                desktopMediaQuery: '(max-width: 960px)',
                mobileInnerMaxHeight: '360px',
            });
        } else {
            treeEl.style.boxSizing = 'border-box';
            treeEl.style.minWidth = '240px';
            treeEl.style.minHeight = '180px';
            treeEl.style.maxWidth = 'min(52vw, 620px)';
            treeEl.style.resize = 'both';
            treeEl.style.overflow = 'auto';
        }
    }

    function renderProductPathDraft(container) {
        var target = container.querySelector('#gt-pps-draft-paths');
        if (!target) return;
        var paths = state.productPathDraftPaths || [];
        if (!paths.length) {
            target.innerHTML = '<div style="padding:12px;color:#888;font-size:12px;line-height:1.6;">从左侧产品树勾选路径后，点击“正新增”或“负新增”。正新增路径下的单个产品也可以在展开后做负新增。</div>';
            return;
        }
        var html = '';
        html += '<div style="padding:7px 9px;border-bottom:1px solid #eef2f7;font-size:12px;font-weight:700;color:#475467;">当前路径规则 <span style="font-weight:500;color:#94a3b8;">' + paths.length + '</span></div>';
        paths.forEach(function(path) {
            var negative = String(path).charAt(0) === '-';
            var clean = negative ? String(path).substring(1) : String(path);
            html += '<div style="border-bottom:1px solid #f1f5f9;">';
            html += '<div style="display:grid;grid-template-columns:22px minmax(0,1fr) auto auto;gap:6px;align-items:start;padding:6px 8px;">';
            html += '<span style="display:inline-flex;align-items:center;justify-content:center;width:19px;height:18px;border-radius:4px;background:' + (negative ? '#fef2f2' : '#ecfdf3') + ';color:' + (negative ? '#b42318' : '#166534') + ';font-weight:700;font-size:12px;">' + (negative ? '-' : '+') + '</span>';
            html += '<span style="font-family:monospace;font-size:11px;color:#334155;word-break:break-all;line-height:1.35;">' + escapeHTML(clean) + '</span>';
            if (negative) {
                html += '<span></span>';
            } else {
                html += '<button type="button" data-gt-pps-show-products="' + escapeHTML(clean) + '" style="height:22px;padding:0 7px;border:1px solid #dbeafe;border-radius:4px;background:#eff6ff;color:#1d4ed8;font-size:11px;cursor:pointer;">产品</button>';
            }
            html += '<button type="button" data-gt-pps-remove-path="' + escapeHTML(path) + '" style="height:22px;padding:0 7px;border:1px solid #fecaca;border-radius:4px;background:#fff5f5;color:#b91c1c;font-size:11px;cursor:pointer;">移除</button>';
            html += '</div>';
            html += '<div data-gt-pps-products-for="' + escapeHTML(clean) + '" style="display:none;padding:0 8px 7px 36px;"></div>';
            html += '</div>';
        });
        target.innerHTML = html;
        target.querySelectorAll('[data-gt-pps-remove-path]').forEach(function(button) {
            button.addEventListener('click', function() {
                removeProductPathDraftPath(this.getAttribute('data-gt-pps-remove-path'));
                renderProductPathDraft(container);
            });
        });
        target.querySelectorAll('[data-gt-pps-show-products]').forEach(function(button) {
            button.addEventListener('click', function() {
                var path = this.getAttribute('data-gt-pps-show-products');
                renderPathProductsForExclusion(container, path);
            });
        });
    }

    function renderPathProductsForExclusion(container, path) {
        var slot = null;
        container.querySelectorAll('[data-gt-pps-products-for]').forEach(function(node) {
            if (node.getAttribute('data-gt-pps-products-for') === path) slot = node;
        });
        if (!slot) return;
        if (slot.style.display !== 'none' && slot.innerHTML) {
            slot.style.display = 'none';
            return;
        }
        slot.style.display = '';
        slot.innerHTML = '<div style="font-size:11px;color:#888;padding:5px 0;">加载产品...</div>';
        fetch('/get_products?path=' + encodeURIComponent(path), { headers: { Accept: 'application/json' } })
            .then(function(response) { return response.json().catch(function() { return []; }); })
            .then(function(products) {
                var html = '';
                (products || []).forEach(function(product) {
                    var name = product.product_name || product.title || product.name || '';
                    if (!name) return;
                    var exclusion = negativeProductPath(path, name);
                    var excluded = state.productPathDraftPaths.indexOf(exclusion) >= 0;
                    html += '<div style="display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px;align-items:center;padding:4px 0;border-top:1px solid #f1f5f9;">';
                    html += '<span style="min-width:0;font-size:11px;color:#475467;"><b style="font-family:monospace;color:#334155;">' + escapeHTML(name) + '</b>' + (product.desc ? ' <span style="color:#94a3b8;">' + escapeHTML(product.desc) + '</span>' : '') + '</span>';
                    html += '<button type="button" data-gt-pps-exclude-product="' + escapeHTML(exclusion) + '" style="height:22px;padding:0 7px;border:1px solid ' + (excluded ? '#bfdbfe' : '#fecaca') + ';border-radius:4px;background:' + (excluded ? '#eff6ff' : '#fef2f2') + ';color:' + (excluded ? '#1d4ed8' : '#b42318') + ';font-size:11px;cursor:pointer;">' + (excluded ? '已排除' : '负新增') + '</button>';
                    html += '</div>';
                });
                slot.innerHTML = html || '<div style="font-size:11px;color:#888;padding:5px 0;">无产品</div>';
                slot.querySelectorAll('[data-gt-pps-exclude-product]').forEach(function(button) {
                    button.addEventListener('click', function() {
                        addProductPathDraftPaths([this.getAttribute('data-gt-pps-exclude-product')], true);
                        renderProductPathDraft(container);
                        renderPathProductsForExclusion(container, path);
                    });
                });
            }).catch(function() {
                slot.innerHTML = '<div style="font-size:11px;color:#d92d20;padding:5px 0;">产品加载失败</div>';
            });
    }

    function renderProductPathSelectionManager(container) {
        container.innerHTML = '<div style="color:#64748b;font-size:12px;">正在加载产品路径...</div>';
        loadProductPathSelections().then(function(selections) {
            var currentId = selectionId(state.localValues.product_path_selection);
            var html = '';
            html += '<div style="display:flex;flex-direction:column;gap:12px;">';
            html += '<div style="border:1px solid #e5e7eb;border-radius:8px;background:#fff;overflow:hidden;">';
            html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 10px;border-bottom:1px solid #eef2f7;">';
            html += '<span style="font-size:12px;font-weight:700;color:#334155;">已加载产品路径组</span>';
            html += '<span style="font-size:11px;color:#94a3b8;">' + selections.length + '</span>';
            html += '</div>';
            html += '<div style="max-height:170px;overflow:auto;">';
            if (!selections.length) {
                html += '<div style="padding:14px;color:#888;font-size:12px;">暂无产品路径组，请在下方新增。</div>';
            }
            selections.forEach(function(selection) {
                var id = selectionId(selection);
                var active = id && id === currentId;
                var label = productPathSelectionLabel(selection);
                var pathCount = (selection.paths || selection.selected_paths || []).length;
                var productCount = productPathSelectionProducts(selection).length;
                html += '<div style="display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:6px;align-items:center;padding:7px 8px;border-bottom:1px solid #f1f5f9;background:' + (active ? '#eff6ff' : '#fff') + ';">';
                html += '<button type="button" data-gt-pps-open="' + escapeHTML(id) + '" style="min-width:0;text-align:left;border:none;background:transparent;padding:0;cursor:pointer;">';
                html += '<div style="font-size:12px;font-weight:600;color:#1f2937;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escapeHTML(label) + '</div>';
                html += '<div style="font-size:11px;color:#64748b;margin-top:1px;">' + pathCount + ' 路径 · ' + productCount + ' 产品' + (active ? ' · 默认' : '') + '</div>';
                html += '</button>';
                html += '<button type="button" data-gt-pps-default="' + escapeHTML(id) + '" class="gt-backend-chip" style="border:1px solid #cbd5e1;background:#fff;cursor:pointer;">' + renderChipHtml(active ? '默认' : '设为默认') + '</button>';
                html += '<button type="button" data-gt-pps-delete="' + escapeHTML(id) + '" style="height:24px;padding:0 7px;border:1px solid #fecaca;border-radius:4px;background:#fff5f5;color:#b91c1c;font-size:11px;cursor:pointer;">删除</button>';
                html += '</div>';
            });
            html += '</div></div>';
            html += '<div style="border:1px solid #e5e7eb;border-radius:8px;background:#fff;padding:10px;min-width:0;">';
            html += '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;">';
            html += '<span style="font-size:12px;font-weight:700;color:#334155;">现场新增路径组</span>';
            html += '<span id="gt-pps-status" style="font-size:12px;color:#64748b;"></span>';
            html += '</div>';
            html += '<input id="gt-pps-new-name" type="text" placeholder="路径组名称" style="width:100%;box-sizing:border-box;height:30px;margin-bottom:8px;padding:4px 8px;border:1px solid #d0d5dd;border-radius:4px;font-size:12px;">';
            html += '<div style="display:grid;grid-template-columns:auto minmax(280px,1fr);gap:10px;align-items:start;min-width:0;">';
            html += '<div id="gt-pps-tree-panel" style="min-width:0;">';
            html += '<div style="display:flex;gap:6px;margin-bottom:6px;">';
            html += '<button type="button" id="gt-pps-add-positive" style="height:26px;padding:0 9px;border:1px solid #bbf7d0;border-radius:4px;background:#f0fdf4;color:#166534;font-size:12px;cursor:pointer;">+ 正新增</button>';
            html += '<button type="button" id="gt-pps-add-negative" style="height:26px;padding:0 9px;border:1px solid #fecaca;border-radius:4px;background:#fef2f2;color:#b42318;font-size:12px;cursor:pointer;">- 负新增</button>';
            html += '</div>';
            html += '<div id="gt-pps-tree" class="product-tree-scrollbox" style="width:320px;height:300px;overflow:auto;border:1px solid #e1e4e8;border-radius:6px;padding:6px;background:#fff;font-size:11px;line-height:1.35;"></div>';
            html += '</div>';
            html += '<div style="min-width:0;">';
            html += '<div id="gt-pps-draft-paths" style="height:300px;overflow:auto;border:1px solid #e5e7eb;border-radius:6px;background:#fff;"></div>';
            html += '<div style="display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-top:8px;">';
            html += '<button type="button" id="gt-pps-clear-draft" style="height:28px;padding:0 10px;border:1px solid #cbd5e1;border-radius:4px;background:#fff;color:#475569;font-size:12px;cursor:pointer;">清空</button>';
            html += '<button type="button" id="gt-pps-create" style="height:28px;padding:0 12px;border:1px solid #bfdbfe;border-radius:4px;background:#eff6ff;color:#1d4ed8;font-size:12px;cursor:pointer;">新增</button>';
            html += '<button type="button" id="gt-pps-create-default" style="height:28px;padding:0 12px;border:none;border-radius:4px;background:#2563eb;color:#fff;font-size:12px;cursor:pointer;">新增并设为默认</button>';
            html += '</div>';
            html += '</div></div></div></div>';
            container.innerHTML = html;

            container.querySelectorAll('[data-gt-pps-open]').forEach(function(button) {
                button.addEventListener('click', function() {
                    var id = this.getAttribute('data-gt-pps-open');
                    var selected = state.productPathSelections.filter(function(item) { return selectionId(item) === id; })[0] || null;
                    if (!selected || !GT.overlays || !GT.overlays.productPathSelectionProducts) return;
                    GT.overlays.productPathSelectionProducts.open(
                        productPathSelectionLabel(selected),
                        productPathSelectionProducts(selected),
                        selected
                    );
                });
            });
            container.querySelectorAll('[data-gt-pps-default]').forEach(function(button) {
                button.addEventListener('click', function() {
                    var id = this.getAttribute('data-gt-pps-default');
                    var selected = state.productPathSelections.filter(function(item) { return selectionId(item) === id; })[0] || null;
                    setDefaultProductPathSelection(selected);
                    renderProductPathSelectionManager(container);
                });
            });
            container.querySelectorAll('[data-gt-pps-delete]').forEach(function(button) {
                button.addEventListener('click', function() {
                    var id = this.getAttribute('data-gt-pps-delete');
                    var selected = state.productPathSelections.filter(function(item) { return selectionId(item) === id; })[0] || null;
                    var name = selected && productPathSelectionLabel(selected);
                    if (!name || !confirm('删除产品路径组 "' + name + '"？')) return;
                    fetch('/api/product-groups/' + encodeURIComponent(name), { method: 'DELETE' })
                        .then(function(response) { return response.json().catch(function() { return {}; }); })
                        .then(function(payload) {
                            if (payload.success === false) throw new Error(payload.error || '删除失败');
                            if (selectionId(state.localValues.product_path_selection) === id) setDefaultProductPathSelection(null);
                            return loadProductPathSelections(true);
                        })
                        .then(function() { renderProductPathSelectionManager(container); })
                        .catch(function(error) { alert(error.message || error); });
                });
            });
            var createBtn = document.getElementById('gt-pps-create');
            var createDefaultBtn = document.getElementById('gt-pps-create-default');
            renderProductPathDraft(container);
            mountProductPathTree(container);
            var addPositiveBtn = document.getElementById('gt-pps-add-positive');
            if (addPositiveBtn) {
                addPositiveBtn.addEventListener('click', function() {
                    addProductPathDraftPaths(state.productPathTreeSelected, false);
                    state.productPathDraftPaths = positivePaths(state.productPathDraftPaths)
                        .concat(exclusionsCoveredBy(state.productPathDraftPaths, positivePaths(state.productPathDraftPaths)));
                    renderProductPathDraft(container);
                });
            }
            var addNegativeBtn = document.getElementById('gt-pps-add-negative');
            if (addNegativeBtn) {
                addNegativeBtn.addEventListener('click', function() {
                    addProductPathDraftPaths(state.productPathTreeSelected, true);
                    renderProductPathDraft(container);
                });
            }
            var clearDraftBtn = document.getElementById('gt-pps-clear-draft');
            if (clearDraftBtn) {
                clearDraftBtn.addEventListener('click', function() {
                    state.productPathDraftPaths = [];
                    renderProductPathDraft(container);
                });
            }
            function createProductPathGroup(setAsDefault) {
                    var nameInput = document.getElementById('gt-pps-new-name');
                    var status = document.getElementById('gt-pps-status');
                    var name = nameInput ? nameInput.value.trim() : '';
                    var paths = state.productPathDraftPaths.slice();
                    if (!name || !paths.length) {
                        if (status) status.textContent = '请填写名称和路径';
                        return;
                    }
                    fetch('/api/product-groups', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                        body: JSON.stringify({ name: name, paths: paths }),
                    }).then(function(response) {
                        return response.json().catch(function() { return {}; }).then(function(payload) {
                            if (!response.ok || payload.success === false) throw new Error(payload.error || '新增失败');
                            return payload;
                        });
                    }).then(function(payload) {
                        var selection = productGroupToSelection(payload.group || {});
                        if (setAsDefault) setDefaultProductPathSelection(selection);
                        return loadProductPathSelections(true);
                    }).then(function() {
                        state.productPathDraftPaths = [];
                        renderProductPathSelectionManager(container);
                    }).catch(function(error) {
                        if (status) status.textContent = error.message || String(error);
                    });
            }
            if (createBtn) {
                createBtn.addEventListener('click', function() { createProductPathGroup(false); });
            }
            if (createDefaultBtn) {
                createDefaultBtn.addEventListener('click', function() { createProductPathGroup(true); });
            }
        }).catch(function(error) {
            container.textContent = '加载失败：' + error.message;
        });
    }

    function parseDateParts(value) {
        var match = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(String(value || '').trim());
        return {
            year: match ? match[1] : '',
            month: match ? padDatePart(match[2], 2) : '',
            day: match ? padDatePart(match[3], 2) : '',
        };
    }

    function sanitizeDigits(value) {
        return String(value || '').replace(/\D/g, '');
    }

    function padDatePart(value, length) {
        var digits = sanitizeDigits(value);
        if (!digits) return '';
        return digits.padStart(length, '0').slice(-length);
    }

    function clampNumber(value, min, max) {
        var number = parseInt(value, 10);
        if (isNaN(number)) return min;
        return Math.max(min, Math.min(max, number));
    }

    function normalizeControlValue(setting, value) {
        if (!setting || setting.control_template !== 'date') return value;
        var text = String(value || '').trim();
        if (/^\d{8}$/.test(text)) {
            text = text.slice(0, 4) + '-' + text.slice(4, 6) + '-' + text.slice(6, 8);
        }
        var match = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/.exec(text);
        if (!match) return text;
        var year = match[1];
        var month = match[2].padStart(2, '0');
        var day = match[3].padStart(2, '0');
        return year + '-' + month + '-' + day;
    }

    function renderManifest(manifest, mount, container) {
        if (mount === LOCAL && manifest.tab && manifest.tab.key === 'product_path_selection') {
            renderProductPathSelectionManager(container);
            return;
        }
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
        if (mount !== LOCAL) {
            renderChips();
            container.appendChild(chips);
        }
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
        if (!window.BackendSettingsPanel) return;
        window.BackendSettingsPanel.toggleMountedTab({
            mountedTabs: state.mountedTabs[mount],
            tabKey: tabKey,
            enabled: enabled,
            clearTabValues: function(key) {
                clearTabOverrides(mount, key);
            },
            afterChange: function() {
                if (mount === LOCAL) renderLocalTabs();
                if (mount === GROUP && GT.tabs && GT.tabs.refreshTabBar) GT.tabs.refreshTabBar();
            },
        });
    }

    function renderChooser(mount, container) {
        container.innerHTML = '';
        var intro = document.createElement('div');
        intro.className = 'backend-settings-chooser-intro gt-backtest-settings-chooser-intro';
        intro.textContent = '选择要挂载到此栏的回测设置。未挂载项继续使用下列默认值。';
        container.appendChild(intro);
        availableTabs(mount).forEach(function(tab) {
            var row = document.createElement('label');
            row.className = 'backend-settings-chooser-row gt-backtest-settings-chooser-row';
            var checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.checked = isMounted(mount, tab.key);
            checkbox.addEventListener('change', function() { toggleMounted(mount, tab.key, checkbox.checked); });
            var body = document.createElement('div');
            body.className = 'backend-settings-chooser-body gt-backtest-settings-chooser-body';
            var title = document.createElement('div');
            title.textContent = tab.label;
            title.className = 'backend-settings-chooser-title gt-backtest-settings-chooser-title';
            body.appendChild(title);
            var defaults = document.createElement('div');
            defaults.className = 'backend-settings-chooser-defaults gt-backtest-settings-chooser-defaults';
            defaultsForTab(tab.key).forEach(function(item) {
                defaults.appendChild(chip(item.label + ': ' + item.value, true));
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
                if (!settingVisible(setting, LOCAL)) return;
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
        if (!window.BackendSettingsPanel || typeof window.BackendSettingsPanel.toggleContent !== 'function') {
            if (state.activeLocalTab === tabKey && host && host.style.display !== 'none') {
                deactivateLocal();
                return;
            }
        }
        var toggleResult = window.BackendSettingsPanel && window.BackendSettingsPanel.toggleContent
            ? window.BackendSettingsPanel.toggleContent({
                key: tabKey,
                host: host,
                getActiveKey: function() { return state.activeLocalTab; },
                setActiveKey: function(value) { state.activeLocalTab = value; },
                buttonSelector: '[data-backtest-local-tab]',
                buttonKeyAttribute: 'data-backtest-local-tab',
                panelSelector: '[data-local-settings-tab-panel]',
                panelKeyAttribute: 'data-local-settings-tab-panel',
                beforeOpen: function() {
                    document.querySelectorAll('[data-local-settings-tab-btn]').forEach(function(button) { button.classList.remove('active'); });
                },
            })
            : { opened: true };
        if (!toggleResult.opened) {
            return;
        }
        if (tabKey === '__manage__') renderChooser(LOCAL, host);
        else activateTab(tabKey, LOCAL, host).catch(function(error) { console.error(error); });
    }

    function openLocalTab(tabKey) {
        if (!tabKey || !tabExists(LOCAL, tabKey)) return false;
        ensureMounted(LOCAL, tabKey);
        renderLocalTabs();
        openLocal(tabKey);
        return true;
    }

    function renderLocalTabs() {
        var bar = document.getElementById('gt-local-settings-tab-bar');
        if (!bar || !state.index) return;
        bar.querySelectorAll('[data-backtest-local-tab]').forEach(function(node) { node.remove(); });
        availableTabs(LOCAL).forEach(function(tab) {
            if (!isMounted(LOCAL, tab.key)) return;
            var button = document.createElement('button');
            button.type = 'button';
            button.className = '';
            button.textContent = tab.label;
            button.setAttribute('data-backtest-local-tab', tab.key);
            button.addEventListener('click', function() { openLocal(tab.key); });
            bar.appendChild(button);
        });
        var manage = document.createElement('button');
        manage.type = 'button';
        manage.className = '';
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

    function settingDef(key) {
        var defaults = state.index && state.index.defaults || {};
        return state.settingDefs[key] || Object.assign({ key: key }, defaults[key] || {});
    }

    function configSettingKeys() {
        var defaults = state.index && state.index.defaults || {};
        return Object.keys(defaults).filter(function(key) {
            var setting = settingDef(key);
            var scope = setting.scope_policy || (defaults[key] && defaults[key].scope_policy);
            return (scope === 'group_override' || scope === 'group_only') && !!setting.chip_template;
        });
    }

    function effectiveSettingValueForGroup(group, key) {
        var source = group && group.value ? group.value : group;
        if (source && Object.prototype.hasOwnProperty.call(source, key)) return source[key];
        if (source && source.parentId && GT.groupSettings && GT.groupSettings.groups && GT.groupSettings.groups.resolveRootField) {
            var inherited = GT.groupSettings.groups.resolveRootField(source, key);
            if (inherited !== undefined && inherited !== null && inherited !== '') return inherited;
        }
        var local = effectiveLocalValues();
        return local[key];
    }

    function configChipForGroupKey(group, key) {
        if (!group) return null;
        var value = effectiveSettingValueForGroup(group, key);
        if (value === undefined || value === null || value === '') return null;
        var setting = settingDef(key);
        var values = effectiveValuesForNode(group);
        values[key] = value;
        if (!settingVisibleForValues(setting, values)) return null;
        if (!setting.chip_template) return null;
        return {
            label: 'backtest-' + key,
            html: renderChipHtml(chipText(setting, value)),
            category: 'config',
            style: null,
        };
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
            var setting = settingDef(key);
            var scope = setting.scope_policy || (defaults[key] && defaults[key].scope_policy);
            if (scope !== 'group_override' && scope !== 'group_only') return null;
            if (!settingVisibleForValues(setting, values)) return null;
            var localValue = effectiveLocalValues()[key];
            var differsFromLocal = !valuesEqual(value, localValue);
            var differsFromDefault = defaults[key] && !valuesEqual(value, defaults[key].value);
            if (!differsFromLocal && !differsFromDefault) return null;
            if (settingIsShownInMountedTab(GROUP, key) && !differsFromLocal && !differsFromDefault) return null;
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
        registerBuiltInDefaultProviders();
        return requestJSON('/api/backtest/settings/' + encodeURIComponent(state.application) + '?page_uuid=' + pageUuid).then(function(index) {
            state.index = index;
            copyLocalDefaultsFromProvider('page_time_range', { blockOnUserKeys: RUN_WINDOW_KEYS });
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

    function registerBuiltInDefaultProviders() {
        if (state.localDefaultProviders.page_time_range) return;
        registerLocalDefaultProvider('page_time_range', function() {
            if (!window.BacktestTimeWindowSettings) return null;
            return window.BacktestTimeWindowSettings.pageRuntimeTimeRangeValues();
        });
    }

    function registerLocalDefaultProvider(name, provider) {
        if (!name || typeof provider !== 'function') return;
        state.localDefaultProviders[name] = provider;
    }

    function copyLocalDefaultsFromProvider(name, options) {
        var provider = state.localDefaultProviders[name];
        if (!provider || !state.index || !state.index.defaults) return false;
        var values = provider();
        if (!values || typeof values !== 'object') return false;
        return applyLocalDefaultValues(values, options);
    }

    function applyLocalDefaultValues(values, options) {
        options = options || {};
        var changed = false;
        var defaults = state.index && state.index.defaults || {};
        var blockOnUserKeys = Array.isArray(options.blockOnUserKeys) ? options.blockOnUserKeys : [];
        if (blockOnUserKeys.some(function(key) {
            return Object.prototype.hasOwnProperty.call(state.localValues, key);
        })) {
            return false;
        }
        Object.keys(values || {}).forEach(function(key) {
            var def = defaults[key];
            if (!def || def.scope_policy === 'group_only') return;
            if (options.skipUserValues !== false && Object.prototype.hasOwnProperty.call(state.localValues, key)) return;
            var value = normalizeControlValue(def, values[key]);
            if (value === undefined || value === null || value === '') return;
            if (valuesEqual(def.value, value)) return;
            def.value = value;
            changed = true;
        });
        if (changed) {
            renderLocalTabs();
            if (GT.tabs && GT.tabs.refreshTabBar) GT.tabs.refreshTabBar();
        }
        return changed;
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
        state.mountedTabs[LOCAL] = [];
        deactivateLocal();
        mountTabsForSnapshotValues(LOCAL, snapshotValues);
        renderLocalTabs();
        if (GT.tabs && GT.tabs.refreshTabBar) GT.tabs.refreshTabBar();
    }

    function syncAppliedTimeRange() {
        var values = effectiveLocalValues();
        if (!values.start_date || !values.end_date) return Promise.resolve(null);
        var precision = values.time_precision || 'exact';
        var tradingDayMode = precision === 'trading_day';
        var timePayload = {
            factor_family_alias: window.factorFamilyAlias || window._sftCurrentFactorId || '',
            page_uuid: window._pageUuid || '',
            start_date: values.start_date || '',
            start_time: tradingDayMode ? '' : (values.start_time || '09:00'),
            end_date: values.end_date || '',
            end_time: tradingDayMode ? '' : (values.end_time || '15:00'),
            timezone: tradingDayMode ? 'UTC' : (values.timezone || 'Asia/Shanghai'),
            time_precision: tradingDayMode ? 'trading_day' : precision,
            is_trading_day: tradingDayMode,
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
        state.mountedTabs[LOCAL] = [];
        state.mountedTabs[GROUP] = [];
        deactivateLocal();
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
        var localValues = effectiveLocalValues();
        Object.keys(defaults).forEach(function(key) {
            var def = defaults[key];
            if (!def || !Object.prototype.hasOwnProperty.call(source, key)) return;
            if (def.scope_policy === 'local_only') return;
            if (!settingVisibleForValues(def, values)) return;
            if (source[key] === '' || source[key] === null || source[key] === undefined) return;
            if (def.scope_policy === 'group_override' && valuesEqual(source[key], localValues[key])) return;
            if (def.scope_policy !== 'group_override' && valuesEqual(source[key], def.value)) return;
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
        var precision = values.time_precision || 'exact';
        var tradingDayMode = precision === 'trading_day';
        return Object.assign({}, collectLocalSettings(), {
            _runtime_window: {
                start_date: values.start_date,
                end_date: values.end_date,
                start_time: tradingDayMode ? '' : values.start_time,
                end_time: tradingDayMode ? '' : values.end_time,
                time_precision: tradingDayMode ? 'trading_day' : precision,
                timezone: tradingDayMode ? '' : (values.timezone || 'Asia/Shanghai'),
            },
            auto_group_calendar_freq: calendar === 'auto',
            group_calendar_freq: calendar === 'auto' ? null : calendar,
        });
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
            copyLocalDefaultsFromProvider('page_time_range', { blockOnUserKeys: RUN_WINDOW_KEYS });
            renderLocalTabs();
            return index;
        });
    }

    document.addEventListener('timeRangeDefaultLoaded', function() {
        copyLocalDefaultsFromProvider('page_time_range', { blockOnUserKeys: RUN_WINDOW_KEYS });
    });

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
        registerLocalDefaultProvider: registerLocalDefaultProvider,
        copyLocalDefaultsFromProvider: copyLocalDefaultsFromProvider,
        applyLocalDefaultValues: applyLocalDefaultValues,
        openLocalTab: openLocalTab,
        loadProductPathSelections: loadProductPathSelections,
        getProductPathSelections: function() { return state.productPathSelections.slice(); },
        getAllChips: getAllChips,
        getOverrideChips: getOverrideChips,
        configSettingKeys: configSettingKeys,
        effectiveSettingValueForGroup: effectiveSettingValueForGroup,
        configChipForGroupKey: configChipForGroupKey,
        renderChipHtml: renderChipHtml,
        toggleProductMask: toggleProductMask,
        isProductMaskExpanded: isProductMaskExpanded,
        _state: state,
    };
})();
