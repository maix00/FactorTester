/**
 * panels/config/liquidity.js — Liquidity constraint config panel
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.config) { GT.panels.config = {}; }

    var REG = window.GT_CONFIG_REGISTRY;
    var _containerId = 'config-liquidity';
    var _mounted = false;

    var MODE_LABELS = {
        infinite: '无限流动性',
        percent: '百分比流动性',
    };

    function $(id) { return document.getElementById(id); }

    function registry() {
        REG = window.GT_CONFIG_REGISTRY || REG;
        return REG;
    }

    function _percentValue(value) {
        var num = Number(value);
        if (!isFinite(num)) return 100;
        if (num < 0) return 0;
        if (num > 100) return 100;
        return num;
    }

    function _formatPercent(value) {
        var num = _percentValue(value);
        return (Math.round(num * 100) / 100).toString().replace(/\.0+$/, '').replace(/(\.\d*[1-9])0+$/, '$1') + '%';
    }

    function render() {
        var container = $(_containerId);
        if (!container) return;

        var reg = registry();
        if (!reg) return;

        var group = reg.getReferenceGroup();
        if (!group) {
            container.innerHTML = '<div class="group-test-empty-state" style="padding:24px;text-align:center;color:#888;font-size:13px;">请先选择一个分组</div>';
            return;
        }

        var mode = reg.getDirty('liquidityMode', group.liquidityMode || 'infinite');
        var percent = _percentValue(reg.getDirty('liquidityPercent', group.liquidityPercent !== undefined && group.liquidityPercent !== null ? group.liquidityPercent : 100));
        var showPercent = mode === 'percent';

        var html = '<div style="padding:16px 0;">';
        html += '<div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">';
        html += '<label for="liquidity-mode-select" style="font-size:14px;font-weight:500;white-space:nowrap;">流动性约束：</label>';
        html += '<select id="liquidity-mode-select" style="width:200px;padding:4px 8px;border:1px solid #d0d5dd;border-radius:4px;font-size:13px;">';
        Object.keys(MODE_LABELS).forEach(function(key) {
            html += '<option value="' + key + '"' + (key === mode ? ' selected' : '') + '>' + MODE_LABELS[key] + '</option>';
        });
        html += '</select>';
        html += '</div>';

        html += '<div id="liquidity-percent-row" style="display:' + (showPercent ? 'flex' : 'none') + ';align-items:center;gap:10px;margin-bottom:12px;">';
        html += '<label for="liquidity-percent-input" style="font-size:13px;color:#555;">单期交易量上限：</label>';
        html += '<input id="liquidity-percent-input" type="number" min="0" max="100" step="0.1" value="' + percent + '" style="width:96px;padding:4px 8px;border:1px solid #d0d5dd;border-radius:4px;font-size:13px;">';
        html += '<span style="font-size:13px;color:#555;">% 当期成交量</span>';
        html += '</div>';

        html += '<div style="padding:10px 14px;background:#f6f8fa;border-radius:4px;border-left:3px solid #0f4c81;font-size:13px;color:#555;line-height:1.5;">';
        html += showPercent
            ? '每次调仓的买卖量不得超过当期成交量的 ' + _formatPercent(percent) + '。当期成交量应按测试/信号频率聚合，例如 1m 原始量在 $F=5m 时使用 5 分钟成交量求和。'
            : '默认不使用成交量约束，按理论目标仓位成交。';
        html += '</div>';
        html += '</div>';

        container.innerHTML = html;

        var modeSelect = $('liquidity-mode-select');
        if (modeSelect) {
            modeSelect.addEventListener('change', function() {
                var newMode = modeSelect.value || 'infinite';
                registry().setDirty('liquidityMode', newMode);
                if (newMode === 'percent') {
                    registry().setDirty('liquidityPercent', percent);
                }
                render();
            });
        }

        var percentInput = $('liquidity-percent-input');
        if (percentInput) {
            percentInput.addEventListener('change', function() {
                registry().setDirty('liquidityPercent', _percentValue(percentInput.value));
                render();
            });
        }
    }

    function _onGroupsChanged() {
        var reg = registry();
        if (_mounted && reg && !reg.hasDirty()) render();
    }

    function _onActiveGroupChanged() {
        var reg = registry();
        if (_mounted && reg) { reg.rollbackDirty(); render(); }
    }

    function mount() {
        registry();
        _mounted = true;
        GT.state.on('groupsChanged', _onGroupsChanged);
        var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
        if (sel && sel.on) sel.on('selectionChanged', _onActiveGroupChanged);
        render();
    }

    function unmount() {
        _mounted = false;
        GT.state.off('groupsChanged', _onGroupsChanged);
        var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
        if (sel && sel.off) sel.off('selectionChanged', _onActiveGroupChanged);
    }

    function refresh() {
        if (_mounted) render();
    }

    function getTableColumns() {
        return [{
            key: 'liquidity',
            label: '流动性',
            render: function(group) {
                var mode = group && group.liquidityMode || 'infinite';
                if (mode === 'percent') return _formatPercent(group.liquidityPercent) + '成交量';
                return '无限';
            }
        }];
    }

    function getChips(group) {
        if (!group) return [];
        var mode = group.liquidityMode || 'infinite';
        var html = mode === 'percent' ? ('💧 流动性:' + _formatPercent(group.liquidityPercent)) : '💧 无限流动性';
        return [{
            label: 'liquidity',
            html: html,
            style: 'display:inline-block;background:#e0f2fe;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;color:#075985;',
        }];
    }

    GT.panels.config.liquidity = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
        getTableColumns: getTableColumns,
        getChips: getChips,
    };

    if (window.GT_CONFIG_REGISTRY) {
        window.GT_CONFIG_REGISTRY.register({
            name: 'liquidity',
            label: '流动性',
            panel: GT.panels.config.liquidity,
            fields: ['liquidityMode', 'liquidityPercent'],
        }, 'config-liquidity');
    }

    GT.log('panels.config.liquidity loaded');
})();
