/**
 * panels/add/derived.js — 派生组 addFlow + editAction
 *
 * - addFlow: 'derived' — 新建派生组（无 defaultTab，config tabs 自动展示）
 * - editAction: 'create-derived' — 从选中行创建派生组
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.add) { GT.panels.add = {}; }

    var M = GT.modes;
    var TABS = GT.tabs;

    function _getGroup(id) {
        return GT.groupSettings.groups ? GT.groupSettings.groups.get(id) : null;
    }

    function _inheritedConfigKeys() {
        var keys = {};
        ['feeMode', 'feeRate', 'feeMap', 'feeSensitivity', 'useCloseToday',
         'rebalanceMode', 'liquidityMode', 'liquidityPercent'].forEach(function(k) { keys[k] = true; });
        return keys;
    }

    function _buildDerivedAddDraft(ctx) {
        var ids = (ctx && ctx.ids) ? ctx.ids : [];
        if (ids.length !== 1) return { addFlow: 'derived' };
        var selected = _getGroup(ids[0]);
        if (!selected) return { addFlow: 'derived' };
        var draft = { addFlow: 'derived' };
        draft.preselectedParentId = selected.id;
        draft.preselectedParentLabel = selected.name || selected.shortAlias || selected.id;
        if (selected.productMask) {
            var parentMask = selected.productMask || {};
            var hasOwnMask = Object.keys(parentMask).length > 0;
            if (hasOwnMask) {
                draft.preselectedProducts = Object.keys(parentMask).filter(function(k) { return parentMask[k]; });
            }
        }
        var cfg = M.resolveConfig(selected);
        if (cfg) Object.assign(draft, cfg);
        draft._inheritedConfigKeys = _inheritedConfigKeys();
        return draft;
    }

    function _buildDerivedDraftFromState(ctx) {
        var draft = { addFlow: 'derived' };
        var activeId = ctx.activeDerivedId || ctx.activeBaseId || null;
        if (activeId) {
            draft.preselectedParentId = activeId;
            var active = _getGroup(activeId);
            if (active) {
                draft.preselectedParentLabel = active.name || active.shortAlias || active.id;
                if (active.productMask) {
                    draft.preselectedProducts = Object.keys(active.productMask).filter(function(k) { return active.productMask[k]; });
                }
                var cfg = M.resolveConfig(active);
                if (cfg) Object.assign(draft, cfg);
                draft._inheritedConfigKeys = _inheritedConfigKeys();
            }
        }
        return draft;
    }

    function _submitDerived(draft, helpers) {
        if (!draft) { alert('提交草稿丢失'); return; }
        var parentId = draft.preselectedParentId;
        if (!parentId) {
            alert('请先从列表中选择一个分组或派生组作为上级');
            return;
        }
        var parentNode = _getGroup(parentId);
        var resolvedName = draft.name || draft.defaultName;
        if (!resolvedName || !resolvedName.trim()) {
            resolvedName = (parentNode && (parentNode.shortAlias || parentNode.name)) || '派生组';
        }
        var siftPanel = GT.panels.config.productSift;
        var selectedProducts = (siftPanel && typeof siftPanel.getSelectedProducts === 'function')
            ? siftPanel.getSelectedProducts() : [];
        var allProducts = (siftPanel && typeof siftPanel.getAllProducts === 'function')
            ? siftPanel.getAllProducts() : [];
        var productMask = {};
        if (selectedProducts.length > 0 && selectedProducts.length < allProducts.length) {
            for (var i = 0; i < selectedProducts.length; i++) productMask[selectedProducts[i]] = true;
        }
        var config = {
            name: resolvedName,
            parentId: parentId,
            productMask: productMask,
        };
        ['feeMode', 'feeRate', 'feeMap', 'feeSensitivity', 'useCloseToday',
         'rebalanceMode', 'liquidityMode', 'liquidityPercent'].forEach(function(key) {
            var inherited = draft._inheritedConfigKeys && draft._inheritedConfigKeys[key];
            if (!inherited && draft[key] !== undefined) config[key] = draft[key];
        });
        try {
            GT.groupSettings.groups.add(config);
        } catch (err) {
            alert('创建派生组失败: ' + (err && err.message || err));
            return;
        }
        if (parentNode && parentNode._expanded === false && GT.groupSettings.groups) {
            GT.groupSettings.groups.toggleExpanded(parentId);
        }
        helpers.exitAdd();
    }

    if (M && TABS) {
        M.registerAddFlow({
            flow: 'derived',
            priority: 10,
            defaultTab: 'config-product-sift',
            condition: function(ctx) {
                if (ctx && ctx.groups && ctx.groups.length >= 1) {
                    for (var i = 0; i < ctx.groups.length; i++) {
                        if (ctx.groups[i].parentId) return true;
                    }
                }
                return false;
            },
            buildDraft: function(ctx) {
                if (ctx && ctx.ids && ctx.ids.length === 1) {
                    return _buildDerivedAddDraft(ctx);
                }
                return _buildDerivedDraftFromState(ctx);
            },
            onSubmit: _submitDerived,
            submitLabel: '创建派生组'
        });

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
                if (!draft.preselectedParentId) {
                    alert('无法识别选中的分组类型');
                    return;
                }
                helpers.exitEdit();
                M.enterAdd('derived');
                M.setAddDraft(draft);
                helpers.mountTab('config-product-sift');
                helpers.renderActions();
            },
            standalone: true
        });

        M.registerEditAction({
            name: 'create-child',
            label: '＋ 新增子组',
            priority: 15,
            condition: function(ctx) {
                return ctx && ctx.count >= 1;
            },
            action: function(ctx, helpers) {
                if (!ctx || ctx.ids.length === 0) { alert('请至少选择 1 行'); return; }
                // Use first selected as parent
                var draft = _buildDerivedAddDraft(ctx);
                if (!draft.preselectedParentId) {
                    alert('无法识别选中的分组类型');
                    return;
                }
                helpers.exitEdit();
                M.enterAdd('derived');
                M.setAddDraft(draft);
                helpers.mountTab('config-product-sift');
                helpers.renderActions();
            },
            standalone: true
        });
    }

    GT.log('panels/add/derived loaded');
})();
