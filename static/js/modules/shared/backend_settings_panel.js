(function() {
    function toggleMountedTab(options) {
        options = options || {};
        var mountedTabs = options.mountedTabs;
        var tabKey = options.tabKey;
        if (!Array.isArray(mountedTabs) || !tabKey) return false;
        var enabled = !!options.enabled;
        var index = mountedTabs.indexOf(tabKey);
        var changed = false;
        if (enabled && index < 0) {
            mountedTabs.push(tabKey);
            changed = true;
        }
        if (!enabled && index >= 0) {
            mountedTabs.splice(index, 1);
            changed = true;
            if (typeof options.clearTabValues === 'function') {
                options.clearTabValues(tabKey);
            }
        }
        if (changed && typeof options.afterChange === 'function') {
            options.afterChange(tabKey, enabled);
        }
        return changed;
    }

    function resolveElement(target) {
        if (!target) return null;
        if (typeof target === 'string') return document.querySelector(target);
        return target;
    }

    function visible(element) {
        return !!element && element.style.display !== 'none';
    }

    function setActiveButtons(selector, attr, activeKey) {
        if (!selector || !attr) return;
        document.querySelectorAll(selector).forEach(function(button) {
            button.classList.toggle('active', !!activeKey && button.getAttribute(attr) === activeKey);
        });
    }

    function setActivePanels(selector, attr, activeKey) {
        if (!selector || !attr) return;
        document.querySelectorAll(selector).forEach(function(panel) {
            panel.style.display = activeKey && panel.getAttribute(attr) === activeKey ? '' : 'none';
        });
    }

    function toggleContent(options) {
        options = options || {};
        var key = options.key;
        var host = resolveElement(options.host);
        var getActiveKey = typeof options.getActiveKey === 'function'
            ? options.getActiveKey
            : function() { return options.activeKey || null; };
        var setActiveKey = typeof options.setActiveKey === 'function'
            ? options.setActiveKey
            : function() {};
        var activeKey = getActiveKey();
        var shouldClose = activeKey === key && visible(host);

        if (shouldClose) {
            setActiveKey(null);
            if (host) host.style.display = 'none';
            setActiveButtons(options.buttonSelector, options.buttonKeyAttribute, null);
            setActivePanels(options.panelSelector, options.panelKeyAttribute, null);
            if (typeof options.onClose === 'function') options.onClose(key);
            return { opened: false, key: null };
        }

        if (typeof options.beforeOpen === 'function') options.beforeOpen(key);
        setActiveKey(key || null);
        if (host) host.style.display = key ? '' : 'none';
        setActiveButtons(options.buttonSelector, options.buttonKeyAttribute, key || null);
        setActivePanels(options.panelSelector, options.panelKeyAttribute, key || null);
        if (typeof options.onOpen === 'function') options.onOpen(key);
        return { opened: !!key, key: key || null };
    }

    // 选择器（"+ 设置"）：统一 manifest + store + ChipRenderer 一条路径，无 fallback。
    function renderChooser(options) {
        options = options || {};
        var host = resolveElement(options.host);
        if (!host) return;
        host.innerHTML = '';
        if (!options.manifest || !options.store || !window.ChipRenderer) return;
        _renderChooserChips(host, options);
    }

    function _renderChooserChips(host, options) {
        var manifest = options.manifest;
        var store = options.store;
        var defaults = manifest.defaults || {};
        var tabs = Array.isArray(options.tabs) ? options.tabs : [];
        var mountedTabs = Array.isArray(options.mountedTabs) ? options.mountedTabs : [];
        var isVisible = typeof options.isVisible === 'function' ? options.isVisible : function() { return true; };
        var onToggle = typeof options.onToggle === 'function' ? options.onToggle : function() {};
        var shouldShow = typeof options.shouldShow === 'function' ? options.shouldShow : null;
        var escapeHTML = options.escapeHTML;
        var renderChipHtml = options.renderChipHtml;

        var introText = options.introText || '选择要挂载的设置。未挂载项继续使用默认值。';
        if (introText) {
            var intro = document.createElement('div');
            intro.className = options.introClassName || 'backend-settings-chooser-intro';
            intro.textContent = introText;
            host.appendChild(intro);
        }

        tabs.filter(isVisible).forEach(function(tab) {
            // 收集该 tab 下有 chip_template 的 setting key
            var tabSettingKeys = Object.keys(defaults).filter(function(key) {
                var def = defaults[key] || {};
                return (def.tab_key || def.tab) === tab.key && def.chip_template;
            });
            tabSettingKeys = sortSettingKeysByDisplayOrder(tabSettingKeys, defaults);

            var row = document.createElement('label');
            row.className = options.rowClassName || 'backend-settings-chooser-row';
            var input = document.createElement('input');
            input.type = 'checkbox';
            input.checked = mountedTabs.indexOf(tab.key) >= 0;
            input.addEventListener('change', function() { onToggle(tab, input.checked); });
            var body = document.createElement('div');
            body.className = options.bodyClassName || 'backend-settings-chooser-body';
            var title = document.createElement('div');
            title.className = options.titleClassName || 'backend-settings-chooser-title';
            title.textContent = tab.label || tab.key;
            var defaultsHost = document.createElement('div');
            defaultsHost.className = options.defaultsClassName || 'backend-settings-chooser-defaults';
            body.appendChild(title);
            body.appendChild(defaultsHost);
            row.appendChild(input);
            row.appendChild(body);
            host.appendChild(row);

            // 用 ChipRenderer 渲染该 tab 的 chip 行。
            // 不传 onOpen → chip 默认行为：按 info_overlay 打开信息 overlay。
            window.ChipRenderer.render(defaultsHost, {
                manifest: manifest,
                store: store,
                settingKeys: tabSettingKeys,
                includeHidden: true,
                notApplicableLabel: options.notApplicableLabel || 'N/A',
                shouldShow: shouldShow,
                escapeHTML: escapeHTML,
                renderChipHtml: renderChipHtml,
            });
        });
    }

    function matchesConditions(conditions, values) {
        conditions = conditions || {};
        values = values || {};
        return Object.keys(conditions).every(function(key) {
            var allowed = conditions[key];
            if (!Array.isArray(allowed)) allowed = [allowed];
            return allowed.map(String).indexOf(String(values[key])) >= 0;
        });
    }

    function settingVisibleForValues(setting, values) {
        return matchesConditions((setting && setting.rules && setting.rules.visible_if) || {}, values);
    }

    function settingEditableForValues(setting, values) {
        return matchesConditions((setting && setting.rules && setting.rules.editable_if) || {}, values);
    }

    function defaultValueForValues(setting, values) {
        setting = setting || {};
        values = values || {};
        var conditional = setting.rules && setting.rules.default_if || {};
        var keys = Object.keys(conditional);
        for (var i = 0; i < keys.length; i++) {
            var sourceKey = keys[i];
            var mapping = conditional[sourceKey] || {};
            var sourceValue = values[sourceKey];
            if (Object.prototype.hasOwnProperty.call(mapping, sourceValue)) {
                return mapping[sourceValue];
            }
            var stringValue = String(sourceValue);
            if (Object.prototype.hasOwnProperty.call(mapping, stringValue)) {
                return mapping[stringValue];
            }
        }
        return setting.value;
    }

    function settingDisplayOrder(setting) {
        var order = setting && setting.serialization && setting.serialization.display_order;
        if (order != null) return Number(order);
        if (setting && setting.order != null) return Number(setting.order);
        return null;
    }

    function sortSettingKeysByDisplayOrder(keys, defaults) {
        defaults = defaults || {};
        return (Array.isArray(keys) ? keys.slice() : []).sort(function(a, b) {
            var ao = settingDisplayOrder(defaults[a]);
            var bo = settingDisplayOrder(defaults[b]);
            if (ao == null && bo == null) return 0;
            if (ao == null) return 1;
            if (bo == null) return -1;
            return ao - bo;
        });
    }

    function sortTabsByOrder(tabKeys, tabs) {
        var tabMap = {};
        (Array.isArray(tabs) ? tabs : []).forEach(function(tab) {
            if (tab && tab.key) tabMap[tab.key] = tab;
        });
        return (Array.isArray(tabKeys) ? tabKeys.slice() : []).sort(function(a, b) {
            var ao = tabMap[a] && tabMap[a].order;
            var bo = tabMap[b] && tabMap[b].order;
            if (ao == null && bo == null) return 0;
            if (ao == null) return 1;
            if (bo == null) return -1;
            return Number(ao) - Number(bo);
        });
    }

    function customProductFieldMeta(setting, fieldKey) {
        var fields = setting && setting.serialization && setting.serialization.fields || [];
        for (var i = 0; i < fields.length; i++) {
            if (String(fields[i].value) === String(fieldKey)) return fields[i];
        }
        return null;
    }

    function customProductFieldLabel(setting, fieldKey) {
        var meta = customProductFieldMeta(setting, fieldKey);
        return meta ? String(meta.label || meta.value || fieldKey || '') : String(fieldKey || '');
    }

    function displaySettingValue(setting, value) {
        var serializationKind = setting && setting.serialization && setting.serialization.kind;
        var descriptor = setting && setting.value_descriptor || {};
        if (Array.isArray(descriptor.options)) {
            for (var i = 0; i < descriptor.options.length; i++) {
                if (String(descriptor.options[i].value) === String(value)) return descriptor.options[i].label;
            }
        }
        if (value === undefined || value === null || value === '') {
            if (serializationKind === 'product_path_selection') return '无';
            return '无';
        }
        if (serializationKind === 'product_path_candidate_list'
            || serializationKind === 'factor_candidate_list'
            || serializationKind === 'category_candidate_list') {
            return (Array.isArray(value) ? value.length : 0) + '项';
        }
        if (serializationKind === 'custom_product_overrides') {
            var rows = Array.isArray(value) ? value : [];
            var filter = setting && setting.serialization && setting.serialization.module_filter;
            if (filter) {
                var fields = (setting.serialization && setting.serialization.fields) || [];
                var modulesByField = {};
                fields.forEach(function(item) {
                    modulesByField[String(item.value)] = String(item.module || '');
                });
                rows = rows.filter(function(row) {
                    return modulesByField[String(row && row.field)] === String(filter);
                });
            }
            return rows.length + '项';
        }
        // 多选列表（复数 selections）：显示已选个数。
        if (serializationKind === 'product_path_selection_list'
            || serializationKind === 'factor_selection_list') {
            return (Array.isArray(value) ? value.length : 0) + ' 个已选';
        }
        if (serializationKind === 'product_path_selection' && value && typeof value === 'object') {
            var pps = window.ProductPathSelectionUtils;
            if (pps && typeof pps.selectionDisplayLabel === 'function') return pps.selectionDisplayLabel(value);
        }
        if (serializationKind === 'factor_selection' && value && typeof value === 'object') {
            var labelKeys = setting && setting.serialization && setting.serialization.label_keys || ['alias', 'name', 'label'];
            for (var j = 0; j < labelKeys.length; j++) {
                var label = value[labelKeys[j]];
                if (label !== undefined && label !== null && label !== '') return String(label);
            }
        }
        if (serializationKind === 'factor_role_bindings'
            && window.FactorRoleBindingsControl) {
            return window.FactorRoleBindingsControl.displayValue(value);
        }
        if (Array.isArray(value)) return '未注册显示格式';
        if (value && typeof value === 'object') {
            return '未注册显示格式';
        }
        var template = descriptor.editor;
        if (!template || template === 'custom') {
            // 标量值（string/number/boolean）直接显示；custom 控件只是编辑方式，
            // 值本身（如模板名）仍应能作为 chip 展示。
            if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
                return String(value);
            }
            return '未注册显示格式';
        }
        return String(value);
    }

    window.BackendSettingsPanel = {
        toggleMountedTab: toggleMountedTab,
        toggleContent: toggleContent,
        renderChooser: renderChooser,
        matchesConditions: matchesConditions,
        settingVisibleForValues: settingVisibleForValues,
        settingEditableForValues: settingEditableForValues,
        defaultValueForValues: defaultValueForValues,
        settingDisplayOrder: settingDisplayOrder,
        sortSettingKeysByDisplayOrder: sortSettingKeysByDisplayOrder,
        sortTabsByOrder: sortTabsByOrder,
        displaySettingValue: displaySettingValue,
        customProductFieldMeta: customProductFieldMeta,
        customProductFieldLabel: customProductFieldLabel,
    };
})();
