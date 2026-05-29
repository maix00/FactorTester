/**
 * panels/base/groups.js — Group settings panel (Tab 1, sub-tab "分组设置")
 *
 * Phase 3 UI panel. Renders group-count / group-index / isAllGroups fields,
 * time-range inputs, and a "sync from strategy params" button for the selected
 * base group. All data access through datamodel + state.
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

    var _containerId = 'base-groups-settings';
    var _mounted = false;

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

        var groupCount = item.groupCount != null ? item.groupCount : 5;
        var groupIndex = item.groupIndex != null ? item.groupIndex : 0;
        var isAllGroups = !!item.isAllGroups;
        var startDate = item.startDate || '';
        var endDate = item.endDate || '';

        var html = '<div style="padding:16px 0;display:flex;flex-direction:column;gap:14px;">';

        // --- Group count row ---
        html += '<div style="display:flex;align-items:center;gap:8px;">';
        html += '<label for="gs-group-count" style="font-size:14px;font-weight:500;">分组数：</label>';
        html += '<input type="number" id="gs-group-count" value="' + groupCount + '" min="2" max="20" style="width:70px;padding:3px 6px;border:1px solid #d0d5dd;border-radius:4px;font-size:13px;" ' + (isAllGroups ? 'disabled' : '') + ' />';
        html += '<span style="font-size:12px;color:#888;">2-20</span>';
        html += '</div>';

        // --- Group index row ---
        html += '<div style="display:flex;align-items:center;gap:8px;">';
        html += '<label for="gs-group-index" style="font-size:14px;font-weight:500;">分组序数：</label>';
        html += '<input type="number" id="gs-group-index" value="' + groupIndex + '" min="0" style="width:70px;padding:3px 6px;border:1px solid #d0d5dd;border-radius:4px;font-size:13px;" ' + (isAllGroups ? 'disabled' : '') + ' />';
        html += '<span style="font-size:12px;color:#888;">0 = 不做分组筛选</span>';
        html += '</div>';

        // --- All groups toggle ---
        html += '<div style="display:flex;align-items:center;gap:10px;">';
        html += '<label style="font-size:14px;font-weight:500;">全部组：</label>';
        html += '<label style="display:flex;align-items:center;gap:4px;cursor:pointer;">';
        html += '<input type="checkbox" id="gs-all-groups" ' + (isAllGroups ? 'checked' : '') + ' style="width:16px;height:16px;" />';
        html += '<span style="font-size:13px;">同时对多组做测试</span>';
        html += '</label>';
        html += '</div>';

        // --- Time range ---
        html += '<div style="border-top:1px solid #e5e7eb;padding-top:12px;margin-top:4px;">';
        html += '<div style="font-size:13px;font-weight:600;margin-bottom:8px;color:#444;">时间范围（可选覆盖）</div>';
        html += '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">';
        html += '<label style="font-size:13px;">起始：</label>';
        html += '<input type="date" id="gs-start-date" value="' + startDate + '" style="padding:2px 6px;border:1px solid #d0d5dd;border-radius:4px;font-size:13px;" />';
        html += '<label style="font-size:13px;margin-left:8px;">终止：</label>';
        html += '<input type="date" id="gs-end-date" value="' + endDate + '" style="padding:2px 6px;border:1px solid #d0d5dd;border-radius:4px;font-size:13px;" />';
        html += '</div>';
        html += '</div>';

        // --- Sync button ---
        html += '<div style="border-top:1px solid #e5e7eb;padding-top:12px;">';
        html += '<button id="gs-sync-btn" class="btn btn-outline-secondary btn-sm" style="padding:4px 14px;">从策略参数同步</button>';
        html += '<span style="margin-left:8px;font-size:12px;color:#888;">会覆盖分组数/序数/全部组/时间</span>';
        html += '</div>';

        html += '</div>';
        container.innerHTML = html;

        // --- Bind events ---
        var gcInput = $('gs-group-count');
        var giInput = $('gs-group-index');
        var agCheck = $('gs-all-groups');
        var sdInput = $('gs-start-date');
        var edInput = $('gs-end-date');
        var syncBtn = $('gs-sync-btn');

        function save() {
            var id = GT.state.getActiveBaseGroupId();
            if (!id) return;
            var patch = {
                groupCount: parseInt(gcInput.value, 10) || 5,
                groupIndex: parseInt(giInput.value, 10) || 0,
                isAllGroups: agCheck.checked,
                startDate: sdInput.value,
                endDate: edInput.value,
            };
            try {
                GT.datamodel.base_groups.update(id, patch);
            } catch (err) {
                alert('操作失败: ' + err.message);
            }
        }

        if (gcInput) gcInput.addEventListener('change', save);
        if (giInput) giInput.addEventListener('change', save);
        if (agCheck) {
            agCheck.addEventListener('change', function() {
                var disabled = agCheck.checked;
                if (gcInput) gcInput.disabled = disabled;
                if (giInput) giInput.disabled = disabled;
                save();
            });
        }
        if (sdInput) sdInput.addEventListener('change', save);
        if (edInput) edInput.addEventListener('change', save);

        if (syncBtn) {
            syncBtn.addEventListener('click', function() {
                var id = GT.state.getActiveBaseGroupId();
                if (!id) return;
                var current = GT.datamodel.base_groups.get(id);
                if (!current) return;

                // Pull from parent strategy params (or use defaults)
                var stratGroupCount = (current.strategyGroupCount != null) ? current.strategyGroupCount : 5;
                var stratIsAllGroups = !!current.strategyIsAllGroups;

                var patch = {
                    groupCount: stratGroupCount,
                    groupIndex: 0,
                    isAllGroups: stratIsAllGroups,
                };
                try {
                    GT.datamodel.base_groups.update(id, patch);
                } catch (err) {
                    alert('同步失败: ' + err.message);
                }
            });
        }
    }

    // ---------------------------------------------------------------------------
    // Events
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
            GT.log('panels.base.groups: container #' + _containerId + ' not found');
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

    GT.panels.base.groups = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
    };

    GT.log('panels.base.groups loaded');
})();
