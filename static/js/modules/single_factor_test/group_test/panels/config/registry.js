/**
 * panels/config/registry.js — Category-3 config panel registry
 *
 * Pluggable config panels that:
 *   (a) can be mounted as sub-tabs in add/edit modes for any main tab
 *   (b) contribute columns to category-1 list tables
 *
 * Each config panel module registers itself via:
 *   GT_CONFIG_REGISTRY.register({ name, label, mount, unmount, refresh, render, getTableColumns })
 *
 * getTableColumns() → [{ key, label, width, render(group) }]
 *   - key:    unique column key
 *   - label:  column header text
 *   - width:  optional CSS width (e.g. "80px")
 *   - render: function(group) → HTML string
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    // ---------------------------------------------------------------------------
    // Registry state
    // ---------------------------------------------------------------------------

    var _configs = [];  // [{ name, label, panel, containerId, ... }]

    // ---------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------

    /**
     * Register a config panel.
     * @param {object} def — { name, label, panel: { mount, unmount, refresh, render, getTableColumns } }
     * @param {string} [containerId] — optional HTML container ID; defaults to 'gt-config-{name}'
     */
    function register(def, containerId) {
        if (!def || !def.name || !def.panel) {
            GT.log('config/registry: invalid config registration, skipping');
            return;
        }
        // Deduplicate by name
        for (var i = 0; i < _configs.length; i++) {
            if (_configs[i].name === def.name) {
                GT.log('config/registry: duplicate config name "' + def.name + '", overwriting');
                _configs[i] = def;
                return;
            }
        }
        def.containerId = containerId || ('gt-config-' + def.name);
        _configs.push(def);
    }

    /** Get all registered config panels */
    function getAll() {
        return _configs.slice();
    }

    /**
     * Get aggregated table columns from all registered configs.
     * @returns {{ key, label, width, render }[]}
     */
    function getTableColumns() {
        var cols = [];
        var seenKeys = {};
        for (var i = 0; i < _configs.length; i++) {
            var panel = _configs[i].panel;
            if (panel && typeof panel.getTableColumns === 'function') {
                var defCols = panel.getTableColumns();
                if (defCols && defCols.length) {
                    for (var j = 0; j < defCols.length; j++) {
                        var col = defCols[j];
                        if (col && col.key && !seenKeys[col.key]) {
                            seenKeys[col.key] = true;
                            cols.push(col);
                        }
                    }
                }
            }
        }
        return cols;
    }

    /**
     * Create a sub-tab panel entry suitable for GT_PANEL_REGISTRY.
     * @param {string} name — config name (e.g. 'fee')
     * @param {string} label — sub-tab button label
     * @param {string} containerId — HTML container id
     * @returns {object|null} — { name, label, containerId, category, panel }
     */
    function toPanelEntry(name, label, containerId) {
        var cfg = null;
        for (var i = 0; i < _configs.length; i++) {
            if (_configs[i].name === name) { cfg = _configs[i]; break; }
        }
        if (!cfg) return null;
        return {
            name: cfg.name,
            label: label || cfg.label,
            containerId: containerId || cfg.containerId,
            category: GT_SUBTAB_CATEGORY ? GT_SUBTAB_CATEGORY.CONFIG : 3,
            panel: cfg.panel,
        };
    }

    // ---------------------------------------------------------------------------
    // Export
    // ---------------------------------------------------------------------------

    window.GT_CONFIG_REGISTRY = {
        register: register,
        getAll: getAll,
        getTableColumns: getTableColumns,
        toPanelEntry: toPanelEntry,
    };

    GT.log('panels/config/registry loaded');
})();
