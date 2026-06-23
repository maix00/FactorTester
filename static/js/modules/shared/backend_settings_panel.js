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

    window.BackendSettingsPanel = {
        toggleMountedTab: toggleMountedTab,
        toggleContent: toggleContent,
    };
})();
