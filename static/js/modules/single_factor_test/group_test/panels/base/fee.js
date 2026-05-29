/**
 * panels/base/fee.js — Fee strategy config panel (Tab 1, sub-tab "费率策略")
 *
 * Reads the active base group's feeMode/feeRate/feeMap/feeSensitivity,
 * renders appropriate controls, and saves changes via datamodel.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.base) { GT.panels.base = {}; }

    // ---------------------------------------------------------------------------
    // Constants
    // ---------------------------------------------------------------------------

    var CONTAINER_ID = 'base-fee-panel';
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

    // ---------------------------------------------------------------------------
    // Render
    // ---------------------------------------------------------------------------

    function _getGroup() {
        var id = GT.state.getActiveBaseGroupId();
        if (!id) return null;
        return GT.datamodel.base_groups.get(id);
    }

    function _save(patch) {
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
        var val = (value !== null && value !== undefined) ? value : 0;
        var html = '<div style="margin-bottom:16px;">';
        html += '<label style="font-size:13px;font-weight:600;display:block;margin-bottom:8px;">费率灵敏度: <span id="' + CONTAINER_ID + '-sens-val">' + val.toFixed(1) + '</span></label>';
        html += '<input type="range" id="' + CONTAINER_ID + '-sensitivity" value="' + val + '" min="0" max="2" step="0.1" style="width:100%;max-width:300px;">';
        html += '<div style="font-size:11px;color:#888;">0 = 不敏感，2 = 极高敏感</div>';
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
        var sensitivity = group.feeSensitivity !== undefined ? group.feeSensitivity : 0;

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
    // Export
    // ---------------------------------------------------------------------------

    GT.panels.base.fee = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
    };

    GT.log('panels.base.fee loaded');
})();
