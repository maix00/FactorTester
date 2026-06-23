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

    window.BackendSettingsPanel = {
        toggleMountedTab: toggleMountedTab,
    };
})();
