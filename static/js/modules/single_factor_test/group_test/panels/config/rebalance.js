/**
 * panels/config/rebalance.js — Rebalance mode panel (category-3)
 *
 * Phase 3 UI panel. Renders a dropdown for the selected base group's
 * rebalanceMode field with mode description. All data access through groupSettings + state.
 *
 * Contract:
 *   GT.panels.list.selection.getFirst() → id|null
 *   GT.panels.list.selection.on('selectionChanged', cb)
 *   GT.groupSettings.groups.get(id) → {...}|null
 *   GT.groupSettings.groups.update(id, patch)
 *
 * Valid modes: each_period | buy_and_hold | recycle
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.config) { GT.panels.config = {}; }

    var REG = window.GT_CONFIG_REGISTRY;

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

    function registry() {
        REG = window.GT_CONFIG_REGISTRY || REG;
        return REG;
    }

    function render() {
        var container = $(_containerId);
        if (!container) { return; }

        var reg = registry();
        if (!reg) { return; }

        var group = reg.getReferenceGroup();
        if (!group) {
            container.innerHTML = '<div class="group-test-empty-state" style="padding:24px;text-align:center;color:#888;font-size:13px;">请先在基础组列表中选择一个基础组</div>';
            return;
        }

        var currentMode = reg.getDirty('rebalanceMode', group.rebalanceMode || 'each_period');
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
                var descEl = $('rb-mode-desc');
                if (descEl) {
                    descEl.textContent = MODE_DESCRIPTIONS[newMode] || '';
                }
                registry().setDirty('rebalanceMode', newMode);
                render();
            });
        }
    }

    function _onBaseGroupsChanged() {
        var reg = registry();
        if (_mounted && reg && !reg.hasDirty()) { render(); }
    }

    function _onSelectionChanged() {
        var reg = registry();
        if (_mounted && reg) { reg.rollbackDirty(); render(); }
    }

    function mount() {
        registry();
        _mounted = true;
        var container = $(_containerId);
        if (!container) {
            GT.log('panels.base.rebalance: container #' + _containerId + ' not found');
            return;
        }
        if (GT.events && GT.events.on) GT.events.on('groupsChanged', _onBaseGroupsChanged);
        var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
        if (sel && sel.on) sel.on('selectionChanged', _onSelectionChanged);
        render();
    }

    function unmount() {
        _mounted = false;
        if (GT.events && GT.events.off) GT.events.off('groupsChanged', _onBaseGroupsChanged);
        var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
        if (sel && sel.off) sel.off('selectionChanged', _onSelectionChanged);
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

    function getChips(group) {
        if (!group) return [];
        var mode = group.rebalanceMode || 'buy_and_hold';
        var label = MODE_LABELS[mode];
        if (!label) return [];
        var chipPlain = 'display:inline-block;background:#e5e7eb;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;color:#374151;';
        return [{
            label: 'rebalance-mode',
            html: '⚖️ 再平衡:' + label,
            style: chipPlain,
        }];
    }

    GT.panels.config = GT.panels.config || {};
    GT.panels.config.rebalance = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
        getTableColumns: getTableColumns,
        getChips: getChips,
    };

    // Register as category-3 config panel
    if (window.GT_CONFIG_REGISTRY) {
        window.GT_CONFIG_REGISTRY.register({
            name: 'rebalance',
            label: '再平衡',
            panel: GT.panels.config.rebalance,
            fields: ['rebalanceMode'],
        }, 'config-rebalance');
    }

    GT.log('panels.config.rebalance loaded');
})();
