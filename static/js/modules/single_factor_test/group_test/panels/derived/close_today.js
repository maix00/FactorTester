/**
 * panels/derived/close_today.js — Derived group close-today panel (Tab 2, sub-tab "平今/昨")
 *
 * Phase 4 UI panel. Inherit toggle + close-today switch for the selected
 * derived group node. When inheriting, shows effective close-today from
 * parent chain. When overriding, allows direct toggle.
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

    var CONTAINER_ID = 'derived-close-today-panel';

    var _mounted = false;
    var _activeId = null;

    function $(id) { return document.getElementById(id); }

    function _getNode() {
        var id = GT.state.getActiveDerivedNodeId();
        if (!id) return null;
        return GT.datamodel.derived_graph.get(id);
    }

    function _hasOverride(node) {
        return node && node.closeTodayOverride !== null && node.closeTodayOverride !== undefined;
    }

    /**
     * Resolve effective close-today boolean.
     * Override takes priority, then walk parent chain, then base group.
     */
    function _effectiveCloseToday(node) {
        if (!node) return false;
        if (_hasOverride(node)) return !!node.closeTodayOverride;
        if (node.parentId) {
            var parent = GT.datamodel.derived_graph.get(node.parentId);
            if (parent) return _effectiveCloseToday(parent);
        }
        if (node.baseGroupId) {
            var bg = GT.datamodel.base_groups.get(node.baseGroupId);
            if (bg) return !!bg.useCloseToday;
        }
        return false;
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
            if (bg && bg.useCloseToday !== undefined) {
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
        var effCT = _effectiveCloseToday(node);

        var stateColor = effCT ? '#d97706' : '#0078d4';
        var stateText = effCT ? '平今仓' : '平昨仓';

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
            // Read-only display
            html += '<div style="padding:12px;background:#f0f7ff;border-radius:6px;border:1px solid #b3d4fc;">';
            html += '<div style="font-size:12px;color:#666;margin-bottom:6px;">当前有效值 (继承)</div>';
            html += '<strong style="font-size:15px;color:' + stateColor + ';">' + stateText + '</strong>';
            html += '</div>';
        } else {
            // Editable toggle
            var cto = node.closeTodayOverride;
            var eff = cto !== undefined && cto !== null ? !!cto : false;
            var btnText = eff ? '切换为平昨仓' : '切换为平今仓';
            var btnClass = eff ? 'btn-outline-warning' : 'btn-outline-secondary';

            html += '<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">';
            html += '<span style="font-size:14px;font-weight:500;">平仓口径：</span>';
            html += '<strong id="' + CONTAINER_ID + '-state-text" style="font-size:15px;color:' + stateColor + ';">' + stateText + '</strong>';
            html += '</div>';
            html += '<button id="' + CONTAINER_ID + '-toggle-btn" class="btn btn-sm ' + btnClass + '" style="padding:4px 14px;">' + btnText + '</button>';
        }

        container.innerHTML = html;
        _bindEvents(container);
    }

    // ---------------------------------------------------------------------------
    // Event binding
    // ---------------------------------------------------------------------------

    function _bindEvents(container) {
        // Inherit toggle
        var select = $(CONTAINER_ID + '-inherit-toggle');
        if (select) {
            select.addEventListener('change', function() {
                if (this.value === 'inherit') {
                    _clearOverride();
                } else {
                    // Switch to override: inherit current effective value
                    var eff = _effectiveCloseToday(_getNode());
                    _saveOverride({ closeTodayOverride: eff });
                }
            });
        }

        // Toggle button
        var btn = $(CONTAINER_ID + '-toggle-btn');
        if (btn) {
            btn.addEventListener('click', function() {
                if (!_activeId) return;
                var node = _getNode();
                if (!node) return;
                var current = _hasOverride(node) ? !!node.closeTodayOverride : _effectiveCloseToday(node);
                _saveOverride({ closeTodayOverride: !current });
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
            GT.datamodel.derived_graph.update(_activeId, { closeTodayOverride: null });
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

    GT.panels.derived.close_today = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
    };

    GT.log('panels.derived.close_today loaded');
})();
