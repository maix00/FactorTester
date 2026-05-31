/**
 * panels/config/fee.js — Fee strategy + close-today toggle (category-3)
 *
 * Reads the active base group's feeMode/feeRate/feeMap/feeSensitivity/useCloseToday,
 * renders appropriate controls, and saves changes via datamodel.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.config) { GT.panels.config = {}; }

    // ---------------------------------------------------------------------------
    // Constants
    // ---------------------------------------------------------------------------

    var CONTAINER_ID = 'config-fee';
    var FEE_MODES = ['none', 'uniform', 'per_product', 'custom'];
    var FEE_MODE_LABELS = {
        none: '无手续费',
        uniform: '统一费率',
        per_product: '分品种费率',
        custom: '自定义因子'
    };

    var _mounted = false;
    var _activeId = null;

    // ---------------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------------

    function $(id) { return document.getElementById(id); }

    /** Extract group IDs from edit selection (supports {id:true} object and {groupIds:[]} formats) */
    function _getEditGroupIds(sel) {
        if (!sel) return [];
        if (Array.isArray(sel.groupIds)) return sel.groupIds;
        if (Array.isArray(sel)) return sel;
        // Pure object like {id1: true, id2: true}
        if (typeof sel === 'object') {
            return Object.keys(sel).filter(function(k) { return sel[k]; });
        }
        return [];
    }

    // ---------------------------------------------------------------------------
    // Render
    // ---------------------------------------------------------------------------

    function _getGroup() {
        var mode = GT.ui && GT.ui.getPanelMode ? GT.ui.getPanelMode() : 'list';
        
        // In add mode, read from draft
        if (mode === 'add') {
            var draft = GT.ui && GT.ui.getAddDraft ? GT.ui.getAddDraft() : null;
            if (!draft) return null;
            return {
                id: '_add_draft',
                feeMode: draft.feeMode || 'none',
                feeRate: draft.feeRate,
                feeMap: draft.feeMap,
                feeSensitivity: draft.feeSensitivity,
                useCloseToday: draft.useCloseToday || false,
            };
        }
        
        // In edit mode, use first selected group as reference
        if (mode === 'edit') {
            var sel = GT.ui && GT.ui.getEditSelection ? GT.ui.getEditSelection() : null;
            var groupIds = _getEditGroupIds(sel);
            if (groupIds.length === 0) return null;
            return GT.datamodel.base_groups.get(groupIds[0]);
        }
        
        // List mode: use active group
        var id = GT.state.getActiveBaseGroupId();
        if (!id) return null;
        return GT.datamodel.base_groups.get(id);
    }

    function _save(patch) {
        var mode = GT.ui && GT.ui.getPanelMode ? GT.ui.getPanelMode() : 'list';
        
        // In add mode, save to draft
        if (mode === 'add') {
            if (GT.ui && typeof GT.ui.updateAddDraft === 'function') {
                GT.ui.updateAddDraft(patch);
            }
            // Re-render to show changes (fee.js re-renders on its own)
            render();
            return;
        }

        // In edit mode, apply to all selected groups
        if (mode === 'edit') {
            var sel = GT.ui && GT.ui.getEditSelection ? GT.ui.getEditSelection() : null;
            var ids = _getEditGroupIds(sel);
            for (var i = 0; i < ids.length; i++) {
                try {
                    GT.datamodel.base_groups.update(ids[i], patch);
                } catch (err) { /* skip individual failures */ }
            }
            render();
            return;
        }
        
        if (!_activeId) return;
        try {
            GT.datamodel.base_groups.update(_activeId, patch);
        } catch (err) {
            alert('保存费率设置失败: ' + err.message);
        }
    }

    function _makeModeSelector(currentMode) {
        var html = '<div style="margin-bottom:16px;">';
        html += '<label style="font-size:13px;font-weight:600;display:block;margin-bottom:8px;">费率模式</label>';
        html += '<div id="' + CONTAINER_ID + '-mode-group" style="display:flex;gap:12px;">';
        for (var i = 0; i < FEE_MODES.length; i++) {
            var mode = FEE_MODES[i];
            var checked = mode === currentMode ? 'checked' : '';
            html += '<label style="font-size:13px;cursor:pointer;display:flex;align-items:center;gap:4px;">';
            html += '<input type="radio" name="feemode" value="' + mode + '" ' + checked + ' style="margin:0;">';
            html += FEE_MODE_LABELS[mode];
            html += '</label>';
        }
        html += '</div></div>';
        return html;
    }

    function _makeUniformEditor(rate) {
        var rateVal = (rate !== null && rate !== undefined) ? rate : '';
        var html = '<div id="' + CONTAINER_ID + '-uniform-editor" style="margin-bottom:16px;padding:12px;background:#f9fafb;border-radius:6px;border:1px solid #e5e7eb;">';
        html += '<label style="font-size:13px;font-weight:600;display:block;margin-bottom:8px;">统一费率</label>';
        html += '<div style="display:flex;align-items:center;gap:8px;">';
        html += '<input type="number" id="' + CONTAINER_ID + '-feerate" value="' + rateVal + '" step="0.01" min="0" style="width:100px;padding:6px;border:1px solid #ddd;border-radius:4px;" placeholder="0.00">';
        html += '<span style="font-size:12px;color:#666;">万分比 (e.g. 2.5 = 0.025%)</span>';
        html += '</div>';
        html += '</div>';
        return html;
    }

    function _makePerProductEditor(feeMap) {
        var map = feeMap || {};
        var html = '<div id="' + CONTAINER_ID + '-pp-editor" style="margin-bottom:16px;padding:12px;background:#f9fafb;border-radius:6px;border:1px solid #e5e7eb;">';
        html += '<label style="font-size:13px;font-weight:600;display:block;margin-bottom:8px;">分品种费率</label>';

        html += '<table style="width:100%;border-collapse:collapse;font-size:13px;">';
        html += '<thead><tr style="background:#f0f2f5;">';
        html += '<th style="padding:6px 8px;text-align:left;">品种</th>';
        html += '<th style="padding:6px 8px;text-align:left;">费率 (万分比)</th>';
        html += '<th style="padding:6px 8px;text-align:center;width:60px;">操作</th>';
        html += '</tr></thead><tbody id="' + CONTAINER_ID + '-pp-rows">';

        var keys = Object.keys(map).sort();
        for (var i = 0; i < keys.length; i++) {
            html += _makePPRow(keys[i], map[keys[i]]);
        }

        html += '</tbody></table>';

        // Add row
        html += '<div style="margin-top:8px;display:flex;gap:8px;">';
        html += '<input type="text" id="' + CONTAINER_ID + '-pp-new-product" placeholder="品种代码" style="width:100px;padding:4px 6px;border:1px solid #ddd;border-radius:4px;font-size:13px;">';
        html += '<input type="number" id="' + CONTAINER_ID + '-pp-new-rate" step="0.01" min="0" placeholder="费率" style="width:80px;padding:4px 6px;border:1px solid #ddd;border-radius:4px;font-size:13px;">';
        html += '<button id="' + CONTAINER_ID + '-pp-add-btn" style="padding:4px 12px;font-size:12px;border:1px solid #0078d4;border-radius:4px;background:#0078d4;color:#fff;cursor:pointer;">+ 添加</button>';
        html += '</div>';
        html += '</div>';
        return html;
    }

    function _makePPRow(product, rate) {
        return '<tr data-pp-product="' + product + '">'
            + '<td style="padding:4px 8px;">' + product + '</td>'
            + '<td style="padding:4px 8px;">' + rate + '</td>'
            + '<td style="padding:4px 8px;text-align:center;">'
            + '<button class="grouptest-fee-pp-del" data-pp-product="' + product + '" style="padding:1px 6px;font-size:12px;border:1px solid #d32f2f;border-radius:3px;background:#fff;color:#d32f2f;cursor:pointer;">✕</button>'
            + '</td></tr>';
    }

    function _makeSensitivitySlider(value) {
        var val = (value !== null && value !== undefined) ? value : 1;
        var html = '<div style="margin-bottom:16px;">';
        html += '<label style="font-size:13px;font-weight:600;display:block;margin-bottom:8px;">费率倍数: <span id="' + CONTAINER_ID + '-sens-val">' + val.toFixed(1) + 'x</span></label>';
        html += '<input type="range" id="' + CONTAINER_ID + '-sensitivity" value="' + val + '" min="0" max="5" step="0.1" style="width:100%;max-width:300px;">';
        html += '<div style="font-size:11px;color:#888;">1x = 正常费率，0 = 忽略手续费，5x = 五倍费率压力测试</div>';
        html += '</div>';
        return html;
    }

    function render() {
        var container = $(CONTAINER_ID);
        if (!container) return;

        var group = _getGroup();
        if (!group) {
            container.innerHTML = '<div style="padding:24px;text-align:center;color:#888;">请先在「列表」中选择或创建一个基础组</div>';
            _activeId = null;
            return;
        }

        _activeId = group.id;
        var mode = group.feeMode || 'none';
        var rate = group.feeRate;
        var feeMap = group.feeMap;
        var sensitivity = group.feeSensitivity !== undefined ? group.feeSensitivity : 1;

        var html = '';

        // Fee mode selector
        html += _makeModeSelector(mode);

        // Mode-specific editor
        if (mode === 'uniform') {
            html += _makeUniformEditor(rate);
        } else if (mode === 'per_product') {
            html += _makePerProductEditor(feeMap);
        }

        // Sensitivity slider
        html += _makeSensitivitySlider(sensitivity);

        // --- Close-today toggle ---
        var useCT = !!group.useCloseToday;
        var ctStateColor = useCT ? '#d97706' : '#0078d4';
        var ctStateText = useCT ? '平今仓' : '平昨仓';
        var ctBtnText = useCT ? '切换为平昨仓' : '切换为平今仓';
        var ctBtnClass = useCT ? 'btn-outline-warning' : 'btn-outline-secondary';
        html += '<div style="margin-top:12px;padding-top:12px;border-top:1px solid #e5e7eb;">';
        html += '<label style="font-size:13px;font-weight:600;display:block;margin-bottom:8px;">平仓口径</label>';
        html += '<div style="display:flex;align-items:center;gap:8px;">';
        html += '<strong id="' + CONTAINER_ID + '-ct-state" style="font-size:14px;color:' + ctStateColor + ';">' + ctStateText + '</strong>';
        html += '<button id="' + CONTAINER_ID + '-ct-toggle" class="btn btn-sm ' + ctBtnClass + '" style="padding:4px 14px;">' + ctBtnText + '</button>';
        html += '<span style="font-size:12px;color:#888;">影响品种费率表中平今/平昨比率的选择</span>';
        html += '</div></div>';

        container.innerHTML = html;

        // Bind events
        _bindEvents(container);
    }

    // ---------------------------------------------------------------------------
    // Event binding
    // ---------------------------------------------------------------------------

    function _bindEvents(container) {
        // Mode radio change
        var radios = container.querySelectorAll('input[name="feemode"]');
        for (var i = 0; i < radios.length; i++) {
            radios[i].addEventListener('change', function() {
                _save({ feeMode: this.value });
                // re-render to show/hide mode-specific editors
                // (happens via baseGroupsChanged event)
            });
        }

        // Uniform feeRate input
        var rateInput = $(CONTAINER_ID + '-feerate');
        if (rateInput) {
            rateInput.addEventListener('change', function() {
                var v = this.value === '' ? null : parseFloat(this.value);
                if (v !== null && (isNaN(v) || v < 0)) v = null;
                _save({ feeRate: v });
            });
        }

        // Per-product add
        var addBtn = $(CONTAINER_ID + '-pp-add-btn');
        var newProduct = $(CONTAINER_ID + '-pp-new-product');
        var newRate = $(CONTAINER_ID + '-pp-new-rate');
        if (addBtn && newProduct && newRate) {
            addBtn.addEventListener('click', function() {
                var product = newProduct.value.trim();
                var rate = parseFloat(newRate.value);
                if (!product) { alert('请输入品种代码'); return; }
                if (isNaN(rate) || rate < 0) { alert('请输入有效费率'); return; }

                var group = _getGroup();
                if (!group) return;
                var map = group.feeMap ? JSON.parse(JSON.stringify(group.feeMap)) : {};
                map[product] = rate;
                _save({ feeMap: map });

                newProduct.value = '';
                newRate.value = '';
            });
        }

        // Per-product delete — delegate via container
        container.addEventListener('click', function(e) {
            if (e.target.classList.contains('grouptest-fee-pp-del')) {
                var product = e.target.getAttribute('data-pp-product');
                if (!product) return;
                if (!confirm('确定删除品种 "' + product + '" 的费率吗？')) return;

                var group = _getGroup();
                if (!group) return;
                var map = group.feeMap ? JSON.parse(JSON.stringify(group.feeMap)) : {};
                delete map[product];
                _save({ feeMap: Object.keys(map).length > 0 ? map : null });
            }
        });

        // Sensitivity slider
        var slider = $(CONTAINER_ID + '-sensitivity');
        if (slider) {
            slider.addEventListener('input', function() {
                var label = $(CONTAINER_ID + '-sens-val');
                if (label) label.textContent = parseFloat(this.value).toFixed(1);
            });
            slider.addEventListener('change', function() {
                _save({ feeSensitivity: parseFloat(this.value) });
            });
        }

        // Close-today toggle
        var ctToggle = $(CONTAINER_ID + '-ct-toggle');
        if (ctToggle) {
            ctToggle.addEventListener('click', function() {
                var group = _getGroup();
                if (!group) return;
                _save({ useCloseToday: !group.useCloseToday });
            });
        }
    }

    // ---------------------------------------------------------------------------
    // Event handlers
    // ---------------------------------------------------------------------------

    function _onDataChanged() {
        if (_mounted) render();
    }

    // ---------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------

    function mount() {
        _mounted = true;
        _activeId = GT.state.getActiveBaseGroupId();

        GT.state.on('baseGroupsChanged', _onDataChanged);
        GT.state.on('activeBaseGroupChanged', _onDataChanged);

        render();
    }

    function unmount() {
        _mounted = false;
        _activeId = null;
        GT.state.off('baseGroupsChanged', _onDataChanged);
        GT.state.off('activeBaseGroupChanged', _onDataChanged);
    }

    function refresh() {
        if (_mounted) render();
    }

    // ---------------------------------------------------------------------------
    // Category-3 table column contribution
    // ---------------------------------------------------------------------------

    /**
     * getTableColumns — called by category-1 list panels to extend their table.
     * Returns column definitions for fee-related columns.
     */
    function getTableColumns() {
        return [
            {
                key: 'fee',
                label: '手续费',
                render: function(group) {
                    var map = { 'none': '无', 'percent': '百分比', 'fixed': '固定', 'table': '费率表', 'strategy': '策略' };
                    return map[group.feeMode] || (group.feeMode || '—');
                }
            },
            {
                key: 'closeToday',
                label: '平今/平昨',
                render: function(group) {
                    if (group.feeMode === 'none' || group.feeMode === 'fixed') return '—';
                    return group.useCloseToday ? '平今' : '平昨';
                }
            },
            {
                key: 'feeSensitivity',
                label: '费率倍数',
                render: function(group) {
                    return group.feeSensitivity != null ? group.feeSensitivity.toFixed(1) + 'x' : '—';
                }
            }
        ];
    }

    // ---------------------------------------------------------------------------
    // Export
    // ---------------------------------------------------------------------------

    GT.panels.config = GT.panels.config || {};
    GT.panels.config.fee = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
        getTableColumns: getTableColumns,
    };

    // Register as category-3 config panel
    if (window.GT_CONFIG_REGISTRY) {
        window.GT_CONFIG_REGISTRY.register({
            name: 'fee',
            label: '费率',
            panel: GT.panels.config.fee,
        }, 'config-fee');
    }

    GT.log('panels.config.fee loaded');
})();
