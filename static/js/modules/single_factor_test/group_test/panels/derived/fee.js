/**
 * panels/derived/fee.js — Derived group fee strategy panel (Tab 2, sub-tab "费率")
 *
 * Phase 4 UI panel. Renders the fee strategy editor for the selected derived
 * group node. Supports inheritance toggle: ON = inherit from parent chain,
 * OFF = override with full fee controls.
 *
 * Contract (provided by datamodel & state):
 *   GT.state.getActiveDerivedNodeId() → id|null
 *   GT.state.on('activeDerivedNodeChanged', cb)
 *   GT.state.on('derivedGraphChanged', cb)
 *   GT.datamodel.derived_graph.get(id) → node|null
 *   GT.datamodel.derived_graph.update(id, patch)
 *   GT.datamodel.fee_strategy.resolveFee(nodeId) → {mode, rate, feeMap}
 *   GT.datamodel.fee_strategy.resolveParam(nodeId, 'feeOverride') → same
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.derived) { GT.panels.derived = {}; }

    // ---------------------------------------------------------------------------
    // Constants
    // ---------------------------------------------------------------------------

    var CONTAINER_ID = 'derived-fee-panel';
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

    function _getNode() {
        var id = GT.state.getActiveDerivedNodeId();
        if (!id) return null;
        return GT.datamodel.derived_graph.get(id);
    }

    function _hasOverride(node) {
        return node && node.feeOverride !== null && node.feeOverride !== undefined;
    }

    /**
     * Resolve the effective fee for display.
     * If node has override, use it. Otherwise resolve from chain.
     */
    function _effectiveFee(node) {
        if (!node) return { mode: 'none', rate: null, feeMap: null };
        if (_hasOverride(node)) {
            return JSON.parse(JSON.stringify(node.feeOverride));
        }
        return GT.datamodel.fee_strategy.resolveFee(node.id);
    }

    // ---------------------------------------------------------------------------
    // Inheritance info
    // ---------------------------------------------------------------------------

    /**
     * Walk up the chain to find where the effective fee comes from.
     * Returns { source: 'override'|'parent'|'baseGroup'|'default', sourceName, sourceId }
     */
    function _resolveSource(nodeId) {
        var node = GT.datamodel.derived_graph.get(nodeId);
        if (!node) return { source: 'default', sourceName: '系统默认', sourceId: null };

        if (_hasOverride(node)) {
            return { source: 'override', sourceName: '当前节点覆盖', sourceId: node.id };
        }
        if (node.parentId) {
            var parentResult = _resolveSource(node.parentId);
            if (parentResult.source !== 'default') return parentResult;
        }
        if (node.baseGroupId) {
            var bg = GT.datamodel.base_groups.get(node.baseGroupId);
            if (bg && bg.feeMode && bg.feeMode !== 'none') {
                return { source: 'baseGroup', sourceName: '基础组: ' + (bg.name || node.baseGroupId), sourceId: node.baseGroupId };
            }
        }
        return { source: 'default', sourceName: '系统默认 (无手续费)', sourceId: null };
    }

    // ---------------------------------------------------------------------------
    // Sub-renderers (reuse base/fee.js patterns)
    // ---------------------------------------------------------------------------

    function _makeInheritToggle(isInheriting, sourceInfo) {
        var html = '<div style="margin-bottom:16px;display:flex;align-items:center;gap:12px;">';
        html += '<label style="font-size:13px;font-weight:600;">策略来源</label>';
        html += '<select id="' + CONTAINER_ID + '-inherit-toggle" style="padding:4px 8px;border:1px solid #ccc;border-radius:4px;font-size:13px;">';
        html += '<option value="inherit"' + (isInheriting ? ' selected' : '') + '>继承 (来自: ' + sourceInfo.sourceName + ')</option>';
        html += '<option value="override"' + (!isInheriting ? ' selected' : '') + '>覆盖 (自定义)</option>';
        html += '</select>';
        html += '</div>';
        return html;
    }

    function _makeInheritedDisplay(fee) {
        var modeLabel = FEE_MODE_LABELS[fee.mode] || fee.mode;
        var html = '<div style="padding:12px;background:#f0f7ff;border-radius:6px;border:1px solid #b3d4fc;">';
        html += '<div style="font-size:12px;color:#666;margin-bottom:6px;">当前有效费率 (继承)</div>';
        html += '<div style="font-size:14px;font-weight:600;">模式: ' + modeLabel + '</div>';

        if (fee.mode === 'uniform') {
            html += '<div style="margin-top:4px;">费率: ' + (fee.rate !== null ? fee.rate + ' 万分比' : '未设置') + '</div>';
        } else if (fee.mode === 'per_product' || fee.mode === 'custom') {
            var map = fee.feeMap || {};
            var keys = Object.keys(map);
            if (keys.length > 0) {
                html += '<div style="margin-top:4px;font-size:12px;">品种数: ' + keys.length + '</div>';
            } else {
                html += '<div style="margin-top:4px;font-size:12px;">无品种配置</div>';
            }
        }

        html += '</div>';
        return html;
    }

    function _makeModeSelector(currentMode) {
        var html = '<div style="margin-bottom:16px;">';
        html += '<label style="font-size:13px;font-weight:600;display:block;margin-bottom:8px;">费率模式</label>';
        html += '<div id="' + CONTAINER_ID + '-mode-group" style="display:flex;gap:12px;">';
        for (var i = 0; i < FEE_MODES.length; i++) {
            var mode = FEE_MODES[i];
            var checked = mode === currentMode ? 'checked' : '';
            html += '<label style="font-size:13px;cursor:pointer;display:flex;align-items:center;gap:4px;">';
            html += '<input type="radio" name="derived-feemode" value="' + mode + '" ' + checked + ' style="margin:0;">';
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
            + '<button class="grouptest-derived-fee-pp-del" data-pp-product="' + product + '" style="padding:1px 6px;font-size:12px;border:1px solid #d32f2f;border-radius:3px;background:#fff;color:#d32f2f;cursor:pointer;">✕</button>'
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

    // ---------------------------------------------------------------------------
    // Save
    // ---------------------------------------------------------------------------

    function _saveOverride(patch) {
        if (!_activeId) return;
        try {
            GT.datamodel.derived_graph.update(_activeId, patch);
        } catch (err) {
            alert('保存费率设置失败: ' + err.message);
        }
    }

    function _clearOverride() {
        if (!_activeId) return;
        try {
            GT.datamodel.derived_graph.update(_activeId, { feeOverride: null });
        } catch (err) {
            alert('清除费率覆盖失败: ' + err.message);
        }
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
        var effFee = _effectiveFee(node);

        var html = '';

        // Inherit toggle
        html += _makeInheritToggle(isInheriting, sourceInfo);

        if (isInheriting) {
            // Show resolved effective values, read-only
            html += _makeInheritedDisplay(effFee);
        } else {
            // Full editor mode
            var override = node.feeOverride || {};
            var mode = override.mode || 'none';
            var rate = override.rate;
            var feeMap = override.feeMap;
            var sensitivity = override.feeSensitivity !== undefined ? override.feeSensitivity : 0;

            html += _makeModeSelector(mode);
            if (mode === 'uniform') {
                html += _makeUniformEditor(rate);
            } else if (mode === 'per_product') {
                html += _makePerProductEditor(feeMap);
            }
            html += _makeSensitivitySlider(sensitivity);
        }

        container.innerHTML = html;
        _bindEvents(container);
    }

    // ---------------------------------------------------------------------------
    // Event binding
    // ---------------------------------------------------------------------------

    function _bindEvents(container) {
        // Inherit toggle
        var inheritSelect = $(CONTAINER_ID + '-inherit-toggle');
        if (inheritSelect) {
            inheritSelect.addEventListener('change', function() {
                if (this.value === 'inherit') {
                    _clearOverride();
                } else {
                    // Switch to override: initialize with current effective fee
                    var effFee = _effectiveFee(_getNode());
                    effFee.feeSensitivity = 0;
                    _saveOverride({ feeOverride: effFee });
                }
            });
        }

        // Mode radio change
        var radios = container.querySelectorAll('input[name="derived-feemode"]');
        for (var i = 0; i < radios.length; i++) {
            radios[i].addEventListener('change', function() {
                var node = _getNode();
                if (!node) return;
                var override = node.feeOverride ? JSON.parse(JSON.stringify(node.feeOverride)) : { mode: 'none', rate: null, feeMap: null };
                override.mode = this.value;
                _saveOverride({ feeOverride: override });
            });
        }

        // Uniform feeRate input
        var rateInput = $(CONTAINER_ID + '-feerate');
        if (rateInput) {
            rateInput.addEventListener('change', function() {
                var node = _getNode();
                if (!node) return;
                var override = node.feeOverride ? JSON.parse(JSON.stringify(node.feeOverride)) : { mode: 'uniform', rate: null, feeMap: null };
                var v = this.value === '' ? null : parseFloat(this.value);
                if (v !== null && (isNaN(v) || v < 0)) v = null;
                override.rate = v;
                _saveOverride({ feeOverride: override });
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

                var node = _getNode();
                if (!node) return;
                var override = node.feeOverride ? JSON.parse(JSON.stringify(node.feeOverride)) : { mode: 'per_product', rate: null, feeMap: {} };
                override.feeMap = override.feeMap || {};
                override.feeMap[product] = rate;
                _saveOverride({ feeOverride: override });

                newProduct.value = '';
                newRate.value = '';
            });
        }

        // Per-product delete — delegate via container
        container.addEventListener('click', function(e) {
            if (e.target.classList.contains('grouptest-derived-fee-pp-del')) {
                var product = e.target.getAttribute('data-pp-product');
                if (!product) return;
                if (!confirm('确定删除品种 "' + product + '" 的费率吗？')) return;

                var node = _getNode();
                if (!node) return;
                var override = node.feeOverride ? JSON.parse(JSON.stringify(node.feeOverride)) : { mode: 'per_product', rate: null, feeMap: {} };
                override.feeMap = override.feeMap || {};
                delete override.feeMap[product];
                if (Object.keys(override.feeMap).length === 0) {
                    override.feeMap = null;
                }
                _saveOverride({ feeOverride: override });
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
                var node = _getNode();
                if (!node) return;
                var override = node.feeOverride ? JSON.parse(JSON.stringify(node.feeOverride)) : { mode: 'none', rate: null, feeMap: null };
                override.feeSensitivity = parseFloat(this.value);
                _saveOverride({ feeOverride: override });
            });
        }
    }

    // ---------------------------------------------------------------------------
    // Event handlers
    // ---------------------------------------------------------------------------

    function _onDerivedNodeChanged() {
        if (_mounted) render();
    }

    function _onDerivedGraphChanged() {
        if (_mounted) render();
    }

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

    function refresh() {
        if (_mounted) render();
    }

    // ---------------------------------------------------------------------------
    // Export
    // ---------------------------------------------------------------------------

    GT.panels.derived.fee = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
    };

    GT.log('panels.derived.fee loaded');
})();
