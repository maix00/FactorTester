/**
 * panels/config/derived-addon.js — 派生组功能注册（addon）
 *
 * 向 GT.modes 注册：
 *   - 'derived' addFlow（条件：选中 isDerived 组；草稿构建；提交逻辑）
 *   - edit action：「🌳 创建派生组」
 *
 * 向 GT.tabs 注册：
 *   - 'config-derived' 面板（品种筛选）
 *
 * 依赖：
 *   - GT.modes     — 必须在 modes.js 之后加载
 *   - GT.tabs      — 必须在 tabs.js 之后加载
 *   - GT.groupSettings.groups
 *   - GT.panels.config.derived — 品种筛选面板 (derived.js) 必须在先
 *
 * 加载顺序：modes.js → tabs.js → panels/config/derived.js → derived-addon.js
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) return;

    var M = GT.modes;
    if (!M) { console.warn('[derived-addon] modes not loaded yet'); return; }

    var T = GT.tabs;
    if (!T) { console.warn('[derived-addon] tabs not loaded yet'); return; }

    // =========================================================================
    // Helpers
    // =========================================================================

    function _getGroup(id) {
        return GT.groupSettings.groups ? GT.groupSettings.groups.get(id) : null;
    }

    function _inheritedConfigKeys() {
        var keys = {};
        ['feeMode', 'feeRate', 'feeMap', 'feeSensitivity', 'useCloseToday',
         'rebalanceMode', 'liquidityMode', 'liquidityPercent'].forEach(function(k) { keys[k] = true; });
        return keys;
    }

    // =========================================================================
    // Build derived draft from edit selection
    // =========================================================================

    function _buildDerivedAddDraft(ctx) {
        var ids = (ctx && ctx.ids) ? ctx.ids : [];
        if (ids.length !== 1) return { addFlow: 'derived' };

        var selected = _getGroup(ids[0]);
        if (!selected) return { addFlow: 'derived' };

        var draft = { addFlow: 'derived' };

        if (selected.isDerived) {
            draft.preselectedParentDerivedId = selected.id;
            draft.preselectedBaseGroupId = selected.baseGroupId;
            var parentMask = selected.productMask || {};
            var hasOwnMask = Object.keys(parentMask).length > 0;
            if (hasOwnMask) {
                draft.preselectedProducts = Object.keys(parentMask).filter(function(k) { return parentMask[k]; });
            }
        } else {
            draft.preselectedBaseGroupId = selected.id;
        }

        var cfg = M.resolveConfig(selected);
        if (cfg) Object.assign(draft, cfg);
        draft._inheritedConfigKeys = _inheritedConfigKeys();
        return draft;
    }

    // =========================================================================
    // Build derived draft from scratch (没有 edit selection 时)
    // =========================================================================

    function _buildDerivedDraftFromState(ctx) {
        var draft = { addFlow: 'derived' };
        var activeDerivedId = ctx.activeDerivedId || null;
        var activeBaseId = ctx.activeBaseId || null;

        if (activeDerivedId) {
            draft.preselectedParentDerivedId = activeDerivedId;
            var activeDerived = _getGroup(activeDerivedId);
            if (activeDerived) {
                draft.preselectedBaseGroupId = activeDerived.baseGroupId;
                if (activeDerived.productMask) {
                    draft.preselectedProducts = Object.keys(activeDerived.productMask).filter(function(k) { return activeDerived.productMask[k]; });
                }
                var cfg = M.resolveConfig(activeDerived);
                if (cfg) Object.assign(draft, cfg);
                draft._inheritedConfigKeys = _inheritedConfigKeys();
            }
        } else if (activeBaseId) {
            draft.preselectedBaseGroupId = activeBaseId;
            var activeBase = _getGroup(activeBaseId);
            if (activeBase) {
                var cfg2 = M.resolveConfig(activeBase);
                if (cfg2) Object.assign(draft, cfg2);
                draft._inheritedConfigKeys = _inheritedConfigKeys();
            }
        }
        return draft;
    }

    // =========================================================================
    // Submit derived group
    // =========================================================================

    function _submitDerived(draft, helpers) {
        if (!draft) { alert('提交草稿丢失'); return; }
        var baseGroupId = draft.preselectedBaseGroupId;
        var parentDerivedId = draft.preselectedParentDerivedId;

        if (!baseGroupId && !parentDerivedId) {
            alert('请先从列表中选择一个基础组或派生组作为上级');
            return;
        }
        if (!baseGroupId && parentDerivedId) {
            var pNode = _getGroup(parentDerivedId);
            if (pNode && pNode.isDerived) baseGroupId = pNode.baseGroupId;
            if (!baseGroupId) { alert('无法确定上级派生组关联的基础组'); return; }
        }

        var resolvedName = draft.name || draft.defaultName;
        if (!resolvedName || !resolvedName.trim()) {
            var bg = _getGroup(baseGroupId);
            resolvedName = (bg && (bg.shortAlias || bg.name)) || '派生组';
        }

        var derivedPanel = GT.panels && GT.panels.config && GT.panels.config.derived;
        var selectedProducts = (derivedPanel && typeof derivedPanel.getSelectedProducts === 'function')
            ? derivedPanel.getSelectedProducts() : [];
        var allProducts = (derivedPanel && typeof derivedPanel.getAllProducts === 'function')
            ? derivedPanel.getAllProducts() : [];
        var productMask = {};
        if (selectedProducts.length > 0 && selectedProducts.length < allProducts.length) {
            for (var i = 0; i < selectedProducts.length; i++) productMask[selectedProducts[i]] = true;
        }

        var config = {
            name: resolvedName,
            isDerived: true,
            baseGroupId: baseGroupId,
            productMask: productMask,
        };
        ['feeMode', 'feeRate', 'feeMap', 'feeSensitivity', 'useCloseToday',
         'rebalanceMode', 'liquidityMode', 'liquidityPercent'].forEach(function(key) {
            var inherited = draft._inheritedConfigKeys && draft._inheritedConfigKeys[key];
            if (!inherited && draft[key] !== undefined) config[key] = draft[key];
        });
        if (parentDerivedId) config.parentId = parentDerivedId;

        try {
            GT.groupSettings.groups.add(config);
        } catch (err) {
            alert('创建派生组失败: ' + (err && err.message || err));
            return;
        }

        if (parentDerivedId && GT.groupSettings.groups) {
            var parentNode = _getGroup(parentDerivedId);
            if (parentNode && parentNode._expanded === false) GT.groupSettings.groups.toggleExpanded(parentDerivedId);
        }

        helpers.exitAdd();
    }

    // =========================================================================
    // Register addFlow
    // =========================================================================

    M.registerAddFlow({
        flow: 'derived',
        priority: 10,  // 高于 base（0），低于未来的更高优先级 flow
        condition: function(ctx) {
            // 自动匹配：edit 时选中了 isDerived 组
            if (ctx && ctx.groups && ctx.groups.length >= 1) {
                for (var i = 0; i < ctx.groups.length; i++) {
                    if (ctx.groups[i].isDerived) return true;
                }
            }
            return false;
        },
        buildDraft: function(ctx) {
            // 如果有 edit selection（从 edit → derived），用 selection 构建
            if (ctx && ctx.ids && ctx.ids.length === 1) {
                return _buildDerivedAddDraft(ctx);
            }
            // 否则从 state 构建（list → add derived）
            return _buildDerivedDraftFromState(ctx);
        },
        onSubmit: _submitDerived,
        submitLabel: '创建派生组',
        defaultTab: 'config-derived'
    });

    // =========================================================================
    // Register edit action：「🌳 创建派生组」
    // =========================================================================

    M.registerEditAction({
        name: 'create-derived',
        label: '🌳 创建派生组',
        priority: 10,
        condition: function(ctx) {
            return ctx && ctx.count === 1;
        },
        action: function(ctx, helpers) {
            if (!ctx || ctx.ids.length !== 1) { alert('请选择 1 行来创建派生组'); return; }
            var draft = _buildDerivedAddDraft(ctx);
            if (!draft.preselectedBaseGroupId && !draft.preselectedParentDerivedId) {
                alert('无法识别选中的分组类型');
                return;
            }
            helpers.exitEdit();
            // 进入 add/derived 并设置 draft
            M.enterAdd('derived');
            M.setAddDraft(draft);
            helpers.mountTab('config-derived');
            helpers.renderActions();
        },
        standalone: false
    });

    // =========================================================================
    // Register panel: config-derived
    // =========================================================================

    T.registerPanel({
        name: 'config-derived',
        label: '品种筛选',
        containerId: 'config-derived',
        category: 3, // CONFIG
        panel: GT.panels && GT.panels.config ? GT.panels.config.derived : null,
        visible: function() {
            // add/derived 时显示
            if (M.isAddFlow('derived')) return true;
            // edit 时，如果选中的组中有 isDerived 则显示
            if (M.isMode('edit')) {
                var selIds = M.getEditIds();
                return selIds.some(function(sid) {
                    var g = _getGroup(sid);
                    return g && g.isDerived;
                });
            }
            return false;
        },
        onBeforeMount: function() {
            if (M.isMode('edit')) {
                // 用 edit selection 构建 derived draft
                var ctx = M.getEditContext();
                if (ctx && ctx.ids && ctx.ids.length === 1) {
                    M.setAddDraft(_buildDerivedAddDraft(ctx));
                }
            }
        }
    });

    GT.log('panels/config/derived-addon loaded');
})();
