/**
 * panels/derived/rebalance.js — Derived group rebalance mode panel (Tab 2, sub-tab "再平衡")
 *
 * Phase 4 UI panel. Inherit toggle + rebalance mode selector for the selected
 * derived group node. Valid modes: each_period | buy_and_hold | recycle.
 *
 * Contract:
 *   GT.state.getActiveDerivedNodeId() → id|null
 *   GT.state.on('activeDerivedNodeChanged', cb)
 *   GT.state.on('derivedGraphChanged', cb)
 *   GT.datamodel.derived_graph.get(id) → node|null
 *   GT.datamodel.derived_graph.update(id, patch)
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.derived) { GT.panels.derived = {}; }

    var CONTAINER_ID = 'derived-rebalance-panel';

    var MODE_LABELS = {
        'each_period': '每期等权再平衡',
        'buy_and_hold': '组内持仓不动',
        'recycle': '退出资金优先补新仓',
    };

    var _mounted = false;
    var _activeId = null;

    function $(id) { return document.getElementById(id); }

    function _getNode() {
        var id = GT.state.getActiveDerivedNodeId();
        if (!id) return null;
        return GT.datamodel.derived_graph.get(id);
    }

    function _hasOverride(node) {
        return node && node.rebalanceOverride !== null && node.rebalanceOverride !== undefined;
    }

    function _effectiveMode(node) {
        if (!node) return 'buy_and_hold';
        if (_hasOverride(node)) return node.rebalanceOverride;
        if (node.parentId) {
            var parent = GT.datamodel.derived_graph.get(node.parentId);
            if (parent) return _effectiveMode(parent);
        }
        if (node.baseGroupId) {
            var bg = GT.datamodel.base_groups.get(node.baseGroupId);
            if (bg && bg.rebalanceMode) return bg.rebalanceMode;
        }
        return 'buy_and_hold';
    }

    function _resolveSource(nodeId) {
        var node = GT.datamodel.derived_graph.get(nodeId);
        if (!node) return { source: 'default', sourceName: '系统默认' };
        if (_hasOverride(node)) return { source: 'override', sourceName: '当前节点覆盖' };
        if (node.parentId) {
            var pr = _resolveSource(node.parentId);
            if (pr.source !== 'default') return pr;
        }
        if (node.baseGroupId) {
            var bg = GT.datamodel.base_groups.get(node.baseGroupId);
            if (bg && bg.rebalanceMode) {
                return { source: 'baseGroup', sourceName: '基础组: ' + (bg.name || node.baseGroupId) };
            }
        }
        return { source: 'default', sourceName: '系统默认' };
    }

    // ---------------------------------------------------------------------------
    // Render
    // ---------------------------------------------------------------------------

    function render() {
        var container = $(CONTAINER_ID);
        if (!container) return;

        var node = _getNode();
        if (!node) {
            container.innerHTML = '<div style="padding:24px;text-align:center;color:#888;">请在「树」中选择一个派生组节点</div>';
            _activeId = null;
            return;
        }

        _activeId = node.id;
        var isInheriting = !_hasOverride(node);
        var sourceInfo = _resolveSource(node.id);
        var effMode = _effectiveMode(node);
        var modeLabel = MODE_LABELS[effMode] || effMode;

        var html = '';

        // Inherit toggle
        html += '<div style="margin-bottom:16px;display:flex;align-items:center;gap:12px;">';
        html += '<label style="font-size:13px;font-weight:600;">策略来源</label>';
        html += '<select id="' + CONTAINER_ID + '-inherit-toggle" style="padding:4px 8px;border:1px solid #ccc;border-radius:4px;font-size:13px;">';
        html += '<option value="inherit"' + (isInheriting ? ' selected' : '') + '>继承 (来自: ' + sourceInfo.sourceName + ')</option>';
        html += '<option value="override"' + (!isInheriting ? ' selected' : '') + '>覆盖 (自定义)</option>';
        html += '</select>';
        html += '</div>';

        if (isInheriting) {
            html += '<div style="padding:12px;background:#f0f7ff;border-radius:6px;border:1px solid #b3d4fc;">';
            html += '<div style="font-size:12px;color:#666;margin-bottom:6px;">当前有效模式 (继承)</div>';
            html += '<strong style="font-size:15px;">' + modeLabel + '</strong>';
            html += '</div>';
        } else {
            var currentMode = node.rebalanceOverride || 'buy_and_hold';
            html += '<div style="display:flex;align-items:center;gap:12px;">';
            html += '<label for="' + CONTAINER_ID + '-mode-select" style="font-size:14px;font-weight:500;">再平衡模式：</label>';
            html += '<select id="' + CONTAINER_ID + '-mode-select" style="width:200px;padding:4px 8px;border:1px solid #d0d5dd;border-radius:4px;font-size:13px;">';
            Object.keys(MODE_LABELS).forEach(function(mode) {
                var sel = mode === currentMode ? ' selected' : '';
                html += '<option value="' + mode + '"' + sel + '>' + MODE_LABELS[mode] + '</option>';
            });
            html += '</select>';
            html += '</div>';
        }

        container.innerHTML = html;
        _bindEvents(container);
    }

    // ---------------------------------------------------------------------------
    // Event binding
    // ---------------------------------------------------------------------------

    function _bindEvents(container) {
        var select = $(CONTAINER_ID + '-inherit-toggle');
        if (select) {
            select.addEventListener('change', function() {
                if (this.value === 'inherit') {
                    _clearOverride();
                } else {
                    var eff = _effectiveMode(_getNode());
                    _saveOverride({ rebalanceOverride: eff });
                }
            });
        }

        var modeSelect = $(CONTAINER_ID + '-mode-select');
        if (modeSelect) {
            modeSelect.addEventListener('change', function() {
                if (!_activeId) return;
                try {
                    GT.datamodel.derived_graph.update(_activeId, { rebalanceOverride: this.value });
                } catch (err) {
                    alert('保存失败: ' + err.message);
                }
            });
        }
    }

    // ---------------------------------------------------------------------------
    // Save
    // ---------------------------------------------------------------------------

    function _saveOverride(patch) {
        if (!_activeId) return;
        try {
            GT.datamodel.derived_graph.update(_activeId, patch);
        } catch (err) {
            alert('保存失败: ' + err.message);
        }
    }

    function _clearOverride() {
        if (!_activeId) return;
        try {
            GT.datamodel.derived_graph.update(_activeId, { rebalanceOverride: null });
        } catch (err) {
            alert('清除失败: ' + err.message);
        }
    }

    // ---------------------------------------------------------------------------
    // Event handlers
    // ---------------------------------------------------------------------------

    function _onDerivedNodeChanged() { if (_mounted) render(); }
    function _onDerivedGraphChanged() { if (_mounted) render(); }

    // ---------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------

    function mount() {
        _mounted = true;
        _activeId = GT.state.getActiveDerivedNodeId();
        GT.state.on('activeDerivedNodeChanged', _onDerivedNodeChanged);
        GT.state.on('derivedGraphChanged', _onDerivedGraphChanged);
        render();
    }

    function unmount() {
        _mounted = false;
        _activeId = null;
        GT.state.off('activeDerivedNodeChanged', _onDerivedNodeChanged);
        GT.state.off('derivedGraphChanged', _onDerivedGraphChanged);
    }

    function refresh() { if (_mounted) render(); }

    // ---------------------------------------------------------------------------
    // Export
    // ---------------------------------------------------------------------------

    GT.panels.derived.rebalance = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
    };

    GT.log('panels.derived.rebalance loaded');
})();
