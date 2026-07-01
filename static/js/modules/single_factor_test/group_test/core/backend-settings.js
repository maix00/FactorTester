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
        productPathSelectionResolveRequests: Object.create(null),
        inlineManagers: Object.create(null),
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

    function settingStorageKey(setting) {
        var serialization = setting && setting.serialization || {};
        return serialization.storage_key || setting.key;
    }

    function customProductRowsForSetting(setting, value) {
        var rows = Array.isArray(value) ? value : [];
        var serialization = setting && setting.serialization || {};
        var filter = serialization.module_filter;
        if (!filter || serialization.kind !== 'custom_product_overrides') return rows;
        var modulesByField = {};
        (serialization.fields || []).forEach(function(item) {
            modulesByField[String(item.value)] = String(item.module || '');
        });
        return rows.filter(function(row) {
            return modulesByField[String(row && row.field)] === String(filter);
        });
    }

    function hasVisibleStoredValue(def, source, key) {
        var storageKey = settingStorageKey(Object.assign({ key: key }, def || {}));
        if (!hasUsableValue(source, storageKey)) return false;
        if (storageKey === key) return true;
        return customProductRowsForSetting(def, source[storageKey]).length > 0;
    }

    function settingKeysForTab(tabKey) {
        var defaults = state.index && state.index.defaults || {};
        var keys = Object.keys(defaults).filter(function(key) {
            return defaults[key] && defaults[key].tab_key === tabKey;
        });
        return window.BackendSettingsPanel.sortSettingKeysByDisplayOrder(keys, defaults);
    }

    function orderedMountedTabs(mount) {
        var tabs = state.index && state.index.tab_lists ? (state.index.tab_lists[mount] || []) : [];
        return window.BackendSettingsPanel.sortTabsByOrder(state.mountedTabs[mount] || [], tabs);
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
        return window.BackendSettingsPanel.displaySettingValue(setting, value);
    }

    function escapeHTML(str) {
        if (GT.escapeHTML) return GT.escapeHTML(str == null ? '' : String(str));
        return String(str == null ? '' : str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    // chipText 已删除：chip HTML 统一由 ChipRenderer.chipHtml 渲染（见 gtSettingChipHtml）。

    // chipParts 已删除：chip HTML 统一由 ChipRenderer.chipHtml 渲染。

    function renderChipHtml(labelOrText, value) {
        if (value !== undefined && value !== null && value !== '') {
            return window.ChipRenderer.chipHtml(
                { chip_template: '{label}: {value}' },
                { valueOf: function(k) { return k === 'label' ? String(labelOrText || '') : String(value); },
                  escapeHTML: escapeHTML,
                  renderChipHtml: function(l, v, esc) {
                      return '<span class="gt-backend-chip-label">' + esc(l) + '</span>'
                          + '<span class="gt-backend-chip-value">' + esc(v) + '</span>';
                  },
                }
            );
        }
        return window.ChipRenderer.chipHtml(
            { chip_template: '{label}: {value}' },
            { escapeHTML: escapeHTML,
              resolve: function() { return ''; },
              valueOf: function(k) { return k === 'value' ? String(labelOrText == null ? '' : labelOrText) : ''; },
              renderChipHtml: function(l, v, esc) {
                  if (!l) return '<span class="gt-backend-chip-value">' + esc(v) + '</span>';
                  return '<span class="gt-backend-chip-label">' + esc(l) + '</span>'
                      + '<span class="gt-backend-chip-value">' + esc(v) + '</span>';
              },
            }
        );
    }

    function valuesEqual(left, right) {
        if (left === right) return true;
        if (left === undefined && right === null) return true;
        if (left === null && right === undefined) return true;
        if (typeof left === 'number' || typeof right === 'number') return Number(left) === Number(right);
        if ((left && typeof left === 'object') || (right && typeof right === 'object')) {
            try { return JSON.stringify(left || null) === JSON.stringify(right || null); }
            catch (error) { return false; }
        }
        return String(left) === String(right);
    }

    function hasUsableValue(source, key) {
        if (!source || !Object.prototype.hasOwnProperty.call(source, key)) return false;
        return source[key] !== undefined && source[key] !== null && source[key] !== '';
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

    function compactProductPathSelection(selection) {
        var def = settingDef('product_path_selection') || {};
        var utils = window.ProductPathSelectionUtils || {};
        if (utils.compactSelection) return utils.compactSelection(selection, def.serialization || {});
        var id = selectionId(selection);
        if (!selection || !id) return null;
        var serialization = def.serialization || {};
        var idKeys = serialization.id_keys || ['product_path_selection_id', 'selection_id', 'id'];
        var referenceKeys = serialization.product_group_reference_keys || ['product_group_template_id', 'path_id'];
        var sourceType = serialization.product_group_source_type || 'user_product_group_template';
        var manualPathKeys = serialization.manual_path_keys || ['paths', 'selected_paths'];
        var productGroupId = '';
        referenceKeys.forEach(function(key) {
            if (!productGroupId && selection[key]) productGroupId = String(selection[key]);
        });
        if (!productGroupId && selection.source_type === sourceType) {
            idKeys.forEach(function(key) {
                if (!productGroupId && selection[key]) productGroupId = String(selection[key]);
            });
        }
        if (productGroupId) return { product_path_selection_id: productGroupId };
        var paths = [];
        manualPathKeys.forEach(function(key) {
            if (!paths.length && Array.isArray(selection[key])) paths = selection[key];
        });
        var compact = { product_path_selection_id: id };
        if (Array.isArray(paths) && paths.length) {
            compact.paths = paths.map(function(path) { return String(path || '').trim(); }).filter(Boolean);
        }
        return compact;
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

    function findProductPathSelectionById(selectionIdValue) {
        var sid = String(selectionIdValue || '');
        if (!sid) return null;
        for (var i = 0; i < state.productPathSelections.length; i++) {
            if (selectionId(state.productPathSelections[i]) === sid) return state.productPathSelections[i];
        }
        return null;
    }

    function resolveProductPathSelectionReference(selection) {
        if (!selection || typeof selection !== 'object') return selection;
        var paths = selection.paths || selection.selected_paths || [];
        if (Array.isArray(paths) && paths.length) return selection;
        return findProductPathSelectionById(selectionId(selection)) || selection;
    }

    function resolveSnapshotProductPathReferences(groupSettings, local) {
        local = local || {};
        if (local.product_path_selection) {
            local.product_path_selection = resolveProductPathSelectionReference(local.product_path_selection);
        }
        var groups = groupSettings && Array.isArray(groupSettings.groups) ? groupSettings.groups : [];
        groups.forEach(function(group) {
            if (group && group.product_path_selection) {
                group.product_path_selection = resolveProductPathSelectionReference(group.product_path_selection);
            }
        });
        var lsConfigs = groupSettings && Array.isArray(groupSettings.lsConfigs) ? groupSettings.lsConfigs : [];
        lsConfigs.forEach(function(config) {
            if (config && config.product_path_selection) {
                config.product_path_selection = resolveProductPathSelectionReference(config.product_path_selection);
            }
        });
    }

    function resolveSnapshotProductPathReferencesAsync(snapshot) {
        snapshot = snapshot || {};
        var groupSettings = snapshot.group_settings ? snapshot.group_settings : snapshot;
        var local = snapshot.local_settings || {};
        var groups = groupSettings && Array.isArray(groupSettings.groups) ? groupSettings.groups : [];
        var lsConfigs = groupSettings && Array.isArray(groupSettings.lsConfigs) ? groupSettings.lsConfigs : [];
        var items = [local].concat(groups).concat(lsConfigs);
        var ids = [];
        items.forEach(function(item) {
            var selection = item && item.product_path_selection;
            if (selection && typeof selection === 'object' && selectionId(selection) && !selection.product_group && !selection.label && !selection.product_group_template_id && !(Array.isArray(selection.paths) && selection.paths.length)) {
                ids.push(selectionId(selection));
            }
        });
        var ready = ids.length ? resolveProductPathSelectionsByIds(ids) : Promise.resolve(state.productPathSelections);
        return ready.catch(function(error) {
            console.warn('[backend-settings] product path selection resolve failed:', error);
            return state.productPathSelections;
        }).then(function() {
            resolveSnapshotProductPathReferences(groupSettings, local);
            return snapshot;
        });
    }


    function productPathSelectionLabel(selection) {
        if (!selection) return '';
        var utils = window.ProductPathSelectionUtils || {};
        if (utils.selectionDisplayLabel) return utils.selectionDisplayLabel(selection);
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

    function mergeProductPathSelections(selections) {
        (selections || []).forEach(function(selection) {
            var id = selectionId(selection);
            if (!id) return;
            var existingIndex = -1;
            for (var i = 0; i < state.productPathSelections.length; i++) {
                if (selectionId(state.productPathSelections[i]) === id) {
                    existingIndex = i;
                    break;
                }
            }
            if (existingIndex >= 0) state.productPathSelections[existingIndex] = selection;
            else state.productPathSelections.push(selection);
        });
        if (selections && selections.length) {
            document.dispatchEvent(new CustomEvent('groupTestProductPathSelectionsChanged'));
        }
    }

    function removeProductPathSelection(id) {
        id = String(id || '');
        state.productPathSelections = state.productPathSelections.filter(function(item) {
            return selectionId(item) !== id;
        });
        if (selectionId(state.localValues.product_path_selection) === id) setDefaultProductPathSelection(null);
        document.dispatchEvent(new CustomEvent('groupTestProductPathSelectionsChanged'));
    }

    function isManualProductPathSelection(selection) {
        return selection && (selection.source_type === 'runtime_manual_path_group' || !(selection.product_group_template_id || selection.product_group || selection.product_group_name || selection.path_id));
    }

    function resolveProductPathSelectionsByIds(ids) {
        ids = (ids || []).map(function(id) { return String(id || '').trim(); }).filter(Boolean);
        var unique = [];
        ids.forEach(function(id) {
            if (unique.indexOf(id) < 0 && !findProductPathSelectionById(id) && !state.productPathSelectionResolveRequests[id]) unique.push(id);
        });
        var pending = ids
            .map(function(id) { return state.productPathSelectionResolveRequests[id]; })
            .filter(Boolean);
        if (!unique.length) {
            return (pending.length ? Promise.all(pending) : Promise.resolve()).then(function() {
                return state.productPathSelections;
            });
        }
        var request = fetch('/api/product-groups/resolve', {
            method: 'POST',
            headers: {
                Accept: 'application/json',
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            },
            credentials: 'same-origin',
            body: JSON.stringify({ ids: unique }),
        }).then(function(response) {
            return response.json().catch(function() { return {}; }).then(function(payload) {
                if (!response.ok || payload.success === false) {
                    throw new Error(payload.error || ('HTTP ' + response.status));
                }
                mergeProductPathSelections((payload.groups || []).map(productGroupToSelection));
                return state.productPathSelections;
            });
        }).finally(function() {
            unique.forEach(function(id) { delete state.productPathSelectionResolveRequests[id]; });
        });
        unique.forEach(function(id) { state.productPathSelectionResolveRequests[id] = request; });
        return Promise.all(pending.concat([request])).then(function() {
            return state.productPathSelections;
        });
    }

    function loadProductPathSelections(force) {
        if (state.productPathSelectionsLoaded && !force) {
            return Promise.resolve(state.productPathSelections);
        }
        var pageCandidates = pageProductPathCandidates();
        if (pageCandidates.length) {
            state.productPathSelections = [];
            mergeProductPathSelections(pageCandidates);
            state.productPathSelectionsLoaded = true;
            return Promise.resolve(state.productPathSelections);
        }
        return requestJSON('/api/product-groups').then(function(payload) {
            state.productPathSelections = [];
            mergeProductPathSelections((payload.groups || []).map(productGroupToSelection));
            state.productPathSelectionsLoaded = true;
            return state.productPathSelections;
        });
    }

    function pageProductPathCandidates() {
        var serialization = candidateListSerialization();
        var field = serialization.shared_page_field || 'product_path_candidates';
        if (!window.SingleFactorGlobalSettings || typeof window.SingleFactorGlobalSettings.getDefaultValues !== 'function') return [];
        var values = window.SingleFactorGlobalSettings.getDefaultValues([field]);
        return Array.isArray(values[field]) ? values[field] : [];
    }

    function setDefaultProductPathSelection(selection) {
        if (selection) state.localValues.product_path_selection = selection;
        else delete state.localValues.product_path_selection;
        renderLocalSettingChips();
        document.dispatchEvent(new CustomEvent('groupTestProductPathSelectionsChanged'));
    }

    function candidateListSerialization() {
        var def = settingDef('product_path_candidates') || {};
        return def.serialization || {};
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

    function chipSourceGroup(group, chipDef, options) {
        if (options && options.useOwnValues) return group;
        return chipDef && chipDef.inherit_from_root ? resolveRootGroup(group) : group;
    }

    function resolveChipValue(name, group, source, resolvers) {
        var resolver = resolvers && resolvers[name];
        if (resolver === 'product_path_selection_label') return productPathSelectionLabel(source && source.product_path_selection);
        if (resolver === 'product_mask_count') return nodeProducts(group).length;
        if (resolver === 'product_mask_expand_symbol') return state.expandedProductMasks && state.expandedProductMasks[group.id] ? '▾' : '▸';
        if (name === 'n_groups') return source && source.splitCount != null ? source.splitCount : '';
        if (name === 'group_index') return source && source.groupIndex != null ? source.groupIndex : '';
        return source && source[name] != null ? source[name] : '';
    }

    // group_test 的 chip HTML 改由统一的 ChipRenderer.chipHtml 渲染（与各设置栏同一实现）。
    // 这里提供其取值 ctx：valueOf 取 group/source 字段；resolve 复用 resolveChipValue 的
    // resolver 分发；settingValueFn 用于"每设置一枚"的配置 chip（{value}→displayValue）。
    function gtChipCtx(group, source, settingValueFn) {
        return {
            valueOf: function(name) {
                if (settingValueFn) return settingValueFn(name);
                return source && source[name] != null ? source[name] : '';
            },
            resolve: function(resolverName, name) {
                var oneResolver = {}; oneResolver[name] = resolverName;
                return resolveChipValue(name, group, source, oneResolver);
            },
            renderChipHtml: renderChipHtml,
            escapeHTML: escapeHTML,
        };
    }

    function gtChipHtml(template, valueResolvers, ctx) {
        return window.ChipRenderer.chipHtml({ chip_template: template, value_resolvers: valueResolvers || {} }, ctx);
    }

    // "每设置一枚"的配置 chip：chip_template 里 {value} → displayValue(setting, value)。
    function gtSettingChipHtml(setting, value) {
        return gtChipHtml(setting.chip_template, {}, gtChipCtx(null, null, function(name) {
            return name === 'value' ? displayValue(setting, value) : '';
        }));
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
            keys.forEach(function(key) {
                var def = state.index && state.index.defaults && state.index.defaults[key] || {};
                var storageKey = settingStorageKey(Object.assign({ key: key }, def));
                if (storageKey !== key && def.serialization && def.serialization.kind === 'custom_product_overrides') {
                    var rows = Array.isArray(state.localValues[storageKey]) ? state.localValues[storageKey] : [];
                    var scoped = customProductRowsForSetting(def, rows);
                    state.localValues[storageKey] = rows.filter(function(row) { return scoped.indexOf(row) < 0; });
                    return;
                }
                delete state.localValues[storageKey];
            });
            return;
        }
        var groups = GT.groupSettings && GT.groupSettings.groups && GT.groupSettings.groups.getAll
            ? GT.groupSettings.groups.getAll()
            : [];
        groups.forEach(function(group) {
            var patch = {};
            keys.forEach(function(key) {
                var def = state.index && state.index.defaults && state.index.defaults[key] || {};
                var storageKey = settingStorageKey(Object.assign({ key: key }, def));
                if (storageKey !== key && def.serialization && def.serialization.kind === 'custom_product_overrides') {
                    var rows = Array.isArray(group[storageKey]) ? group[storageKey] : [];
                    var scoped = customProductRowsForSetting(def, rows);
                    patch[storageKey] = rows.filter(function(row) { return scoped.indexOf(row) < 0; });
                    return;
                }
                patch[storageKey] = undefined;
            });
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

    // defaultsForTab 已删除：选择器改走统一的 manifest + store 路径（ChipRenderer 渲染）。

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
        var conditionValues = effectiveValuesForNode(node);
        var key = settingStorageKey(setting);
        if (!settingEditableForValues(setting, conditionValues)) {
            return window.BackendSettingsPanel.defaultValueForValues(setting, conditionValues);
        }
        if (mount === GROUP && node && hasUsableValue(node.value, key)) {
            return node.value[key];
        }
        if (Object.prototype.hasOwnProperty.call(state.localValues, key)) {
            return state.localValues[key];
        }
        return window.BackendSettingsPanel.defaultValueForValues(state.index.defaults[key] || state.index.defaults[setting.key], conditionValues);
    }

    function defaultValuesForCurrentState() {
        var values = Object.create(null);
        var defaults = state.index && state.index.defaults || {};
        Object.keys(defaults).forEach(function(key) {
            values[key] = defaults[key].value;
        });
        Object.keys(defaults).forEach(function(key) {
            values[key] = window.BackendSettingsPanel.defaultValueForValues(defaults[key], values);
        });
        return values;
    }

    function effectiveLocalValues() {
        var values = defaultValuesForCurrentState();
        Object.keys(state.localValues || {}).forEach(function(key) {
            values[key] = state.localValues[key];
        });
        Object.keys(state.index && state.index.defaults || {}).forEach(function(key) {
            if (Object.prototype.hasOwnProperty.call(state.localValues || {}, key)) return;
            values[key] = window.BackendSettingsPanel.defaultValueForValues(state.index.defaults[key], values);
        });
        return values;
    }

    function effectiveValuesForNode(node) {
        var values = effectiveLocalValues();
        Object.keys((node && node.value) || node || {}).forEach(function(key) {
            var source = (node && node.value) || node;
            if (hasUsableValue(source, key)) values[key] = source[key];
        });
        return values;
    }

    function settingVisibleForValues(setting, values) {
        var meta = setting && setting.key && state.index && state.index.defaults
            ? state.index.defaults[setting.key]
            : null;
        return window.BackendSettingsPanel.settingVisibleForValues(Object.assign({}, meta || {}, setting || {}), values);
    }

    function settingVisible(setting, mount) {
        var node = mount === GROUP ? activeNode() : null;
        return settingVisibleForValues(setting, effectiveValuesForNode(node));
    }

    function settingEditableForValues(setting, values) {
        var meta = setting && setting.key && state.index && state.index.defaults
            ? state.index.defaults[setting.key]
            : null;
        return window.BackendSettingsPanel.settingEditableForValues(Object.assign({}, meta || {}, setting || {}), values);
    }

    function settingEditable(setting, mount) {
        var scope = setting && setting.scope_policy;
        if (mount === GROUP && scope === 'local_only') return false;
        if (mount === LOCAL && scope === 'group_only') return false;
        var node = mount === GROUP ? activeNode() : null;
        return settingEditableForValues(setting, effectiveValuesForNode(node));
    }

    function hasMaterializableDefault(key) {
        var defaults = state.index && state.index.defaults || {};
        var def = defaults[key];
        if (!def) return false;
        var scope = def.scope_policy;
        if (scope === 'local_only') return false;
        return def.value !== undefined && def.value !== null && def.value !== '';
    }

    function materializeChildDefaultsForChangedKeys(parentId, keys, options) {
        options = options || {};
        if (!parentId || !GT.groupSettings || !GT.groupSettings.groups) return;
        var groups = GT.groupSettings.groups;
        if (!groups.getChildren || !groups.update) return;
        var parent = groups.get(parentId);
        if (!parent) return;
        var skipIds = {};
        (options.skipIds || []).forEach(function(id) {
            if (id) skipIds[String(id)] = true;
        });
        var children = groups.getChildren(parentId) || [];
        (children || []).forEach(function(child) {
            if (!child || !child.id) return;
            if (skipIds[String(child.id)]) return;
            var patch = {};
            (keys || []).forEach(function(key) {
                if (!hasMaterializableDefault(key)) return;
                if (!hasUsableValue(parent, key)) return;
                if (hasUsableValue(child, key)) return;
                var def = state.index.defaults[key];
                if (valuesEqual(parent[key], def.value)) return;
                patch[key] = def.value;
            });
            if (Object.keys(patch).length) {
                patch.needsRegenerate = true;
                try { groups.update(child.id, patch); }
                catch (error) { console.warn('[backend-settings] materialize child defaults failed:', error); }
            }
        });
    }

    function writeValue(setting, mount, value) {
        var key = settingStorageKey(setting);
        if (mount === GROUP) {
            var node = activeNode();
            if (!node) throw new Error('编辑组合设置前必须选择组合');
            var patch = {};
            patch[key] = value;
            if (node.kind === 'group') {
                var ctx = GT.modes && GT.modes.isMode && GT.modes.isMode('edit') && GT.modes.getEditContext
                    ? GT.modes.getEditContext()
                    : null;
                var targets = ctx && Array.isArray(ctx.groups) && ctx.groups.length > 1 ? ctx.groups : [node.value];
                var selectedIds = targets.map(function(group) { return group && group.id; }).filter(Boolean);
                targets.forEach(function(group) {
                    if (group && group.id) {
                        GT.groupSettings.groups.update(group.id, patch);
                        materializeChildDefaultsForChangedKeys(group.id, [setting.key], { skipIds: selectedIds });
                    }
                });
            } else {
                GT.groupSettings.lsConfigs.update(state.activeGroup, patch);
            }
        } else {
            state.localValues[key] = value;
            var store = ensureGtLocalStore();
            if (store && typeof store.set === 'function') store.set(key, value);
            else renderLocalSettingChips();
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
        var disabled = (mount === GROUP && !state.activeGroup) || !settingEditable(setting, mount);
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
        } else if (setting.control_template === 'boolean') {
            control = document.createElement('input');
            control.type = 'checkbox';
            control.style.width = '16px';
            control.style.height = '16px';
            control.style.margin = '0';
        } else if (setting.control_template === 'custom_product_overrides') {
            control = renderCustomProductOverridesControl(setting, mount, rerenderAfterChange, disabled);
            return control;
        } else if (setting.control_template === 'custom') {
            // 自定义控件（候选/多选列表，如 factor_candidates / product_path_candidates /
            // category_candidates）：行内不内联完整管理 UI，显示摘要 chip + "管理"按钮，
            // 点击挂载并跳转到对应设置 tab。
            control = document.createElement('div');
            control.style.cssText = 'display:flex;align-items:center;gap:8px;';
            var summary = document.createElement('span');
            summary.className = 'gt-backend-chip unified-backend-chip';
            try {
                var summaryValue = effectiveValue(setting, mount);
                if (mount === LOCAL) {
                    var localStore = ensureGtLocalStore();
                    if (localStore && typeof localStore.effective === 'function') summaryValue = localStore.effective(settingStorageKey(setting));
                }
                summary.innerHTML = renderChipHtml(setting.label || setting.key, window.BackendSettingsPanel.displaySettingValue(setting, summaryValue));
            }
            catch (e) { summary.textContent = '—'; }
            control.appendChild(summary);
            var manageBtn = document.createElement('button');
            manageBtn.type = 'button';
            manageBtn.textContent = '管理';
            manageBtn.style.cssText = 'height:24px;padding:0 10px;border:1px solid #93c5fd;border-radius:4px;background:#eff6ff;color:#1d4ed8;font-size:12px;cursor:pointer;';
            var targetTab = setting.tab || setting.tab_key;
            manageBtn.addEventListener('click', function() {
                if (targetTab && GT.tabs && typeof GT.tabs.mountTab === 'function') GT.tabs.mountTab(targetTab);
                if (mount === LOCAL && setting.serialization && setting.serialization.kind === 'factor_candidate_list') {
                    state.inlineManagers[targetTab || setting.key] = !state.inlineManagers[targetTab || setting.key];
                    rerenderAfterChange();
                    return;
                }
            });
            control.appendChild(manageBtn);
            return control;
        } else {
            throw new Error('不支持的控件模板: ' + setting.control_template);
        }
        if (setting.control_template === 'boolean') {
            control.checked = !!effectiveValue(setting, mount);
        } else {
            control.value = effectiveValue(setting, mount);
        }
        control.disabled = disabled;
        applyDisabledControlStyle(control, disabled);
        control.addEventListener('change', function() {
            if (setting.control_template === 'date' && !/^\d{4}-\d{2}-\d{2}$/.test(control.value || '')) {
                return;
            }
            var nextValue = setting.control_template === 'boolean'
                ? !!control.checked
                : setting.control_template === 'number'
                ? Number(control.value)
                : normalizeControlValue(setting, control.value);
            if (setting.control_template !== 'boolean') control.value = nextValue;
            writeValue(setting, mount, nextValue);
            rerenderAfterChange();
        });
        return control;
    }

    function applyDisabledControlStyle(control, disabled) {
        if (!control) return;
        if (disabled) {
            control.classList.add('gt-backtest-setting-control-disabled');
            control.style.background = '#f8fafc';
            control.style.color = '#94a3b8';
            control.style.borderColor = '#cbd5e1';
            control.style.cursor = 'not-allowed';
            control.title = '当前模式下使用后端默认值，切换到自定义模式后可编辑';
        } else {
            control.classList.remove('gt-backtest-setting-control-disabled');
            control.style.cursor = '';
            control.title = '';
        }
    }

    function renderCustomProductOverridesControl(setting, mount, rerenderAfterChange, disabled) {
        var host = document.createElement('div');
        host.style.cssText = 'display:flex;flex-direction:column;gap:8px;width:100%;margin:0;box-sizing:border-box;overflow:hidden;';
        if (disabled) {
            host.style.opacity = '0.72';
            host.title = '当前模式下使用后端默认值，切换到自定义模式后可编辑';
        }
        var table = document.createElement('div');
        table.style.cssText = 'display:flex;flex-direction:column;gap:6px;margin:0;width:100%;box-sizing:border-box;';
        var addBtn = document.createElement('button');
        addBtn.type = 'button';
        addBtn.textContent = '+ 字段';
        addBtn.style.cssText = 'align-self:flex-start;height:26px;margin:0;padding:0 10px;box-sizing:border-box;border:1px solid #93c5fd;border-radius:4px;background:#eff6ff;color:#1d4ed8;font-size:12px;cursor:pointer;';
        addBtn.disabled = !!disabled;
        if (disabled) addBtn.style.cssText = 'align-self:flex-start;height:26px;margin:0;padding:0 10px;box-sizing:border-box;border:1px solid #cbd5e1;border-radius:4px;background:#f8fafc;color:#94a3b8;font-size:12px;cursor:not-allowed;';
        host.appendChild(table);
        host.appendChild(addBtn);

        function rows() {
            var value = effectiveValue(setting, mount);
            return Array.isArray(value) ? value.slice() : [];
        }
        function moduleFilter() {
            return setting.serialization && setting.serialization.module_filter || '';
        }
        function fieldBelongsToEditor(field) {
            var filter = moduleFilter();
            if (!filter) return true;
            return String(selectedFieldMeta(field).module || '') === String(filter);
        }
        function visibleRows(allRows) {
            return (allRows || []).filter(function(row) {
                return row && fieldBelongsToEditor(row.field);
            });
        }
        function writeRows(nextRows) {
            var filter = moduleFilter();
            var retained = rows().filter(function(row) {
                return filter && !fieldBelongsToEditor(row.field);
            });
            var scoped = nextRows.filter(function(row) {
                return row && (row.product || row.field || row.value !== undefined && row.value !== '');
            });
            var nextAllRows = retained.concat(scoped);
            writeValue(setting, mount, nextAllRows);
            activateCustomProductModules(nextAllRows);
            render();
            rerenderAfterChange();
        }
        function fieldOptions() {
            var options = (setting.serialization && setting.serialization.fields) || [];
            var filter = moduleFilter();
            if (!filter) return options;
            return options.filter(function(item) {
                return String(item.module || '') === String(filter);
            });
        }
        function selectedFieldMeta(field) {
            var options = fieldOptions();
            for (var i = 0; i < options.length; i++) {
                if (String(options[i].value) === String(field)) return options[i];
            }
            return {};
        }
        function customProductEditorForModule(moduleName) {
            var defaults = state.index && state.index.defaults || {};
            var keys = Object.keys(defaults);
            for (var i = 0; i < keys.length; i++) {
                var def = defaults[keys[i]] || {};
                var serialization = def.serialization || {};
                if (serialization.kind !== 'custom_product_overrides') continue;
                if (serialization.module_filter && String(serialization.module_filter) === String(moduleName)) {
                    return Object.assign({ key: keys[i] }, def);
                }
            }
            return null;
        }
        function modePatchForCustomEditor(editor) {
            var modeWhen = editor && editor.serialization && editor.serialization.module_editor
                && editor.serialization.module_editor.mode_when || {};
            var keys = Object.keys(modeWhen);
            for (var i = 0; i < keys.length; i++) {
                var values = Array.isArray(modeWhen[keys[i]]) ? modeWhen[keys[i]] : [modeWhen[keys[i]]];
                if (values.length) return { key: keys[i], value: values[0] };
            }
            return null;
        }
        function activateCustomProductModules(allRows) {
            var serialization = setting.serialization || {};
            if (settingStorageKey(setting) !== 'custom_product_fields') return;
            if (serialization.kind !== 'custom_product_overrides' || serialization.module_filter) return;
            var activated = {};
            (allRows || []).forEach(function(row) {
                var moduleName = selectedFieldMeta(row && row.field).module;
                if (!moduleName || activated[moduleName]) return;
                activated[moduleName] = true;
                var editor = customProductEditorForModule(moduleName);
                if (!editor) return;
                var tabKey = editor.tab_key || editor.tab || editor.serialization && editor.serialization.module_editor && editor.serialization.module_editor.tab;
                if (tabKey && !isMounted(mount, tabKey)) toggleMounted(mount, tabKey, true);
                var patch = modePatchForCustomEditor(editor);
                if (!patch) return;
                var defaults = state.index && state.index.defaults || {};
                var modeDef = defaults[patch.key];
                if (!modeDef) return;
                var modeSetting = Object.assign({ key: patch.key }, modeDef);
                if (effectiveValue(modeSetting, mount) !== patch.value) {
                    writeValue(modeSetting, mount, patch.value);
                }
            });
        }
        function fieldLabel(field) {
            return window.BackendSettingsPanel.customProductFieldLabel(setting, field);
        }
        function cellInput(type, value, onChange, placeholder) {
            var input = document.createElement('input');
            input.type = type || 'text';
            input.value = value == null ? '' : value;
            input.placeholder = placeholder || '';
            input.style.cssText = 'height:26px;margin:0;box-sizing:border-box;width:100%;border:1px solid #cbd5e1;border-radius:4px;padding:0 6px;font-size:12px;min-width:0;';
            input.addEventListener('change', function() { onChange(input.value); });
            return input;
        }
        function valueInput(meta, value, onChange) {
            if (meta.value_type === 'select') {
                var select = document.createElement('select');
                select.style.cssText = 'height:26px;margin:0;box-sizing:border-box;width:100%;border:1px solid #cbd5e1;border-radius:4px;padding:0 6px;font-size:12px;min-width:0;';
                (meta.value_options || []).forEach(function(item) {
                    var option = document.createElement('option');
                    option.value = Array.isArray(item) ? item[0] : item.value;
                    option.textContent = Array.isArray(item) ? item[1] : item.label;
                    select.appendChild(option);
                });
                select.value = value == null ? '' : value;
                select.addEventListener('change', function() { onChange(select.value); });
                return select;
            }
            return cellInput('number', value, function(nextValue) {
                onChange(nextValue === '' ? '' : Number(nextValue));
            }, '值');
        }
        function render() {
            table.innerHTML = '';
            var current = visibleRows(rows());
            if (!current.length) {
                var empty = document.createElement('div');
                empty.style.cssText = 'color:#64748b;font-size:12px;margin:0;';
                empty.textContent = disabled ? '无（切换到自定义模式后可编辑）' : '无';
                table.appendChild(empty);
            }
            current.forEach(function(row, index) {
                var line = document.createElement('div');
                line.style.cssText = 'display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1.35fr) minmax(0,.85fr) minmax(0,1fr) minmax(0,1fr) 26px;gap:6px;align-items:center;margin:0;width:100%;box-sizing:border-box;';
                var productInput = cellInput('text', row.product || '', function(value) {
                    current[index] = Object.assign({}, current[index], { product: value });
                    writeRows(current);
                }, '产品/合约代码');
                productInput.disabled = !!disabled;
                applyDisabledControlStyle(productInput, disabled);
                line.appendChild(productInput);
                var select = document.createElement('select');
                select.style.cssText = 'height:26px;margin:0;box-sizing:border-box;width:100%;border:1px solid #cbd5e1;border-radius:4px;padding:0 6px;font-size:12px;min-width:0;';
                fieldOptions().forEach(function(item) {
                    var option = document.createElement('option');
                    option.value = item.value;
                    option.textContent = fieldLabel(item.value);
                    if (item.unit) option.title = String(item.unit);
                    select.appendChild(option);
                });
                select.value = row.field || (fieldOptions()[0] && fieldOptions()[0].value) || '';
                select.disabled = !!disabled;
                applyDisabledControlStyle(select, disabled);
                select.addEventListener('change', function() {
                    current[index] = Object.assign({}, current[index], { field: select.value, start: '', end: '' });
                    writeRows(current);
                });
                line.appendChild(select);
                var meta = selectedFieldMeta(select.value);
                var valueControl = valueInput(meta, row.value, function(value) {
                    current[index] = Object.assign({}, current[index], { value: value });
                    writeRows(current);
                });
                valueControl.disabled = !!disabled;
                applyDisabledControlStyle(valueControl, disabled);
                line.appendChild(valueControl);
                var allowRange = meta.allow_time_range !== false;
                var start = cellInput('datetime-local', row.start || '', function(value) {
                    current[index] = Object.assign({}, current[index], { start: value });
                    writeRows(current);
                });
                var end = cellInput('datetime-local', row.end || '', function(value) {
                    current[index] = Object.assign({}, current[index], { end: value });
                    writeRows(current);
                });
                start.disabled = !allowRange || !!disabled;
                end.disabled = !allowRange || !!disabled;
                applyDisabledControlStyle(start, start.disabled);
                applyDisabledControlStyle(end, end.disabled);
                line.appendChild(start);
                line.appendChild(end);
                var remove = document.createElement('button');
                remove.type = 'button';
                remove.textContent = '×';
                remove.style.cssText = 'height:26px;width:26px;margin:0;padding:0;box-sizing:border-box;border:1px solid #fecaca;border-radius:4px;background:#fff1f2;color:#be123c;cursor:pointer;';
                remove.disabled = !!disabled;
                if (disabled) remove.style.cssText = 'height:26px;width:26px;margin:0;padding:0;box-sizing:border-box;border:1px solid #cbd5e1;border-radius:4px;background:#f8fafc;color:#94a3b8;cursor:not-allowed;';
                remove.addEventListener('click', function() {
                    if (disabled) return;
                    current.splice(index, 1);
                    writeRows(current);
                });
                line.appendChild(remove);
                table.appendChild(line);
            });
        }
        addBtn.addEventListener('click', function() {
            if (disabled) return;
            var current = visibleRows(rows());
            current.push({ product: '', field: (fieldOptions()[0] && fieldOptions()[0].value) || '', value: '' });
            writeRows(current);
        });
        render();
        return host;
    }

    /**
     * Render the product-path-selection management UI into `container`.
     * `opts.getCurrent`/`opts.setCurrent` let callers scope "当前选中" to something
     * other than the page-level local default (e.g. an add-draft or a specific group),
     * so the same manager UI can be reused inside the group-add/edit chip-list panel.
     */
    function renderProductPathSelectionManager(container, opts) {
        opts = opts || {};
        var getCurrent = opts.getCurrent || function() { return state.localValues.product_path_selection; };
        var setCurrent = opts.setCurrent || setDefaultProductPathSelection;
        container.innerHTML = '<div style="color:#64748b;font-size:12px;">正在加载产品路径...</div>';
        loadProductPathSelections().then(function(selections) {
            if (!window.ProductPathSelectionUtils || typeof window.ProductPathSelectionUtils.renderSelectionSettingsTab !== 'function') {
                container.textContent = '产品路径设置组件未加载';
                return;
            }
            window.ProductPathSelectionUtils.renderSelectionSettingsTab({
                host: container,
                prefix: 'gt-pps',
                selections: selections,
                currentSelection: getCurrent(),
                currentLabel: '当前默认',
                manualTitle: '现场新增路径组',
                createLabel: '新增',
                createDefaultLabel: '新增并设为默认',
                escapeHTML: escapeHTML,
                productCount: function(selection) { return productPathSelectionProducts(selection).length; },
                allowRemove: isManualProductPathSelection,
                onOpen: function(selected) {
                    if (!selected || !GT.overlays || !GT.overlays.productPathSelectionProducts) return;
                    GT.overlays.productPathSelectionProducts.open(
                        productPathSelectionLabel(selected),
                        productPathSelectionProducts(selected),
                        selected
                    );
                },
                onSetDefault: function(selected) {
                    setCurrent(selected);
                    renderProductPathSelectionManager(container, opts);
                },
                onRemove: function(selected) {
                    var id = selectionId(selected);
                    var name = productPathSelectionLabel(selected);
                    if (!name || !confirm('移除现场产品路径组 "' + name + '"？')) return;
                    removeProductPathSelection(id);
                    renderProductPathSelectionManager(container, opts);
                },
                onCreate: function(selection, meta) {
                    mergeProductPathSelections([selection]);
                    if (meta && meta.setAsDefault) setCurrent(selection);
                    renderProductPathSelectionManager(container, opts);
                },
            });
        }).catch(function(error) {
            container.textContent = '加载失败：' + error.message;
        });
    }

    function renderFactorManager(container, opts) {
        opts = opts || {};
        var multiple = !!opts.multiple;
        var hasExternalToggle = typeof opts.onToggle === 'function';
        var utils = window.FactorParamSelectionUtils;
        if (!utils || typeof utils.renderFactorStoreManager !== 'function') {
            container.textContent = '因子参数设置组件未加载';
            return;
        }
        var store = opts.store || ensureGtLocalStore();
        var ffAlias = window.factorFamilyAlias || '';
        var libraryPromise = function() { return ffAlias
            ? requestJSON('/custom-factors/api/factor-library-overview?factor_family_alias=' + encodeURIComponent(ffAlias)).catch(function() { return { factors: [] }; })
            : Promise.resolve({ factors: [] }); };
        utils.renderFactorStoreManager({
            host: container,
            prefix: opts.prefix || 'gt-fps',
            store: store,
            candidateKey: opts.candidateKey || 'factor_candidates',
            factorKey: opts.factorKey || 'factor',
            factorFamilyAlias: ffAlias,
            paramDefs: opts.paramDefs || [],
            multiple: multiple,
            selected: opts.selected,
            onToggle: hasExternalToggle ? function(alias) { opts.onToggle(alias); } : undefined,
            onSetDefault: hasExternalToggle ? function(alias) { opts.onToggle(alias); } : undefined,
            loadLibraryParams: function() {
                return libraryPromise().then(function(payload) {
            var libraryItems = Array.isArray(payload.factors) ? payload.factors : [];
                    return libraryItems.map(function(item) {
                return utils.factorItemToParamSelection ? utils.factorItemToParamSelection(item) : item;
            });
                });
            },
            onRegisterParam: function(param) {
                if (!param || !ffAlias) return param;
                return addFactorByParams(ffAlias, param.params || {}).then(function(data) {
                    if (data && data.factor_alias) {
                        return Object.assign({}, param, { factor_alias: data.factor_alias });
                    }
                    return param;
                });
            },
            escapeHTML: escapeHTML,
        });
    }

    // 新增一个因子候选：POST /add_factor_by_params（写入 page_factors），
    // 成功后刷新 window.factorList（与 IC 共用同一全局列表与刷新入口）。
    function addFactorByParams(factorFamilyAlias, params) {
        return fetch('/add_factor_by_params', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                factor_family_alias: factorFamilyAlias,
                params: params || {},
                page_uuid: window._pageUuid || '',
            }),
        }).then(function(res) { return res.json(); }).then(function(data) {
            if (data && data.success && data.factor_alias && typeof window.refreshICModule === 'function') {
                return Promise.resolve(window.refreshICModule()).then(function() { return data; });
            }
            return data;
        }).catch(function(err) {
            console.error('[gt factor-manager] add_factor_by_params failed:', err);
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
                var node = document.createElement('span');
                node.className = 'gt-backend-chip';
                node.innerHTML = gtSettingChipHtml(setting, effectiveValue(setting, mount));
                chips.appendChild(node);
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
        if (mount === LOCAL && manifest.tab && state.inlineManagers[manifest.tab.key]) {
            var hasFactorCandidates = (manifest.settings || []).some(function(setting) {
                return setting && setting.serialization && setting.serialization.kind === 'factor_candidate_list';
            });
            if (hasFactorCandidates) {
                var managerWrap = document.createElement('div');
                managerWrap.style.cssText = 'margin-top:10px;border:1px solid #e5e7eb;border-radius:8px;background:#fff;overflow:hidden;';
                container.appendChild(managerWrap);
                renderFactorManager(managerWrap, {
                    multiple: false,
                    store: ensureGtLocalStore(),
                    selected: (ensureGtLocalStore() && ensureGtLocalStore().effective('factor')) || '',
                });
            }
        }
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
        if (!window.BackendSettingsPanel || typeof window.BackendSettingsPanel.renderChooser !== 'function') return;
        // 统一走 manifest + store 路径（与其它模块的选择器一致），chip 由 ChipRenderer 渲染。
        window.BackendSettingsPanel.renderChooser({
            host: container,
            manifest: state.index,
            store: ensureGtLocalStore(),
            tabs: availableTabs(mount),
            mountedTabs: state.mountedTabs[mount],
            introText: '选择要挂载到此栏的回测设置。未挂载项继续使用下列默认值。',
            introClassName: 'backend-settings-chooser-intro gt-backtest-settings-chooser-intro',
            rowClassName: 'backend-settings-chooser-row gt-backtest-settings-chooser-row',
            bodyClassName: 'backend-settings-chooser-body gt-backtest-settings-chooser-body',
            titleClassName: 'backend-settings-chooser-title gt-backtest-settings-chooser-title',
            defaultsClassName: 'backend-settings-chooser-defaults gt-backtest-settings-chooser-defaults',
            onToggle: function(tab, enabled) { toggleMounted(mount, tab.key, enabled); },
            escapeHTML: escapeHTML,
            renderChipHtml: renderChipHtml,
        });
    }

    function localHost() { return document.getElementById('gt-backtest-local-host'); }

    function localChipRow() { return document.getElementById('gt-local-settings-chip-row'); }

    // 响应式 chip：manifest 建 FieldStore（backing = state.localValues），ChipRenderer 订阅。
    // 这是"tab/内容"那条 chip 行——点击 chip 打开/关闭对应设置 tab（保留 onOpen=openLocal）。
    var gtLocalStore = null, gtLocalChipUnbind = null;
    function ensureGtLocalStore() {
        if (!gtLocalStore && state.index && window.FieldStore) {
            gtLocalStore = window.FieldStore.create({ defaults: state.index.defaults, values: state.localValues, parent: window._singleFactorPageStore || null });
        }
        if (gtLocalStore && window._singleFactorPageStore && gtLocalStore.setParent) {
            gtLocalStore.setParent(window._singleFactorPageStore);
        }
        return gtLocalStore;
    }

    function renderLocalSettingChips() {
        var row = document.getElementById('gt-local-settings-chip-row');
        if (!row) return;
        if (!state.index) { row.style.display = 'none'; return; }
        var store = ensureGtLocalStore();
        if (store) store.setMany(state.localValues);
        if (gtLocalChipUnbind) { gtLocalChipUnbind(); gtLocalChipUnbind = null; }
        var keys = [];
        orderedMountedTabs(LOCAL).forEach(function(tabKey) {
            settingKeysForTab(tabKey).forEach(function(key) {
                if ((state.index.defaults[key] || {}).chip_template) keys.push(key);
            });
        });
        if (window.ChipRenderer && store) {
            gtLocalChipUnbind = window.ChipRenderer.render(row, {
                manifest: { defaults: state.index.defaults },
                store: store,
                settingKeys: keys,
                tabOf: function(key) { return (state.index.defaults[key] || {}).tab_key || key; },
                onOpen: function(tabKey) { openLocal(tabKey); },
                escapeHTML: escapeHTML,
                renderChipHtml: renderChipHtml,
            });
        } else {
            row.innerHTML = '';
        }
        var anyVisible = Array.prototype.some.call(row.children, function(c) { return c.style.display !== 'none'; });
        row.style.display = anyVisible ? 'flex' : 'none';
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

    function parentFieldDiffers(group, key, value) {
        var source = group && group.value ? group.value : group;
        if (!source || !source.parentId || !GT.groupSettings || !GT.groupSettings.groups || !GT.groupSettings.groups.get) return false;
        var parent = GT.groupSettings.groups.get(source.parentId);
        if (!parent || !hasUsableValue(parent, key)) return false;
        return !valuesEqual(parent[key], value);
    }

    function configSettingKeys() {
        var defaults = state.index && state.index.defaults || {};
        var keys = Object.keys(defaults).filter(function(key) {
            var setting = settingDef(key);
            var scope = setting.scope_policy || (defaults[key] && defaults[key].scope_policy);
            return scope !== 'local_only' && !!setting.chip_template;
        });
        return window.BackendSettingsPanel.sortSettingKeysByDisplayOrder(keys, defaults);
    }

    function effectiveSettingValueForGroup(group, key) {
        var source = group && group.value ? group.value : group;
        if (hasUsableValue(source, key)) return source[key];
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
        if (!settingEditableForValues(setting, values)) {
            value = window.BackendSettingsPanel.defaultValueForValues(setting, values);
            values[key] = value;
        }
        if (!setting.chip_template) return null;
        return {
            label: 'backtest-' + key,
            html: gtSettingChipHtml(setting, value),
            category: 'config',
            style: null,
        };
    }

    function backendSettingChips(group) {
        if (!group) return [];
        var defaults = state.index && state.index.defaults || {};
        var values = effectiveValuesForNode(group);
        var keys = Object.keys(defaults).filter(function(key) {
            return Object.prototype.hasOwnProperty.call(group, key);
        });
        return window.BackendSettingsPanel.sortSettingKeysByDisplayOrder(keys, defaults).map(function(key) {
            var value = group[key];
            if (value === undefined || value === null || value === '') return null;
            var setting = settingDef(key);
            var scope = setting.scope_policy || (defaults[key] && defaults[key].scope_policy);
            if (scope === 'local_only') return null;
            if (!settingVisibleForValues(setting, values)) return null;
            if (!settingEditableForValues(setting, values)) {
                value = window.BackendSettingsPanel.defaultValueForValues(setting, values);
            }
            var localValue = effectiveLocalValues()[key];
            var differsFromLocal = !valuesEqual(value, localValue);
            var defaultValue = defaults[key]
                ? window.BackendSettingsPanel.defaultValueForValues(defaults[key], values)
                : undefined;
            var differsFromDefault = defaults[key] && !valuesEqual(value, defaultValue);
            var differsFromParent = parentFieldDiffers(group, key, value);
            if (!differsFromLocal && !differsFromDefault && !differsFromParent) return null;
            if (settingIsShownInMountedTab(GROUP, key) && !differsFromLocal && !differsFromDefault && !differsFromParent) return null;
            if (!setting.chip_template) return null;
            return {
                label: 'backtest-' + key,
                html: gtSettingChipHtml(setting, value),
                category: 'config',
                style: null,
            };
        }).filter(Boolean);
    }

    function manifestChips(group, categories, options) {
        if (!group || !state.index) return [];
        var filter = null;
        if (categories) {
            filter = {};
            (Array.isArray(categories) ? categories : [categories]).forEach(function(category) { filter[category] = true; });
        }
        var chips = [];
        (state.index.chip_fields || []).forEach(function(def) {
            if (filter && !filter[def.category]) return;
            var source = chipSourceGroup(group, def, options);
            if (!source) return;
            var missing = (def.source_keys || []).some(function(key) {
                return source[key] === undefined || source[key] === null || source[key] === '';
            });
            if (missing) return;
            if (def.key === 'product_mask') {
                var ownMask = group.productMask || {};
                if (!group.parentId || Object.keys(ownMask).length === 0) return;
                var products = nodeProducts(group);
                var parent = GT.groupSettings && GT.groupSettings.groups ? GT.groupSettings.groups.get(group.parentId) : null;
                if (parent && sameProductNames(nodeProducts(parent), products)) return;
            }
            chips.push({
                label: def.key,
                html: gtChipHtml(def.chip_template, def.value_resolvers || {}, gtChipCtx(group, source)),
                category: def.category,
                clickable: !!def.clickable,
                batch_owned: !!def.batch_owned,
                action: def.key === 'tester' ? 'tester-products' : (def.key === 'product_mask' ? 'toggle-product-mask' : ''),
                style: null,
            });
        });
        return chips;
    }

    function getAllChips(group, categories, options) {
        var chips = manifestChips(group, categories, options);
        if (!categories || categories === 'config' || (Array.isArray(categories) && categories.indexOf('config') >= 0)) {
            chips = chips.concat(backendSettingChips(group));
        }
        return chips;
    }

    function getOverrideChips(group) {
        if (!group || !group.parentId || !GT.groupSettings || !GT.groupSettings.groups) return [];
        var parent = GT.groupSettings.groups.get(group.parentId);
        var base = {};
        var categories = ['identity', 'config', 'derived'];
        var options = { useOwnValues: true };
        getAllChips(parent, categories, options).forEach(function(chip) { base[chip.label] = chip.html; });
        var childChips = getAllChips(group, categories, options);
        var childChipLabels = {};
        childChips.forEach(function(chip) { childChipLabels[chip.label] = true; });
        var defaults = state.index && state.index.defaults || {};
        Object.keys(defaults).forEach(function(key) {
            if (childChipLabels['backtest-' + key]) return;
            var def = defaults[key];
            if (!def || !def.chip_template) return;
            var scope = def.scope_policy;
            if (scope === 'local_only') return;
            var parentHasValue = hasUsableValue(parent, key);
            if (!parentHasValue || hasUsableValue(group, key)) return;
            var childValue = def.value;
            var parentValue = parent[key];
            if (childValue === undefined || childValue === null || childValue === '') return;
            if (valuesEqual(childValue, parentValue)) return;
            var values = effectiveValuesForNode(group);
            values[key] = childValue;
            if (!settingVisibleForValues(def, values)) return;
            childChips.push({
                label: 'backtest-' + key,
                html: gtSettingChipHtml(settingDef(key), childValue),
                category: 'config',
                style: null,
            });
            childChipLabels['backtest-' + key] = true;
        });
        return childChips.filter(function(chip) {
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
            copyLocalDefaultsFromProvider('page_shared_defaults', { skipUserValues: true });
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
            if (!window.SingleFactorGlobalSettings || typeof window.SingleFactorGlobalSettings.getDefaultValues !== 'function') return null;
            return window.SingleFactorGlobalSettings.getDefaultValues(RUN_WINDOW_KEYS);
        });
        registerLocalDefaultProvider('page_shared_defaults', function() {
            if (!window.SingleFactorGlobalSettings || typeof window.SingleFactorGlobalSettings.getDefaultValues !== 'function') return null;
            return window.SingleFactorGlobalSettings.getDefaultValues(
                (window.SingleFactorGlobalSettings.sharedDefaultKeys && window.SingleFactorGlobalSettings.sharedDefaultKeys()) || []
            );
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
                default: null,
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
        return resolveSnapshotProductPathReferencesAsync({ group_settings: groupSettings, local_settings: local }).then(function() {
            mountTabsForSnapshotValues(LOCAL, local);
            groups.concat(groupSettings && Array.isArray(groupSettings.lsConfigs) ? groupSettings.lsConfigs : []).forEach(function(item) {
                mountTabsForSnapshotValues(GROUP, item || {});
            });
            clearLoadedLocalEchoOverrides(local);
            renderLocalTabs();
            if (GT.tabs && GT.tabs.refreshTabBar) GT.tabs.refreshTabBar();
            if (GT.events && GT.events.emit) GT.events.emit('groupsChanged');
            return null;
        });
    }

    function clearLoadedLocalEchoOverrides(local) {
        var defaults = state.index && state.index.defaults || {};
        var clearKeys = Object.keys(defaults).filter(function(key) {
            var def = defaults[key];
            return def && def.scope_policy !== 'group_only' && def.scope_policy !== 'local_only';
        });
        if (!clearKeys.length || !GT.groupSettings) return;
        function patchFor(item) {
            var patch = {};
            clearKeys.forEach(function(key) {
                if (!Object.prototype.hasOwnProperty.call(item || {}, key)) return;
                if (valuesEqual(item[key], local[key])) patch[key] = null;
            });
            Object.keys(defaults).forEach(function(key) {
                var def = defaults[key];
                if (def && def.scope_policy === 'local_only' && Object.prototype.hasOwnProperty.call(item || {}, key)) {
                    patch[key] = null;
                }
            });
            return patch;
        }
        if (GT.groupSettings.groups && GT.groupSettings.groups.getAll && GT.groupSettings.groups.update) {
            GT.groupSettings.groups.getAll().forEach(function(group) {
                var patch = patchFor(group);
                if (Object.keys(patch).length) {
                    try { GT.groupSettings.groups.update(group.id, patch); } catch (error) { console.warn('[backend-settings] clear group echo override failed:', error); }
                }
            });
        }
        if (GT.groupSettings.lsConfigs && GT.groupSettings.lsConfigs.getAll && GT.groupSettings.lsConfigs.update) {
            GT.groupSettings.lsConfigs.getAll().forEach(function(config) {
                var patch = patchFor(config);
                if (Object.keys(patch).length) {
                    try { GT.groupSettings.lsConfigs.update(config.id, patch); } catch (error) { console.warn('[backend-settings] clear ls echo override failed:', error); }
                }
            });
        }
    }

    function flattenGroupForSnapshot(group) {
        var source = group || {};
        var out = {};
        var defaults = state.index && state.index.defaults || {};
        var values = effectiveValuesForNode(source);
        var localValues = effectiveLocalValues();
        Object.keys(defaults).forEach(function(key) {
            var def = defaults[key];
            var storageKey = settingStorageKey(Object.assign({ key: key }, def || {}));
            if (!def || !hasVisibleStoredValue(def, source, key)) return;
            if (def.scope_policy === 'local_only') return;
            if (!settingVisibleForValues(def, values)) return;
            if (def.scope_policy !== 'group_only' && valuesEqual(source[storageKey], localValues[storageKey]) && !parentFieldDiffers(source, storageKey, source[storageKey])) return;
            if (def.scope_policy === 'group_only' && valuesEqual(source[storageKey], def.value)) return;
            out[storageKey] = storageKey === 'product_path_selection' ? compactProductPathSelection(source[storageKey]) : source[storageKey];
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
        return Object.assign(stripRegisteredSettings(group), groupOverridesForRun(group));
    }

    function collectLocalSettings() {
        var out = {};
        var defaults = state.index && state.index.defaults || {};
        var values = effectiveLocalValues();
        Object.keys(state.localValues || {}).forEach(function(key) {
            var def = defaults[key];
            if (!def || def.scope_policy === 'group_only') return;
            if (!settingVisibleForValues(def, values)) return;
            if (!settingEditableForValues(def, values)) return;
            if (state.localValues[key] === '' || state.localValues[key] === null || state.localValues[key] === undefined) return;
            if (valuesEqual(state.localValues[key], def.value)) return;
            out[key] = state.localValues[key];
        });
        Object.keys(defaults).forEach(function(key) {
            var def = defaults[key];
            if (!def || def.scope_policy === 'group_only') return;
            var storageKey = settingStorageKey(Object.assign({ key: key }, def));
            if (storageKey === key || Object.prototype.hasOwnProperty.call(out, storageKey)) return;
            if (!hasVisibleStoredValue(def, state.localValues, key)) return;
            if (!settingVisibleForValues(def, values)) return;
            if (!settingEditableForValues(def, values)) return;
            out[storageKey] = state.localValues[storageKey];
        });
        return out;
    }

    function pageRunWindowValues() {
        var provider = state.localDefaultProviders && state.localDefaultProviders.page_time_range;
        var values = typeof provider === 'function' ? provider() : null;
        if (!values || typeof values !== 'object') return {};
        return values;
    }

    function pageSharedDefaultValues() {
        var provider = state.localDefaultProviders && state.localDefaultProviders.page_shared_defaults;
        var values = typeof provider === 'function' ? provider() : null;
        if (!values || typeof values !== 'object') return {};
        return values;
    }

    function shouldUsePageRunWindowForLocalSettings() {
        return !RUN_WINDOW_KEYS.some(function(key) {
            return Object.prototype.hasOwnProperty.call(state.localValues || {}, key);
        });
    }

    function collectRunLocalSettings() {
        var out = {};
        var defaults = state.index && state.index.defaults || {};
        var values = effectiveLocalValues();
        var pageWindow = shouldUsePageRunWindowForLocalSettings() ? pageRunWindowValues() : {};
        Object.keys(state.localValues || {}).forEach(function(key) {
            var def = defaults[key];
            if (!def || def.scope_policy === 'group_only') return;
            if (key === 'product_path_selection') return;
            var value = state.localValues[key];
            var visibilityValues = Object.assign({}, values, state.localValues);
            visibilityValues[key] = value;
            if (!settingVisibleForValues(def, visibilityValues)) return;
            if (!settingEditableForValues(def, visibilityValues)) return;
            if (value === '' || value === null || value === undefined) return;
            out[key] = value;
        });
        Object.keys(defaults).forEach(function(key) {
            var def = defaults[key];
            if (!def || def.scope_policy === 'group_only') return;
            var storageKey = settingStorageKey(Object.assign({ key: key }, def));
            if (storageKey === key || Object.prototype.hasOwnProperty.call(out, storageKey)) return;
            if (!hasVisibleStoredValue(def, state.localValues, key)) return;
            var value = state.localValues[storageKey];
            var visibilityValues = Object.assign({}, values, state.localValues);
            visibilityValues[storageKey] = value;
            if (!settingVisibleForValues(def, visibilityValues)) return;
            if (!settingEditableForValues(def, visibilityValues)) return;
            out[storageKey] = value;
        });
        Object.keys(pageWindow).forEach(function(key) {
            var def = defaults[key];
            if (!def || def.scope_policy === 'group_only') return;
            if (key === 'product_path_selection') return;
            if (Object.prototype.hasOwnProperty.call(out, key)) return;
            var value = normalizeControlValue(def, pageWindow[key]);
            if (value === '' || value === null || value === undefined) return;
            var visibilityValues = Object.assign({}, values, pageWindow, out);
            visibilityValues[key] = value;
            if (!settingVisibleForValues(def, visibilityValues)) return;
            if (!settingEditableForValues(def, visibilityValues)) return;
            out[key] = value;
        });
        Object.keys(pageSharedDefaultValues()).forEach(function(key) {
            var def = defaults[key];
            if (!def || def.scope_policy === 'group_only') return;
            if (key === 'product_path_selection' || RUN_WINDOW_KEYS.indexOf(key) >= 0) return;
            if (Object.prototype.hasOwnProperty.call(out, key)) return;
            if (Object.prototype.hasOwnProperty.call(state.localValues || {}, key)) return;
            var value = normalizeControlValue(def, pageSharedDefaultValues()[key]);
            if (value === '' || value === null || value === undefined) return;
            var visibilityValues = Object.assign({}, values, out);
            visibilityValues[key] = value;
            if (!settingVisibleForValues(def, visibilityValues)) return;
            if (!settingEditableForValues(def, visibilityValues)) return;
            out[key] = value;
        });
        return out;
    }

    function groupOverridesForRun(group) {
        var out = {};
        var defaults = state.index && state.index.defaults || {};
        var values = effectiveValuesForNode(group);
        var localValues = effectiveLocalValues();
        var source = group && group.value ? group.value : group || {};
        Object.keys(defaults).forEach(function(key) {
            var def = defaults[key];
            var storageKey = settingStorageKey(Object.assign({ key: key }, def || {}));
            if (!def || def.scope_policy === 'local_only') return;
            if (!hasVisibleStoredValue(def, source, key)) return;
            if (!settingVisibleForValues(def, values)) return;
            if (!settingEditableForValues(def, values)) return;
            var value = source[storageKey];
            if (def.scope_policy !== 'group_only' && valuesEqual(value, localValues[storageKey]) && !parentFieldDiffers(source, storageKey, value)) return;
            out[storageKey] = value;
        });
        return out;
    }

    function registerSnapshot() {
        state.snapshotRegistered = true;
    }

    function collect() { return collectLocalSettings(); }

    function runPayload() {
        var localSettings = collectRunLocalSettings();
        return { local_settings: localSettings };
    }

    function groupOverrideValues(groupId) {
        var groups = GT.groupSettings && GT.groupSettings.groups;
        var group = groups && groups.get ? groups.get(groupId) : null;
        return group ? Object.assign({}, group) : null;
    }

    function syncPageTimeDefaults() {
        copyLocalDefaultsFromProvider('page_time_range', { blockOnUserKeys: RUN_WINDOW_KEYS });
        renderLocalTabs();
        return Promise.resolve(state.index);
    }

    function syncPageSharedDefaults() {
        copyLocalDefaultsFromProvider('page_shared_defaults', { skipUserValues: true });
        renderLocalTabs();
        renderLocalSettingChips();
        return Promise.resolve(state.index);
    }

    document.addEventListener('timeRangeDefaultLoaded', function() {
        copyLocalDefaultsFromProvider('page_time_range', { blockOnUserKeys: RUN_WINDOW_KEYS });
    });

    document.addEventListener('pageTimeRangeChanged', function() {
        syncPageTimeDefaults().catch(function(error) {
            console.error('[backend-settings] sync page time failed:', error);
        });
    });

    document.addEventListener('singleFactorGlobalSettingsChanged', function() {
        syncPageSharedDefaults().then(function() {
            document.dispatchEvent(new CustomEvent('groupTestProductPathSelectionsChanged'));
        }).catch(function(error) {
            console.error('[backend-settings] sync page shared defaults failed:', error);
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
        materializeChildDefaultsForChangedKeys: materializeChildDefaultsForChangedKeys,
        registerSnapshot: registerSnapshot,
        runPayload: runPayload,
        groupOverrideValues: groupOverrideValues,
        compactProductPathSelection: compactProductPathSelection,
        resolveSnapshotProductPathReferences: resolveSnapshotProductPathReferencesAsync,
        syncPageTimeDefaults: syncPageTimeDefaults,
        syncPageSharedDefaults: syncPageSharedDefaults,
        registerLocalDefaultProvider: registerLocalDefaultProvider,
        copyLocalDefaultsFromProvider: copyLocalDefaultsFromProvider,
        applyLocalDefaultValues: applyLocalDefaultValues,
        openLocalTab: openLocalTab,
        loadProductPathSelections: loadProductPathSelections,
        getProductPathSelections: function() { return state.productPathSelections.slice(); },
        renderProductPathManager: renderProductPathSelectionManager,
        renderFactorManager: renderFactorManager,
        productPathSelectionProducts: productPathSelectionProducts,
        productPathSelectionLabel: productPathSelectionLabel,
        getDefaultProductPathSelection: function() {
            var def = settingDef('product_path_selection') || {};
            return state.localValues.product_path_selection || def.value || null;
        },
        setDefaultProductPathSelection: setDefaultProductPathSelection,
        getAllChips: getAllChips,
        getOverrideChips: getOverrideChips,
        configSettingKeys: configSettingKeys,
        effectiveSettingValueForGroup: effectiveSettingValueForGroup,
        configChipForGroupKey: configChipForGroupKey,
        renderChipHtml: renderChipHtml,
        ensureGtLocalStore: ensureGtLocalStore,
        toggleProductMask: toggleProductMask,
        isProductMaskExpanded: isProductMaskExpanded,
        _state: state,
    };
})();
