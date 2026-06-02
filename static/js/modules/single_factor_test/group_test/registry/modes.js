/**
 * registry/modes.js — UI 模式管理（纯状态机 + 注册机制）
 *
 * 职责：
 *   - 管理当前模式：'list' | 'add' | 'edit'
 *   - 管理 addDraft（新建草稿）
 *   - 管理 editSelection（编辑选中项）
 *   - 注册机制：外部通过 registerAddFlow / registerEditAction 注入行为
 *
 * 设计原则：
 *   - modes 不硬编码任何具体 addFlow（如 base/derived/ls）
 *   - 所有具体行为通过注册回调注入
 *   - enterAdd(flow?) 如不传 flow，按注册 priority 降序匹配条件
 *
 * 依赖：
 *   - GT.groupSettings.groups  — 分组数据（用于 resolveConfig）
 *
 * 挂载到 GT.modes
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    // ---------------------------------------------------------------------------
    // Internal state
    // ---------------------------------------------------------------------------

    var _panelMode = 'list';   // 'list' | 'add' | 'edit'
    var _addDraft = null;      // 新建草稿
    var _editSelection = null; // 编辑模式下的选中项
    var _activeFlowMeta = null;// 当前匹配到的 addFlow 注册项 {flow, priority, ...}

    // 注册表
    var _addFlowRegistry = [];    // [{flow, priority, condition, buildDraft, onSubmit, defaultTab}]
    var _editActionRegistry = []; // [{name, label, priority, condition, action, standalone, buttonClass}]

    // ---------------------------------------------------------------------------
    // Config resolution helper（泛型，不硬编码 derived）
    // ---------------------------------------------------------------------------

    function _resolvedConfigForDraft(group) {
        var base = null;
        if (group && group.baseGroupId && GT.groupSettings.groups) {
            base = GT.groupSettings.groups.get(group.baseGroupId);
        }
        return {
            feeMode: group && group.feeMode != null ? group.feeMode : (base && base.feeMode != null ? base.feeMode : 'none'),
            feeRate: group && group.feeRate != null ? group.feeRate : (base ? base.feeRate : null),
            feeMap: group && group.feeMap != null ? group.feeMap : (base ? base.feeMap : null),
            feeSensitivity: group && group.feeSensitivity != null ? group.feeSensitivity : (base && base.feeSensitivity != null ? base.feeSensitivity : 1),
            useCloseToday: group && group.useCloseToday != null ? !!group.useCloseToday : !!(base && base.useCloseToday),
            rebalanceMode: group && group.rebalanceMode != null ? group.rebalanceMode : (base && base.rebalanceMode ? base.rebalanceMode : 'each_period'),
            liquidityMode: group && group.liquidityMode != null ? group.liquidityMode : (base && base.liquidityMode ? base.liquidityMode : 'infinite'),
            liquidityPercent: group && group.liquidityPercent != null ? group.liquidityPercent : (base && base.liquidityPercent != null ? base.liquidityPercent : 100)
        };
    }

    // ---------------------------------------------------------------------------
    // Edit context helpers
    // ---------------------------------------------------------------------------

    function _selectedEditIds() {
        if (_editSelection && _editSelection instanceof Set) return Array.from(_editSelection);
        if (_editSelection && Array.isArray(_editSelection)) return _editSelection.slice();
        if (_editSelection && typeof _editSelection === 'object') {
            return Object.keys(_editSelection).filter(function(k) { return _editSelection[k]; });
        }
        return [];
    }

    function _buildEditContext() {
        var ids = _selectedEditIds();
        var groups = [];
        if (GT.groupSettings.groups) {
            for (var i = 0; i < ids.length; i++) {
                var g = GT.groupSettings.groups.get(ids[i]);
                if (g) groups.push(g);
            }
        }
        return { ids: ids, groups: groups, count: ids.length };
    }

    function _buildAddContext(flow) {
        var ctx = _buildEditContext();
        ctx.explicitFlow = flow || null;
        var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
        var firstId = sel ? sel.getFirst() : null;
        ctx.activeDerivedId = firstId;
        ctx.activeBaseId = firstId;
        return ctx;
    }

    // ---------------------------------------------------------------------------
    // Mode API
    // ---------------------------------------------------------------------------

    var api = {};

    api.getMode = function() { return _panelMode; };
    api.isMode = function(mode) { return _panelMode === mode; };

    // ── add flow 注册 ──

    /**
     * 注册 addFlow
     *
     * @param {Object} def
     *   - flow: string          — addFlow 名称（如 'base', 'derived', 'ls'）
     *   - priority: number      — 匹配优先级（越大越优先），默认 0
     *   - condition: function(ctx) — 返回 true 表示匹配。
     *       ctx = { editIds, editGroups, editCount, explicitFlow, activeDerivedId, activeBaseId }
     *       当 explicitFlow === def.flow 时直接匹配（不检查 condition）
     *   - buildDraft: function(ctx) — 返回 draft 对象。至少要有 addFlow 字段。
     *   - onSubmit: function(draft, helpers) — 提交回调（可选）。
     *       helpers = { exitAdd }
     *   - defaultTab: string    — 进入此 flow 后默认显示的 tab（可选）
     */
    api.registerAddFlow = function(def) {
        if (!def || !def.flow) { console.warn('[modes] registerAddFlow: missing flow name'); return; }
        def.priority = def.priority || 0;
        _addFlowRegistry.push(def);
        _addFlowRegistry.sort(function(a, b) { return (b.priority || 0) - (a.priority || 0); });
    };

    api.getActiveFlowMeta = function() { return _activeFlowMeta; };
    api.getActiveFlow = function() { return _activeFlowMeta ? _activeFlowMeta.flow : null; };

    api.isAddFlow = function(flow) {
        return _panelMode === 'add' && _activeFlowMeta && _activeFlowMeta.flow === flow;
    };

    // ── edit action 注册 ──

    /**
     * 注册编辑模式下的操作按钮
     *
     * @param {Object} def
     *   - name: string          — 唯一名称
     *   - label: string         — 按钮文本（HTML 安全）
     *   - priority: number      — 排序（越大越靠前），默认 0
     *   - condition: function(ctx) — 返回 true 表示显示。
     *       ctx = { ids, groups, count, mode: 'edit' }
     *   - action: function(ctx, helpers) — 按钮点击时执行。
     *       helpers = { exitEdit, enterAdd, setDraft, mountTab, renderActions }
     *   - standalone: boolean   — 是否在 config tab 中也显示（默认 false）
     *   - buttonClass: string   — 额外的 CSS class
     */
    api.registerEditAction = function(def) {
        if (!def || !def.name) { console.warn('[modes] registerEditAction: missing name'); return; }
        def.priority = def.priority || 0;
        _editActionRegistry.push(def);
        _editActionRegistry.sort(function(a, b) { return (b.priority || 0) - (a.priority || 0); });
    };

    api.getMatchingEditActions = function() {
        if (_panelMode !== 'edit') return [];
        var ctx = _buildEditContext();
        return _editActionRegistry.filter(function(def) {
            if (typeof def.condition === 'function') return def.condition(ctx);
            return true;
        });
    };

    // ── add mode ──

    api.enterAdd = function(flow) {
        _panelMode = 'add';
        _activeFlowMeta = null;
        var ctx = _buildAddContext(flow);

        var matched = null;
        for (var i = 0; i < _addFlowRegistry.length; i++) {
            var reg = _addFlowRegistry[i];
            if (flow) {
                if (reg.flow === flow) { matched = reg; break; }
            } else {
                if (typeof reg.condition === 'function' && reg.condition(ctx)) { matched = reg; break; }
            }
        }

        if (matched) {
            _activeFlowMeta = matched;
            _addDraft = (typeof matched.buildDraft === 'function')
                ? matched.buildDraft(ctx) : { addFlow: matched.flow };
        } else {
            _addDraft = { addFlow: flow || '' };
        }
    };

    api.exitAdd = function() { _panelMode = 'list'; _addDraft = null; _activeFlowMeta = null; };
    api.getAddDraft = function() { return _addDraft; };

    api.setAddDraft = function(draft) { _addDraft = draft; };

    api.updateAddDraft = function(patch) {
        if (!_addDraft) return;
        Object.assign(_addDraft, patch);
        if (_addDraft._inheritedConfigKeys && patch) {
            Object.keys(patch).forEach(function(key) { delete _addDraft._inheritedConfigKeys[key]; });
        }
    };

    api.buildAddDraft = function() {
        var ctx = _buildAddContext(_activeFlowMeta ? _activeFlowMeta.flow : null);
        if (_activeFlowMeta && typeof _activeFlowMeta.buildDraft === 'function') {
            return _activeFlowMeta.buildDraft(ctx);
        }
        return { addFlow: _activeFlowMeta ? _activeFlowMeta.flow : '' };
    };

    api.getOnSubmit = function() {
        return _activeFlowMeta && typeof _activeFlowMeta.onSubmit === 'function'
            ? _activeFlowMeta.onSubmit : null;
    };

    api.getDefaultTab = function() {
        return _activeFlowMeta ? _activeFlowMeta.defaultTab || null : null;
    };

    // ── edit mode ──

    api.enterEdit = function(selection) {
        var REG = window.GT_CONFIG_REGISTRY;
        if (REG && typeof REG.rollbackDirty === 'function') REG.rollbackDirty();
        _panelMode = 'edit';
        _editSelection = selection || {};
    };

    api.exitEdit = function() {
        var REG = window.GT_CONFIG_REGISTRY;
        if (REG && typeof REG.rollbackDirty === 'function') REG.rollbackDirty();
        _panelMode = 'list';
        _editSelection = null;
        var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
        if (sel) sel.clear();
        if (GT.events && GT.events.emit) {
            GT.events.emit('editModeExited');
        }
    };

    api.getEditSelection = function() { return _editSelection; };
    api.getEditIds = function() { return _selectedEditIds(); };
    api.getEditContext = function() { return _buildEditContext(); };

    // ── 配置解析（泛型） ──

    api.resolveConfig = function(group) {
        if (!group) return null;
        return _resolvedConfigForDraft(group);
    };

    // ═══════════════════════════════════════════════════════════════
    // Export
    // ═══════════════════════════════════════════════════════════════

    GT.modes = api;

    GT.log('registry/modes loaded');
})();
