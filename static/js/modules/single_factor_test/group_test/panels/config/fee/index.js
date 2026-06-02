/**
 * panels/config/fee/index.js — Fee data layer + config panel (merged)
 *
 * Data layer (GT.fee):
 *   - fetchFeeTable / getFeeRows / buildFeeMap / hasFeeData
 *   - Fee modifications (getModifications / applyModifications)
 *
 * Config panel (GT.panels.config.fee):
 *   - Per-group fee mode selection (none/uniform/per_product)
 *   - Dirty workspace via REG.setDirty / commitDirty / rollbackDirty
 *   - getChips for list aggregation
 *   - Uses GT.overlays.configFeeTable for per-product editing
 *
 * Dependencies:
 *   - GT_CONFIG_REGISTRY (registry.js)
 *   - GT.overlays.configFeeTable (overlay.js)
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    // ═══════════════════════════════════════════════════════════════════════════
    // Data layer — Fee table management (GT.fee)
    // ═══════════════════════════════════════════════════════════════════════════

    var _feeTableData = [];          // 原始费率数据（从后端获取，不可变）
    var _feeModifications = {};      // 用户修改：{variety_code: {open_ratio, close_ratio, closetoday_ratio}}
    var _useCloseToday = false;       // 平今仓/平昨仓
    var _feeNotice = null;            // 当前费率表来源提示

    // ── Fee data API ───────────────────────────────────────────────────────────

    /** Fetch fee table from backend (cache in _feeTableData). */
    function fetchFeeTable(forceRefresh) {
        if (_feeTableData.length > 0 && !forceRefresh) {
            return Promise.resolve(_feeTableData);
        }
        return fetch('/get_fee_table', {
            method: 'POST',
            headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' }
        })
        .then(function(r) {
            return r.json();
        })
        .then(function(data) {
            if (data && data.success && Array.isArray(data.rows)) {
                _feeTableData = data.rows;
                _feeNotice = data.fee_notice ? {
                    source: data.fee_source || 'current_snapshot',
                    sourceDate: data.fee_source_date || null,
                    message: data.fee_notice
                } : null;
            }
            return _feeTableData;
        })
        .catch(function(err) {
            console.error('[GT.fee.fetchFeeTable] FAILED:', err);
            return _feeTableData;
        });
    }

    /** Get raw fee rows (immutable backend data), normalised with a `code` alias. */
    function getFeeRows() {
        for (var i = 0; i < _feeTableData.length; i++) {
            if (_feeTableData[i].variety_code && !_feeTableData[i].code) {
                _feeTableData[i].code = _feeTableData[i].variety_code;
            }
        }
        return _feeTableData;
    }

    /** Build a fee map {variety_code: {open_ratio, close_ratio, closetoday_ratio}} from raw data. */
    function buildFeeMap() {
        var map = {};
        for (var i = 0; i < _feeTableData.length; i++) {
            var r = _feeTableData[i];
            var code = (r.variety_code || r.code || '').toLowerCase();
            map[code] = {
                open_ratio: r.open_ratio,
                close_ratio: r.close_ratio,
                closetoday_ratio: r.closetoday_ratio
            };
        }
        return map;
    }

    /** Whether fee data has been fetched. */
    function hasFeeData() {
        return _feeTableData.length > 0;
    }

    function getFeeNotice() {
        return _feeNotice ? JSON.parse(JSON.stringify(_feeNotice)) : null;
    }

    /** Get fee modifications snapshot. */
    function getModifications() {
        return JSON.parse(JSON.stringify(_feeModifications));
    }

    /** Apply fee modifications snapshot. */
    function applyModifications(mods) {
        _feeModifications = mods && typeof mods === 'object' ? JSON.parse(JSON.stringify(mods)) : {};
        if (GT.events && typeof GT.events.emit === 'function') {
            GT.events.emit('feeDataChanged');
        }
    }

    /** Whether close-today mode is active (checks dirty workspace first). */
    function useCloseToday() {
        var REG = window.GT_CONFIG_REGISTRY;
        if (REG) {
            var group = REG.getReferenceGroup();
            if (group) return !!REG.getDirty('useCloseToday', !!group.useCloseToday);
        }
        return _useCloseToday;
    }

    /** Set close-today mode. */
    function setUseCloseToday(v) {
        _useCloseToday = !!v;
        if (GT.events && typeof GT.events.emit === 'function') {
            GT.events.emit('feeDataChanged');
        }
    }

    /**
     * Idempotently ensure the global fee table is loaded from the backend.
     * Always returns a fresh fee map built from loaded data.
     *
     * @returns {Promise<object>} — {variety_code: {open_ratio, close_ratio, closetoday_ratio}}
     */
    function ensureFeeData() {
        return fetchFeeTable(true).then(function() {
            return buildFeeMap();
        });
    }

    function bindFeeControls() {
        // Legacy hook kept for app.js init compatibility.
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // Config panel — Per-group fee settings (GT.panels.config.fee)
    // ═══════════════════════════════════════════════════════════════════════════

    var REG = null; // GT_CONFIG_REGISTRY, set on mount
    var _mounted = false;

    var CONTAINER_ID = 'config-fee';
    var FEE_MODES = ['none', 'uniform', 'per_product'];

    // ── DOM helpers ────────────────────────────────────────────────────────────

    function $(id) { return document.getElementById(id); }

    function escapeHTML(str) { return GT.escapeHTML(str); }

    // ── Rendering ──────────────────────────────────────────────────────────────

    function render() {
        if (!_mounted) return;
        if (!REG) REG = window.GT_CONFIG_REGISTRY;

        var group = REG ? REG.getReferenceGroup() : null;
        if (!group) return;

        var container = $(CONTAINER_ID);
        if (!container) return;

        var mode = REG.getDirty('feeMode', group.feeMode || GS.getFieldDefault('feeMode'));
        var feeRate = REG.getDirty('feeRate', group.feeRate != null ? group.feeRate : 0.0025);
        var sensitivity = REG.getDirty('feeSensitivity', group.feeSensitivity != null ? group.feeSensitivity : 1);
        var useCT = REG.getDirty('useCloseToday', !!group.useCloseToday);
        var feeMap = REG.getDirty('feeMap', group.feeMap);

        var html = '';

        // ── Mode selector ──
        html += '<div style="margin-bottom:16px;">';
        html += '<label style="font-size:13px;font-weight:600;display:block;margin-bottom:6px;">费率模式</label>';
        html += '<div style="display:flex;gap:6px;flex-wrap:wrap;">';
        for (var mi = 0; mi < FEE_MODES.length; mi++) {
            var m = FEE_MODES[mi];
            var mLabel = m === 'none' ? '不使用手续费' : (m === 'uniform' ? '统一费率' : '分品种费率');
            var active = (m === mode);
            html += '<button id="' + CONTAINER_ID + '-mode-' + m + '" style="padding:6px 14px;font-size:12px;border:1px solid ' + (active ? '#0078d4' : '#ccc') + ';border-radius:4px;background:' + (active ? '#0078d4' : '#fff') + ';color:' + (active ? '#fff' : '#333') + ';cursor:pointer;">' + mLabel + '</button>';
        }
        html += '</div></div>';

        // ── Mode-specific UI ──
        if (mode === 'uniform') {
            html += '<div style="margin-bottom:16px;">';
            html += '<label style="font-size:13px;font-weight:600;display:block;margin-bottom:6px;">统一费率（双边合计）</label>';
            html += '<div style="display:flex;align-items:center;gap:8px;">';
            html += '<input id="' + CONTAINER_ID + '-fee-rate" type="number" step="0.000001" min="0" value="' + Number(feeRate).toFixed(6) + '" style="width:160px;padding:6px 8px;font-size:13px;border:1px solid #ccc;border-radius:4px;">';
            html += '<span style="font-size:12px;color:#888;">例如：0.002500 表示双边合计 0.25%</span>';
            html += '</div></div>';
        } else if (mode === 'per_product') {
            // Per-product: single button to open configFeeTable overlay in EDIT mode
            if (!hasFeeData()) {
                fetchFeeTable(false).then(function() {
                    if (_mounted) render();
                });
            }
            var notice = getFeeNotice();
            html += '<div id="' + CONTAINER_ID + '-pp-editor" style="margin-bottom:16px;padding:12px;background:#f9fafb;border-radius:6px;border:1px solid #e5e7eb;">';
            html += '<label style="font-size:13px;font-weight:600;display:block;margin-bottom:8px;">分品种费率</label>';
            if (notice && notice.message) {
                html += '<div style="margin-bottom:8px;padding:8px 10px;border:1px solid #fbbf24;background:#fffbeb;color:#92400e;border-radius:6px;font-size:12px;line-height:1.5;">⚠️ ' + escapeHTML(notice.message) + (notice.sourceDate ? ' 当前费率日期：' + escapeHTML(notice.sourceDate) : '') + '</div>';
            }
            html += '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">';
            html += '<button id="' + CONTAINER_ID + '-edit-fee-btn" style="padding:6px 16px;font-size:12px;border:1px solid #0078d4;border-radius:4px;background:#0078d4;color:#fff;cursor:pointer;">📋 查看/编辑品种费率表</button>';
            html += '<span style="font-size:12px;color:#888;">修改过的费率标记为黄色，编辑费率表中可设置自定义费率</span>';
            html += '</div>';
            html += '</div>';
        }

        // ── Sensitivity slider (per_product only) ──
        if (mode === 'per_product') {
            html += '<div style="margin-bottom:16px;">';
            html += '<label style="font-size:13px;font-weight:600;display:block;margin-bottom:6px;">费率倍数 <span id="' + CONTAINER_ID + '-sens-val" style="font-weight:700;color:#0078d4;">' + Number(sensitivity).toFixed(1) + '</span>x</label>';
            html += '<input id="' + CONTAINER_ID + '-sensitivity" type="range" min="0.1" max="5" step="0.1" value="' + Number(sensitivity).toFixed(1) + '" style="width:100%;max-width:300px;">';
            html += '</div>';
        }

        // ── Close-today toggle (per_product only) ──
        if (mode === 'per_product') {
            html += '<div style="margin-bottom:16px;padding:10px 14px;background:#f9fafb;border-radius:6px;border:1px solid #e5e7eb;">';
            html += '<label style="font-size:13px;font-weight:600;display:flex;align-items:center;gap:8px;cursor:pointer;">';
            html += '<span>平仓口径</span>';
            html += '<button id="' + CONTAINER_ID + '-ct-toggle" style="padding:4px 12px;font-size:12px;border:1px solid ' + (useCT ? '#0078d4' : '#ccc') + ';border-radius:4px;background:' + (useCT ? '#0078d4' : '#fff') + ';color:' + (useCT ? '#fff' : '#333') + ';cursor:pointer;">' + (useCT ? '平今仓' : '平昨仓') + '</button>';
            html += '</label>';
            html += '<div style="font-size:11px;color:#888;margin-top:4px;">平今仓模式使用 closetoday_ratio 计算手续费；平昨仓模式使用 close_ratio</div>';
            html += '</div>';
        }

        container.innerHTML = html;
        _bindEvents();
    }

    // ── Event binding ──────────────────────────────────────────────────────────

    function _bindEvents() {
        var container = $(CONTAINER_ID);
        if (!container) return;

        // Mode buttons
        for (var mi = 0; mi < FEE_MODES.length; mi++) {
            var m = FEE_MODES[mi];
            var btn = $(CONTAINER_ID + '-mode-' + m);
            if (btn) {
                btn.addEventListener('click', function(modeVal) {
                    return function() {
                        REG.setDirty('feeMode', modeVal);
                        render();
                    };
                }(m));
            }
        }

        // Uniform fee rate input
        var rateInput = $(CONTAINER_ID + '-fee-rate');
        if (rateInput) {
            rateInput.addEventListener('change', function() {
                var val = parseFloat(this.value);
                if (!isNaN(val) && val >= 0) {
                    REG.setDirty('feeRate', val);
                    render();
                }
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
                        render();
                    });
                }
            });
        }
    }

    // ── Event handlers ────────────────────────────────────────────────────────

    function _onDataChanged() {
        if (_mounted) {
            REG.rollbackDirty();
            render();
        }
    }

    // ── Config chips (consumed by list panel via REG.getChips) ────────────────

    /**
     * getChips(group) → [{label, html, style, onClick}]
     *
     * Rules:
     *  - 'none':         no chips at all
     *  - 'uniform':      [统一费率: 2.500000] + [费率倍数: 1.5x] if sensitivity ≠ 1
     *  - 'per_product':  [分品种费率] clickable → configFeeTable overlay (view mode)
     *                      if feeMap has entries → [分品种费率(自定义)]
     *                    + [费率倍数: 1.5x] if sensitivity ≠ 1
     *                    + [平今/平昨] always
     */
    function getChips(group) {
        if (!group) return [];
        var mode = group.feeMode || GS.getFieldDefault('feeMode');
        if (mode === 'none') return [];

        var chips = [];
        var chipPlain = 'display:inline-block;background:#e5e7eb;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;color:#374151;';
        var chipClickable = 'display:inline-block;cursor:pointer;background:#c7d2fe;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;color:#312e81;';

        if (mode === 'uniform') {
            var rateVal = (group.feeRate != null) ? Number(group.feeRate) : 0.0025;
            var rateStr = rateVal.toFixed(6);
            chips.push({
                label: 'fee-uniform',
                html: '💰 统一费率:' + rateStr,
                style: chipPlain
            });
        } else if (mode === 'per_product') {
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
        var sensNum = Number(sens);
        if (sens != null && !Number.isNaN(sensNum) && sensNum !== 1) {
            chips.push({
                label: 'fee-sensitivity',
                html: '⚡ 费率倍数:' + sensNum.toFixed(1) + 'x',
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

    // ═══════════════════════════════════════════════════════════════════════════
    // Public API — GT.fee (data layer)
    // ═══════════════════════════════════════════════════════════════════════════

    GT.fee = {
        fetchFeeTable: fetchFeeTable,
        getFeeRows: getFeeRows,
        buildFeeMap: buildFeeMap,
        ensureFeeData: ensureFeeData,
        hasFeeData: hasFeeData,
        getFeeNotice: getFeeNotice,
        getModifications: getModifications,
        applyModifications: applyModifications,
        useCloseToday: useCloseToday,
        setUseCloseToday: setUseCloseToday,
        bind: bindFeeControls,
    };

    // ═══════════════════════════════════════════════════════════════════════════
    // Public API — GT.panels.config.fee (config panel)
    // ═══════════════════════════════════════════════════════════════════════════

    function mount() {
        _mounted = true;
        REG = window.GT_CONFIG_REGISTRY;

        if (GT.events && GT.events.on) GT.events.on('groupsChanged', _onDataChanged);
        var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
        if (sel && sel.on) sel.on('selectionChanged', _onDataChanged);

        render();
    }

    function unmount() {
        _mounted = false;
        if (GT.events && GT.events.off) GT.events.off('groupsChanged', _onDataChanged);
        var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
        if (sel && sel.off) sel.off('selectionChanged', _onDataChanged);
    }

    function refresh() {
        if (_mounted) render();
    }

    if (!GT.panels) GT.panels = {};
    if (!GT.panels.config) GT.panels.config = {};

    GT.panels.config.fee = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
        getTableColumns: function() { return []; },
        getChips: getChips,
    };

    // Register field schemas (so _fillGroupFromConfig preserves these fields)
    var GS = GT.groupSettings;
    if (GS && GS.registerField) {
        GS.registerField({ key: 'feeMode',        type: 'string',  default: 'none' });
        GS.registerField({ key: 'feeRate',        type: 'number',  default: 0.0025 });
        GS.registerField({ key: 'feeMap',         type: 'object',  default: null });
        GS.registerField({ key: 'feeSensitivity', type: 'number',  default: 1 });
        GS.registerField({ key: 'useCloseToday',  type: 'boolean', default: false });
    }

    // Register as category-3 config panel
    if (window.GT_CONFIG_REGISTRY) {
        window.GT_CONFIG_REGISTRY.register({
            name: 'fee',
            label: '费率',
            panel: GT.panels.config.fee,
            fields: ['feeMode', 'feeRate', 'feeMap', 'feeSensitivity', 'useCloseToday'],
        }, 'config-fee');
    }

    GT.log('panels/config/fee/index.js loaded (fee data + config panel)');
})();
