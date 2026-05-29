/**
 * panels/base/close_today.js — Close-today toggle panel (Tab 1, sub-tab "平今/昨")
 *
 * Phase 3 UI panel. Renders a toggle switch for the selected base group's
 * useCloseToday field. All data access through datamodel + state.
 *
 * Contract (provided by P3-1 & datamodel):
 *   GT.state.getActiveBaseGroupId() → id|null
 *   GT.state.on('activeBaseGroupChanged', cb)
 *   GT.datamodel.base_groups.get(id) → {...}|null
 *   GT.datamodel.base_groups.update(id, patch)
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.base) { GT.panels.base = {}; }

    // ---------------------------------------------------------------------------
    // Container ID — expected in the HTML template for this sub-tab
    // ---------------------------------------------------------------------------
    var _containerId = 'base-close-today';

    var _mounted = false;

    // ---------------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------------

    function $(id) { return document.getElementById(id); }

    // ---------------------------------------------------------------------------
    // Render
    // ---------------------------------------------------------------------------

    function render() {
        var container = $(_containerId);
        if (!container) { return; }

        var activeId = GT.state.getActiveBaseGroupId();

        if (!activeId) {
            container.innerHTML = '<div class="group-test-empty-state" style="padding:24px;text-align:center;color:#888;font-size:13px;">请先在基础组列表中选择一个基础组</div>';
            return;
        }

        var item = GT.datamodel.base_groups.get(activeId);
        if (!item) {
            container.innerHTML = '<div class="group-test-empty-state" style="padding:24px;text-align:center;color:#888;font-size:13px;">未找到选中的基础组</div>';
            return;
        }

        var useCloseToday = !!item.useCloseToday;
        var stateColor = useCloseToday ? '#d97706' : '#0078d4';
        var stateText = useCloseToday ? '平今仓' : '平昨仓';
        var btnText = useCloseToday ? '切换为平昨仓' : '切换为平今仓';
        var btnClass = useCloseToday ? 'btn-outline-warning' : 'btn-outline-secondary';

        var html = '<div style="padding:16px 0;">';
        html += '<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">';
        html += '<span style="font-size:14px;font-weight:500;">平仓口径：</span>';
        html += '<strong id="ct-state-text" style="font-size:15px;color:' + stateColor + ';">' + stateText + '</strong>';
        html += '</div>';
        html += '<div style="display:flex;align-items:center;gap:8px;">';
        html += '<button id="ct-toggle-btn" class="btn btn-sm ' + btnClass + '" style="padding:4px 14px;">' + btnText + '</button>';
        html += '<span style="font-size:12px;color:#888;">影响品种费率表中平今/平昨比率的选择</span>';
        html += '</div>';
        html += '</div>';

        container.innerHTML = html;

        // Bind toggle
        var btn = $('ct-toggle-btn');
        if (btn) {
            btn.addEventListener('click', function() {
                var id = GT.state.getActiveBaseGroupId();
                if (!id) return;
                var current = GT.datamodel.base_groups.get(id);
                if (!current) return;
                var newVal = !current.useCloseToday;
                try {
                    GT.datamodel.base_groups.update(id, { useCloseToday: newVal });
                } catch (err) {
                    alert('操作失败: ' + err.message);
                }
            });
        }
    }

    // ---------------------------------------------------------------------------
    // Event handlers
    // ---------------------------------------------------------------------------

    function _onBaseGroupsChanged() {
        if (_mounted) { render(); }
    }

    function _onActiveBaseGroupChanged() {
        if (_mounted) { render(); }
    }

    // ---------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------

    function mount() {
        _mounted = true;
        var container = $(_containerId);
        if (!container) {
            GT.log('panels.base.close_today: container #' + _containerId + ' not found');
            return;
        }
        GT.state.on('baseGroupsChanged', _onBaseGroupsChanged);
        GT.state.on('activeBaseGroupChanged', _onActiveBaseGroupChanged);
        render();
    }

    function unmount() {
        _mounted = false;
        GT.state.off('baseGroupsChanged', _onBaseGroupsChanged);
        GT.state.off('activeBaseGroupChanged', _onActiveBaseGroupChanged);
    }

    function refresh() {
        if (_mounted) { render(); }
    }

    // ---------------------------------------------------------------------------
    // Export
    // ---------------------------------------------------------------------------

    GT.panels.base.close_today = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
    };

    GT.log('panels.base.close_today loaded');
})();
