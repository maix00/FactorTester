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
    // Shared helpers for config panels
    // ---------------------------------------------------------------------------

    /**
     * Extract group IDs from edit selection.
     * Supports multiple formats:
     *   - {groupIds: ['id1','id2']}  (wrapper object)
     *   - ['id1','id2']              (plain array)
     *   - {id1: true, id2: true}     (truthy-key object, from list panel _selectedIds)
     *
     * @param {*} sel — edit selection value from GT.ui.getEditSelection()
     * @returns {string[]}
     */
    function getEditGroupIds(sel) {
        if (!sel) return [];
        if (Array.isArray(sel.groupIds)) return sel.groupIds;
        if (Array.isArray(sel)) return sel;
        if (typeof sel === 'object') {
            return Object.keys(sel).filter(function(k) { return sel[k]; });
        }
        return [];
    }

    /**
     * Determine the reference group for a config panel to display settings from.
     * In edit mode: uses the first selected group.
     * In list mode: uses the active base group from state.
     * In add mode: returns the draft object (or null).
     *
     * @returns {object|null} — base group record from datamodel, or a synthetic draft object
     */
    function getReferenceGroup() {
        var GT = window.GroupTest;
        var mode = GT.ui && GT.ui.getPanelMode ? GT.ui.getPanelMode() : 'list';

        if (mode === 'add') {
            var draft = GT.ui && GT.ui.getAddDraft ? GT.ui.getAddDraft() : null;
            if (!draft) return null;
            return {
                id: '_add_draft',
                feeMode: draft.feeMode || 'none',
                feeRate: draft.feeRate,
                feeMap: draft.feeMap,
                feeSensitivity: draft.feeSensitivity,
                rebalanceMode: draft.rebalanceMode,
                useCloseToday: draft.useCloseToday || false,
            };
        }

        if (mode === 'edit') {
            var sel = GT.ui && GT.ui.getEditSelection ? GT.ui.getEditSelection() : null;
            var ids = getEditGroupIds(sel);
            if (ids.length === 0) return null;
            if (!GT.datamodel || !GT.datamodel.base_groups) return null;
            return GT.datamodel.base_groups.get(ids[0]);
        }

        // list mode
        var id = GT.state && GT.state.getActiveBaseGroupId ? GT.state.getActiveBaseGroupId() : null;
        if (!id) return null;
        if (!GT.datamodel || !GT.datamodel.base_groups) return null;
        return GT.datamodel.base_groups.get(id);
    }

    /**
     * Apply a patch to all selected groups in edit mode, or to the active group in list mode.
     * In add mode, saves to the add draft.
     *
     * @param {object} patch — key/value pairs to save
     */
    function savePatch(patch) {
        var GT = window.GroupTest;
        var mode = GT.ui && GT.ui.getPanelMode ? GT.ui.getPanelMode() : 'list';

        if (mode === 'add') {
            if (GT.ui && typeof GT.ui.updateAddDraft === 'function') {
                GT.ui.updateAddDraft(patch);
            }
            return;
        }

        if (mode === 'edit') {
            var sel = GT.ui && GT.ui.getEditSelection ? GT.ui.getEditSelection() : null;
            var ids = getEditGroupIds(sel);
            for (var i = 0; i < ids.length; i++) {
                try {
                    GT.datamodel.base_groups.update(ids[i], patch);
                } catch (err) { /* skip individual failures */ }
            }
            return;
        }

        // list mode
        var id = GT.state && GT.state.getActiveBaseGroupId ? GT.state.getActiveBaseGroupId() : null;
        if (!id) return;
        try {
            GT.datamodel.base_groups.update(id, patch);
        } catch (err) {
            alert('保存失败: ' + err.message);
        }
    }

    // ---------------------------------------------------------------------------
    // Export
    // ---------------------------------------------------------------------------

    window.GT_CONFIG_REGISTRY = {
        register: register,
        getAll: getAll,
        getTableColumns: getTableColumns,
        toPanelEntry: toPanelEntry,
        // shared helpers
        getEditGroupIds: getEditGroupIds,
        getReferenceGroup: getReferenceGroup,
        savePatch: savePatch,
    };

    GT.log('panels/config/registry loaded');
})();
