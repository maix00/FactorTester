/**
 * registry/group-settings.js — Config panel 注册层
 *
 * 职责：
 *   - config panel 注册（声明哪个 panel 管理哪些字段）
 *   - commitDirty() 只收集已注册字段，委托 core/group-settings 执行
 *
 * 依赖：
 *   - core/group-settings.js (GT.groupSettings)  — 底层 state + dirty store + cache
 *   - registry/chips.js 之后的 chips bridge
 *
 * 挂载到 window.GT_CONFIG_REGISTRY
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    var GS = GT.groupSettings;
    if (!GS) throw new Error('core/group-settings must be loaded before registry/group-settings');

    // ---------------------------------------------------------------------------
    // Registry state
    // ---------------------------------------------------------------------------

    var _configs = [];

    /**
     * Fields registered by config panels via def.fields.
     * ONLY fields in this list are collected on commitDirty().
     *
     * TO ADD A NEW CONFIG FIELD (agent / human):
     *   1. Add the field to _state in core/group-settings.js.
     *   2. Register it via register({ fields: ['...'] }) in the config panel.
     *   3. Use REG.setDirty / REG.getDirty in the panel's UI.
     */
    var _registeredFields = [];

    // ---------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------

    function register(def, containerId) {
        if (!def || !def.name || !def.panel) {
            GT.log('registry/group-settings: invalid config registration, skipping');
            return;
        }
        if (Array.isArray(def.fields)) {
            for (var fi = 0; fi < def.fields.length; fi++) {
                var fk = def.fields[fi];
                if (fk && _registeredFields.indexOf(fk) === -1) {
                    _registeredFields.push(fk);
                }
            }
        }
        for (var i = 0; i < _configs.length; i++) {
            if (_configs[i].name === def.name) {
                GT.log('registry/group-settings: duplicate config name "' + def.name + '", overwriting');
                _configs[i] = def;
                _bridgeConfigToChipProvider(def);
                return;
            }
        }
        def.containerId = containerId || ('gt-config-' + def.name);
        _configs.push(def);
        _bridgeConfigToChipProvider(def);
    }

    function _bridgeConfigToChipProvider(def) {
        var REG = window.GT_CONFIG_REGISTRY;
        if (REG && typeof REG._bridgeConfigToChipProvider === 'function') {
            REG._bridgeConfigToChipProvider(def);
        }
    }

    function getAll() { return _configs.slice(); }

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

    function getChips(group) {
        if (!group) return [];
        var chips = [];
        var seen = {};
        for (var i = 0; i < _configs.length; i++) {
            var panel = _configs[i].panel;
            if (panel && typeof panel.getChips === 'function') {
                var panelChips = panel.getChips(group);
                if (panelChips && panelChips.length) {
                    for (var j = 0; j < panelChips.length; j++) {
                        var c = panelChips[j];
                        if (c && c.label && !seen[c.label]) {
                            seen[c.label] = true;
                            chips.push(c);
                        }
                    }
                }
            }
        }
        return chips;
    }

    // ---------------------------------------------------------------------------
    // Dirty workspace — delegates to core/group-settings
    // ---------------------------------------------------------------------------

    function setDirty(key, value) {
        GS.setDirty(key, value);
        if (GT.tabs && typeof GT.tabs.renderTabActions === 'function') {
            GT.tabs.renderTabActions();
        }
    }

    function getDirty(key, fallback) {
        var v = GS.getDirty(key);
        return v !== undefined ? v : fallback;
    }

    function hasDirty() { return GS.isDirty(); }

    function rollbackDirty() {
        GS.clearDirty();
        if (GT.tabs && typeof GT.tabs.renderTabActions === 'function') {
            GT.tabs.renderTabActions();
        }
    }

    function commitDirty() {
        if (!GS.isDirty()) return false;
        var patch = {};
        var hasRegistered = false;
        for (var i = 0; i < _registeredFields.length; i++) {
            var key = _registeredFields[i];
            if (GS.isDirty(key)) {
                patch[key] = GS.getDirty(key);
                hasRegistered = true;
            }
        }
        if (!hasRegistered) { GS.clearDirty(); return false; }
        savePatch(patch);
        GS.clearDirty();
        if (GT.tabs && typeof GT.tabs.renderTabActions === 'function') {
            GT.tabs.renderTabActions();
        }
        if (GT.events && typeof GT.events.emit === 'function') {
            GT.events.emit('groupsChanged');
        }
        return true;
    }

    // ---------------------------------------------------------------------------
    // Group reference helpers
    // ---------------------------------------------------------------------------

    function getEditGroupIds(sel) {
        if (!sel) return [];
        if (Array.isArray(sel.groupIds)) return sel.groupIds;
        if (Array.isArray(sel)) return sel;
        if (typeof sel === 'object') {
            return Object.keys(sel).filter(function(k) { return sel[k]; });
        }
        return [];
    }

    function getReferenceGroup() {
        var mode = GT.tabs && GT.tabs.getPanelMode ? GT.tabs.getPanelMode() : 'list';

        if (mode === 'add') {
            var draft = GT.tabs && GT.tabs.getAddDraft ? GT.tabs.getAddDraft() : null;
            if (!draft) return null;
            return {
                id: '_add_draft',
                testerId: draft.testerId,
                feeMode: draft.feeMode || 'none',
                feeRate: draft.feeRate,
                feeMap: draft.feeMap,
                feeSensitivity: draft.feeSensitivity,
                rebalanceMode: draft.rebalanceMode,
                liquidityMode: draft.liquidityMode || 'infinite',
                liquidityPercent: draft.liquidityPercent !== undefined ? draft.liquidityPercent : 100,
                useCloseToday: draft.useCloseToday || false,
            };
        }

        if (mode === 'edit') {
            var sel = GT.tabs && GT.tabs.getEditSelection ? GT.tabs.getEditSelection() : null;
            var ids = getEditGroupIds(sel);
            if (ids.length === 0) return null;
            if (!GS.groups) return null;
            return GS.groups.get(ids[0]);
        }

        var id = _getActiveGroupId();
        if (!id) return null;
        if (!GS.groups) return null;
        var g = GS.groups.get(id);
        if (!g) return null;
        return g;
    }

    function savePatch(patch) {
        var mode = GT.tabs && GT.tabs.getPanelMode ? GT.tabs.getPanelMode() : 'list';
        if (mode === 'add') {
            if (GT.tabs && typeof GT.tabs.updateAddDraft === 'function') GT.tabs.updateAddDraft(patch);
            return;
        }
        if (mode === 'edit') {
            var sel = GT.tabs && GT.tabs.getEditSelection ? GT.tabs.getEditSelection() : null;
            var ids = getEditGroupIds(sel);
            for (var i = 0; i < ids.length; i++) {
                try { GS.groups.update(ids[i], patch); } catch (err) {}
            }
            return;
        }
        var id = _getActiveGroupId();
        if (!id) return;
        try { GS.groups.update(id, patch); } catch (err) { alert('保存失败: ' + err.message); }
    }

    function _getActiveGroupId() {
        var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
        return sel ? sel.getFirst() : null;
    }

    // ---------------------------------------------------------------------------
    // Export
    // ---------------------------------------------------------------------------

    window.GT_CONFIG_REGISTRY = {
        register: register,
        getAll: getAll,
        getTableColumns: getTableColumns,
        toPanelEntry: toPanelEntry,
        getChips: getChips,
        getEditGroupIds: getEditGroupIds,
        getReferenceGroup: getReferenceGroup,
        savePatch: savePatch,
        setDirty: setDirty,
        getDirty: getDirty,
        hasDirty: hasDirty,
        rollbackDirty: rollbackDirty,
        commitDirty: commitDirty,
    };

    GT.log('registry/group-settings loaded');
})();
