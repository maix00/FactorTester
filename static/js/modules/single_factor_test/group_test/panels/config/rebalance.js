/**
 * panels/config/rebalance.js — Rebalance mode panel (category-3)
 *
 * Phase 3 UI panel. Renders a dropdown for the selected base group's
 * rebalanceMode field with mode description. All data access through datamodel + state.
 *
 * Contract (provided by P3-1 & datamodel):
 *   GT.state.getActiveBaseGroupId() → id|null
 *   GT.state.on('activeBaseGroupChanged', cb)
 *   GT.datamodel.base_groups.get(id) → {...}|null
 *   GT.datamodel.base_groups.update(id, patch)
 *
 * Valid modes: each_period | buy_and_hold | recycle
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.config) { GT.panels.config = {}; }

    var _containerId = 'config-rebalance';
    var _mounted = false;

    var MODE_LABELS = {
        'each_period': '每期等权再平衡',
        'buy_and_hold': '组内持仓不动',
        'recycle': '退出资金优先补新仓',
    };

    var MODE_DESCRIPTIONS = {
        'each_period': '每一期都把当前组内成员重新调成等权。适合比较"每期按最新排序重新建仓"的理论表现，换手通常最高。',
        'buy_and_hold': '组内成员不变时保持原有持仓比例；只有成员进出组时才交易。更接近低换手的持有逻辑，也是默认模式。',
        'recycle': '留存成员的持仓不动；有成员退出时，把释放出的资金优先分给新进成员。适合观察"旧仓尽量不动、只用退出资金补新仓"的过渡方式。',
    };

    function $(id) { return document.getElementById(id); }

    function render() {
        var container = $(_containerId);
        if (!container) { return; }

        var mode = GT.ui && GT.ui.getPanelMode ? GT.ui.getPanelMode() : 'list';
        var currentMode = 'each_period'; // default for add mode
        var activeId = null;

        if (mode === 'add') {
            var draft = GT.ui && GT.ui.getAddDraft ? GT.ui.getAddDraft() : null;
            currentMode = (draft && draft.rebalanceMode) || 'each_period';
        } else if (mode === 'edit') {
            var sel = GT.ui && GT.ui.getEditSelection ? GT.ui.getEditSelection() : null;
            if (sel && sel.groupIds && sel.groupIds.length > 0) {
                activeId = sel.groupIds[0];
            }
        } else {
            activeId = GT.state.getActiveBaseGroupId();
        }

        if (!activeId && mode !== 'add') {
            container.innerHTML = '<div class="group-test-empty-state" style="padding:24px;text-align:center;color:#888;font-size:13px;">请先在基础组列表中选择一个基础组</div>';
            return;
        }

        if (activeId) {
            var item = GT.datamodel.base_groups.get(activeId);
            if (!item) {
                container.innerHTML = '<div class="group-test-empty-state" style="padding:24px;text-align:center;color:#888;font-size:13px;">未找到选中的基础组</div>';
                return;
            }
            currentMode = item.rebalanceMode || 'each_period';
        }
        var desc = MODE_DESCRIPTIONS[currentMode] || '';

        var html = '<div style="padding:16px 0;">';
        html += '<div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">';
        html += '<label for="rb-mode-select" style="font-size:14px;font-weight:500;white-space:nowrap;">再平衡模式：</label>';
        html += '<select id="rb-mode-select" style="width:200px;padding:4px 8px;border:1px solid #d0d5dd;border-radius:4px;font-size:13px;">';
        Object.keys(MODE_LABELS).forEach(function(mode) {
            var selected = mode === currentMode ? ' selected' : '';
            html += '<option value="' + mode + '"' + selected + '>' + MODE_LABELS[mode] + '</option>';
        });
        html += '</select>';
        html += '</div>';

        html += '<div id="rb-mode-desc" style="padding:10px 14px;background:#f6f8fa;border-radius:4px;border-left:3px solid #0f4c81;font-size:13px;color:#555;line-height:1.5;">' + desc + '</div>';

        html += '<div style="margin-top:10px;font-size:12px;color:#888;">';
        html += '若所选产品交易时段不统一，出现"部分产品有信号、部分产品无信号"的混合期时，会自动启用多时段保护逻辑，并临时覆盖所选再平衡模式。';
        html += '</div>';

        html += '</div>';
        container.innerHTML = html;

        var select = $('rb-mode-select');
        if (select) {
            select.addEventListener('change', function() {
                var newMode = select.value;
                var currentMode = GT.ui && GT.ui.getPanelMode ? GT.ui.getPanelMode() : 'list';
                var descEl = $('rb-mode-desc');
                if (descEl) {
                    descEl.textContent = MODE_DESCRIPTIONS[newMode] || '';
                }
                if (currentMode === 'add') {
                    if (GT.ui && typeof GT.ui.updateAddDraft === 'function') {
                        GT.ui.updateAddDraft({ rebalanceMode: newMode });
                    }
                    return;
                }
                var id = GT.state.getActiveBaseGroupId();
                if (currentMode === 'edit') {
                    var sel = GT.ui && GT.ui.getEditSelection ? GT.ui.getEditSelection() : null;
                    if (sel && sel.groupIds && sel.groupIds.length > 0) {
                        var ids = sel.groupIds;
                        for (var i = 0; i < ids.length; i++) {
                            try {
                                GT.datamodel.base_groups.update(ids[i], { rebalanceMode: newMode });
                            } catch (err) { /* skip individual failures */ }
                        }
                    }
                } else {
                    if (!id) return;
                    try {
                        GT.datamodel.base_groups.update(id, { rebalanceMode: newMode });
                    } catch (err) {
                        alert('操作失败: ' + err.message);
                    }
                }
            });
        }
    }

    function _onBaseGroupsChanged() {
        if (_mounted) { render(); }
    }

    function _onActiveBaseGroupChanged() {
        if (_mounted) { render(); }
    }

    function mount() {
        _mounted = true;
        var container = $(_containerId);
        if (!container) {
            GT.log('panels.base.rebalance: container #' + _containerId + ' not found');
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
    // Category-3 table column contribution
    // ---------------------------------------------------------------------------

    function getTableColumns() {
        return [
            {
                key: 'rebalance',
                label: '再平衡',
                render: function(group) {
                    var map = { 'each_period': '每期', 'buy_and_hold': '持仓不动', 'recycle': '退出补新' };
                    return map[group.rebalanceMode] || (group.rebalanceMode || '—');
                }
            }
        ];
    }

    GT.panels.config = GT.panels.config || {};
    GT.panels.config.rebalance = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
        getTableColumns: getTableColumns,
    };

    // Register as category-3 config panel
    if (window.GT_CONFIG_REGISTRY) {
        window.GT_CONFIG_REGISTRY.register({
            name: 'rebalance',
            label: '再平衡',
            panel: GT.panels.config.rebalance,
        }, 'config-rebalance');
    }

    GT.log('panels.config.rebalance loaded');
})();
