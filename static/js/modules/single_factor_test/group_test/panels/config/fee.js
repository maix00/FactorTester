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

    var REG = window.GT_CONFIG_REGISTRY;

    // ---------------------------------------------------------------------------
    // Constants
    // ---------------------------------------------------------------------------

    var CONTAINER_ID = 'config-fee';
    var FEE_MODES = ['none', 'uniform', 'per_product'];
    var FEE_MODE_LABELS = {
        none: '无手续费',
        uniform: '统一费率',
        per_product: '分品种费率'
    };

    var _mounted = false;

    // ---------------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------------

    function $(id) { return document.getElementById(id); }

    // ---------------------------------------------------------------------------
    // Render
    // ---------------------------------------------------------------------------

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

        var group = REG.getReferenceGroup();
        if (!group) {
            container.innerHTML = '<div style="padding:24px;text-align:center;color:#888;">请先在「列表」中选择或创建一个基础组</div>';
            return;
        }

        var mode = REG.getDirty('feeMode', group.feeMode || 'none');
        var rate = REG.getDirty('feeRate', group.feeRate);
        var feeMap = REG.getDirty('feeMap', group.feeMap);
        var sensitivity = REG.getDirty('feeSensitivity', group.feeSensitivity !== undefined ? group.feeSensitivity : 1);

        var html = '';

        // Fee mode selector
        html += _makeModeSelector(mode);

        // Mode-specific editor
        if (mode === 'uniform') {
            html += _makeUniformEditor(rate);
        } else if (mode === 'per_product') {
            // Per-product: button to open configFeeTable overlay in EDIT mode
            html += '<div id="' + CONTAINER_ID + '-pp-editor" style="margin-bottom:16px;padding:12px;background:#f9fafb;border-radius:6px;border:1px solid #e5e7eb;">';
            html += '<label style="font-size:13px;font-weight:600;display:block;margin-bottom:8px;">分品种费率</label>';
            html += '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">';
            html += '<button id="' + CONTAINER_ID + '-edit-fee-btn" style="padding:6px 16px;font-size:12px;border:1px solid #0078d4;border-radius:4px;background:#0078d4;color:#fff;cursor:pointer;">✏️ 编辑品种费率</button>';
            html += '<button id="' + CONTAINER_ID + '-browse-fee-btn" style="padding:6px 16px;font-size:12px;border:1px solid #0078d4;border-radius:4px;background:#fff;color:#0078d4;cursor:pointer;">📋 查看品种费率表</button>';
            html += '<span style="font-size:12px;color:#888;">修改过的费率标记为黄色，点击"编辑品种费率"设置自定义费率</span>';
            html += '</div>';
            html += '</div>';
        }

        // Sensitivity slider
        html += _makeSensitivitySlider(sensitivity);

        // --- Close-today toggle ---
        var useCT = !!REG.getDirty('useCloseToday', !!group.useCloseToday);
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

        // --- Save / Cancel bar ---
        html += _makeSaveBar();

        container.innerHTML = html;

        // Bind events
        _bindEvents(container);
    }

    function _makeSaveBar() {
        var dirty = REG.hasDirty();
        var barStyle = 'margin-top:16px;padding:12px;display:flex;align-items:center;gap:8px;';
        barStyle += 'border-top:1px solid #e5e7eb;';
        if (dirty) barStyle += 'background:#fff8e1;border-radius:6px;';
        var html = '<div id="' + CONTAINER_ID + '-savebar" style="' + barStyle + '">';
        if (dirty) {
            html += '<span style="font-size:12px;color:#f57c00;flex:1;">⚠ 有未保存的修改</span>';
        } else {
            html += '<span style="font-size:12px;color:#888;flex:1;">✓ 已保存</span>';
        }
        html += '<button id="' + CONTAINER_ID + '-save-btn" style="padding:6px 16px;font-size:12px;border:1px solid #0078d4;border-radius:4px;background:#0078d4;color:#fff;cursor:pointer;"' + (dirty ? '' : ' disabled') + '>保存</button>';
        html += '<button id="' + CONTAINER_ID + '-cancel-btn" style="padding:6px 16px;font-size:12px;border:1px solid #ccc;border-radius:4px;background:#fff;color:#333;cursor:pointer;"' + (dirty ? '' : ' disabled') + '>撤销</button>';
        html += '</div>';
        return html;
    }

    // ---------------------------------------------------------------------------
    // Event binding
    // ---------------------------------------------------------------------------

    function _bindEvents(container) {
        // Mode radio change
        var radios = container.querySelectorAll('input[name="feemode"]');
        for (var i = 0; i < radios.length; i++) {
            radios[i].addEventListener('change', function() {
                REG.setDirty('feeMode', this.value);
                render();
            });
        }

        // Uniform feeRate input
        var rateInput = $(CONTAINER_ID + '-feerate');
        if (rateInput) {
            rateInput.addEventListener('change', function() {
                var v = this.value === '' ? null : parseFloat(this.value);
                if (v !== null && (isNaN(v) || v < 0)) v = null;
                REG.setDirty('feeRate', v);
                render();
            });
        }

        // Sensitivity slider
        var slider = $(CONTAINER_ID + '-sensitivity');
        if (slider) {
            slider.addEventListener('input', function() {
                var label = $(CONTAINER_ID + '-sens-val');
                if (label) label.textContent = parseFloat(this.value).toFixed(1);
            });
            slider.addEventListener('change', function() {
                REG.setDirty('feeSensitivity', parseFloat(this.value));
                render();
            });
        }

        // Close-today toggle
        var ctToggle = $(CONTAINER_ID + '-ct-toggle');
        if (ctToggle) {
            ctToggle.addEventListener('click', function() {
                var group = REG.getReferenceGroup();
                if (!group) return;
                var current = !!REG.getDirty('useCloseToday', !!group.useCloseToday);
                REG.setDirty('useCloseToday', !current);
                render();
            });
        }

        // Save button
        var saveBtn = $(CONTAINER_ID + '-save-btn');
        if (saveBtn) {
            saveBtn.addEventListener('click', function() {
                var ok = REG.commitDirty();
                if (ok && GT.state && typeof GT.state.emit === 'function') {
                    GT.state.emit('baseGroupsChanged');
                }
                render();
            });
        }

        // Cancel (rollback) button
        var cancelBtn = $(CONTAINER_ID + '-cancel-btn');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', function() {
                REG.rollbackDirty();
                render();
            });
        }

        // Per-product edit — open configFeeTable overlay in EDIT mode
        var editFeeBtn = $(CONTAINER_ID + '-edit-fee-btn');
        if (editFeeBtn) {
            editFeeBtn.addEventListener('click', function() {
                var group = REG.getReferenceGroup();
                if (!group) return;
                // Apply current dirty state to the group for the overlay
                var current = JSON.parse(JSON.stringify(group));
                if (REG.hasDirty()) {
                    var dirtyKeys = ['feeMode', 'feeRate', 'feeMap', 'feeSensitivity', 'useCloseToday'];
                    for (var dk = 0; dk < dirtyKeys.length; dk++) {
                        var k = dirtyKeys[dk];
                        var fallback = group[k];
                        current[k] = REG.getDirty(k, fallback);
                    }
                }
                if (GT.overlays && GT.overlays.configFeeTable) {
                    GT.overlays.configFeeTable.open(current, 'edit', function() {
                        // After overlay closes, re-render to show updated fee_map
                        render();
                    });
                }
            });
        }

        // Browse fee table button — view mode
        var browseBtn = $(CONTAINER_ID + '-browse-fee-btn');
        if (browseBtn) {
            browseBtn.addEventListener('click', function() {
                var group = REG.getReferenceGroup();
                if (!group) return;
                if (GT.overlays && GT.overlays.configFeeTable) {
                    GT.overlays.configFeeTable.open(group, 'view');
                }
            });
        }
    }

    // ---------------------------------------------------------------------------
    // Event handlers
    // ---------------------------------------------------------------------------

    function _onDataChanged() {
        if (_mounted) {
            REG.rollbackDirty();
            render();
        }
    }

    // ---------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------

    function mount() {
        _mounted = true;

        GT.state.on('baseGroupsChanged', _onDataChanged);
        GT.state.on('activeBaseGroupChanged', _onDataChanged);

        render();
    }

    function unmount() {
        _mounted = false;
        GT.state.off('baseGroupsChanged', _onDataChanged);
        GT.state.off('activeBaseGroupChanged', _onDataChanged);
    }

    function refresh() {
        if (_mounted) render();
    }

    // ---------------------------------------------------------------------------
    // Config chips (consumed by list panel via REG.getChips)
    // ---------------------------------------------------------------------------

    /**
     * getChips(group) → [{{label, html, style, onClick}}]
     *
     * Rules:
     *  - 'none':         no chips at all
     *  - 'uniform':      [统一费率: 2.500000]  +  [费率倍数: 1.5x]  if sensitivity ≠ 1
     *  - 'per_product':  [分品种费率] clickable → overlay
     *                      if feeMap ≠ null & has entries → [分品种费率(自定义)] instead
     *                    + [费率倍数: 1.5x]  if sensitivity ≠ 1
     *                    + [平今/平昨]  always
     *
     * @param {object} group — base group from datamodel
     * @returns {{label, html, style, onClick}[]}
     */
    function getChips(group) {
        if (!group) return [];
        var mode = group.feeMode || 'none';
        if (mode === 'none') return [];

        var chips = [];
        var chipPlain = 'display:inline-block;background:#e5e7eb;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;color:#374151;';
        var chipClickable = 'display:inline-block;cursor:pointer;background:#c7d2fe;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;color:#312e81;';

        if (mode === 'uniform') {
            // 统一费率 chip
            var rateStr = (group.feeRate != null) ? Number(group.feeRate).toFixed(6) : '—';
            chips.push({
                label: 'fee-uniform',
                html: '💰 统一费率:' + rateStr,
                style: chipPlain
            });
        } else if (mode === 'per_product') {
            // 分品种费率 chip — clickable → configFeeTable overlay (VIEW mode)
            var feeMap = group.feeMap;
            var hasCustom = feeMap && typeof feeMap === 'object' && Object.keys(feeMap).length > 0;
            chips.push({
                label: 'fee-per-product',
                html: hasCustom ? '📊 分品种费率(自定义)' : '📊 分品种费率',
                style: chipClickable,
                onClick: function(chipEl, g) {
                    if (GT.overlays && GT.overlays.configFeeTable) {
                        GT.overlays.configFeeTable.open(g, 'view');
                    }
                }
            });
        }

        // 费率倍数 chip (if ≠ 1)
        var sens = group.feeSensitivity;
        if (sens != null && sens !== 1) {
            chips.push({
                label: 'fee-sensitivity',
                html: '⚡ 费率倍数:' + Number(sens).toFixed(1) + 'x',
                style: chipPlain
            });
        }

        // 平今/平昨 chip (only for per_product)
        if (mode === 'per_product') {
            var isCT = !!group.useCloseToday;
            chips.push({
                label: 'fee-close-today',
                html: isCT ? '🗓️ 平今' : '🗓️ 平昨',
                style: chipPlain
            });
        }

        return chips;
    }

    // ---------------------------------------------------------------------------
    // Category-3 table column contribution
    // ---------------------------------------------------------------------------

    /**
     * getTableColumns — called by category-1 list panels to extend their table.
     * Returns column definitions for fee-related columns.
     */
    function getTableColumns() {
        return []; // chips are now served via getChips; no separate columns needed
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
        getChips: getChips,
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
