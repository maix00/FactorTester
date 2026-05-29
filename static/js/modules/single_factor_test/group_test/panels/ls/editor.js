/**
 * panels/ls/editor.js — LS config editor panel (Tab 3 "多空", detail view)
 *
 * Phase 5 UI panel. Shows full detail of the selected LS config and allows
 * editing of optional override settings: fee override, close-today toggle,
 * rebalance mode. Also displays long/short derived group references.
 *
 * Data shape: { id, name, longGroupId, shortGroupId, feeMode, feeRate,
 *               useCloseToday, rebalanceMode, needsRegenerate, metadata }
 *
 * Contract:
 *   GT.state.getActiveLSConfigId() → id|null
 *   GT.state.on('activeLSConfigChanged', cb)
 *   GT.state.on('lsConfigsChanged', cb)
 *   GT.datamodel.ls_configs — CRUD
 *   GT.datamodel.derived_graph — for resolving group names
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.ls) { GT.panels.ls = {}; }

    var CONTAINER_ID = 'ls-config-editor';

    var FEE_MODE_LABELS = { inherit: '继承自派生组', override: '覆盖费率' };
    var REBALANCE_MODE_LABELS = { each_period: '每期再平衡', buy_and_hold: '买入持有', recycle: '循环再平衡' };

    var _mounted = false;

    function $(id) { return document.getElementById(id); }

    function _getConfig() {
        var id = GT.state.getActiveLSConfigId();
        if (!id) return null;
        return GT.datamodel.ls_configs.get(id);
    }

    function _dgName(id) {
        if (!id) return '—';
        if (GT.datamodel.derived_graph && GT.datamodel.derived_graph.get) {
            var dg = GT.datamodel.derived_graph.get(id);
            if (dg) return dg.name || id;
        }
        return id;
    }

    // ---------------------------------------------------------------------------
    // Render
    // ---------------------------------------------------------------------------

    function render() {
        var container = $(CONTAINER_ID);
        if (!container) return;

        var config = _getConfig();
        if (!config) {
            container.innerHTML = '<div style="padding:24px;text-align:center;color:#888;">请在左侧列表中选择一个多空配置</div>';
            return;
        }

        var html = '';

        // Header
        html += '<div style="margin-bottom:16px;">';
        html += '<span style="font-size:16px;font-weight:700;">' + config.name + '</span>';
        html += '<span style="margin-left:8px;font-size:11px;padding:2px 6px;border-radius:4px;'
            + (config.needsRegenerate ? 'background:#fef3c7;color:#d97706;' : 'background:#d1fae5;color:#059669;')
            + '">' + (config.needsRegenerate ? '待更新' : '就绪') + '</span>';
        html += '</div>';

        // Group references
        html += '<div style="margin-bottom:16px;padding:12px;background:#f9fafb;border-radius:6px;border:1px solid #e5e7eb;">';
        html += '<table style="width:100%;">';
        html += '<tr><td style="padding:4px 0;font-size:12px;color:#666;width:80px;">多头组</td>';
        html += '<td style="font-size:13px;font-weight:500;">' + _dgName(config.longGroupId) + '</td></tr>';
        html += '<tr><td style="padding:4px 0;font-size:12px;color:#666;">空头组</td>';
        html += '<td style="font-size:13px;font-weight:500;">' + _dgName(config.shortGroupId) + '</td></tr>';
        html += '</table></div>';

        // --- Editable overrides ---

        // Fee override
        html += _sectionHeader('费率设置');
        html += '<label style="display:block;margin-bottom:8px;">';
        html += '<select id="lsed-feeMode" style="padding:4px 8px;border:1px solid #d0d5dd;border-radius:4px;font-size:13px;">';
        Object.keys(FEE_MODE_LABELS).forEach(function(mode) {
            var sel = config.feeMode === mode ? ' selected' : '';
            html += '<option value="' + mode + '"' + sel + '>' + FEE_MODE_LABELS[mode] + '</option>';
        });
        html += '</select></label>';
        if (config.feeMode === 'override') {
            html += '<label style="display:block;margin-bottom:8px;">';
            html += '<span style="font-size:12px;color:#666;">费率 (0 = 免手续费)</span>';
            html += '<input type="number" id="lsed-feeRate" value="' + (config.feeRate !== null ? config.feeRate : '') + '" step="0.00001" min="0" style="width:120px;padding:4px 8px;border:1px solid #d0d5dd;border-radius:4px;font-size:13px;margin-left:8px;">';
            html += '</label>';
        }

        // Close today toggle
        html += _sectionHeader('平今/昨');
        var ctVal = config.useCloseToday;
        html += '<div style="display:flex;gap:8px;">';
        html += '<button id="lsed-closeToday-toggle" style="padding:6px 16px;border-radius:4px;font-size:13px;cursor:pointer;'
            + (ctVal === true ? 'background:#0078d4;color:#fff;border:1px solid #0078d4;' : 'background:#fff;color:#333;border:1px solid #d0d5dd;')
            + '">' + (ctVal === true ? '平今仓' : '平昨仓') + '</button>';
        html += '</div>';

        // Rebalance mode
        html += _sectionHeader('再平衡');
        html += '<select id="lsed-rebalanceMode" style="padding:4px 8px;border:1px solid #d0d5dd;border-radius:4px;font-size:13px;">';
        html += '<option value="">— 继承 —</option>';
        Object.keys(REBALANCE_MODE_LABELS).forEach(function(mode) {
            var sel2 = config.rebalanceMode === mode ? ' selected' : '';
            html += '<option value="' + mode + '"' + sel2 + '>' + REBALANCE_MODE_LABELS[mode] + '</option>';
        });
        html += '</select>';

        // Save button
        html += '<div style="margin-top:20px;display:flex;gap:8px;">';
        html += '<button id="lsed-save" style="padding:8px 20px;border:none;border-radius:4px;background:#0078d4;color:#fff;cursor:pointer;font-size:13px;">保存设置</button>';
        html += '</div>';

        container.innerHTML = html;
        _bindEvents(config);
    }

    function _sectionHeader(title) {
        return '<div style="margin-top:16px;margin-bottom:8px;font-size:13px;font-weight:600;color:#333;border-bottom:1px solid #e5e7eb;padding-bottom:4px;">' + title + '</div>';
    }

    function _bindEvents(config) {
        // Fee mode change → show/hide rate input → re-render
        var feeModeSel = $('lsed-feeMode');
        if (feeModeSel) {
            feeModeSel.addEventListener('change', function() {
                var patch = { feeMode: this.value };
                if (this.value === 'inherit') patch.feeRate = null;
                try {
                    GT.datamodel.ls_configs.update(config.id, patch);
                } catch (e) { alert(e.message); }
            });
        }

        // Close-today toggle
        var ctBtn = $('lsed-closeToday-toggle');
        if (ctBtn) {
            ctBtn.addEventListener('click', function() {
                var cur = config.useCloseToday;
                var next = cur === true ? null : true; // toggle: true → null → true
                try {
                    GT.datamodel.ls_configs.update(config.id, { useCloseToday: next });
                } catch (e) { alert(e.message); }
            });
        }

        // Rebalance mode
        var rebalSel = $('lsed-rebalanceMode');
        if (rebalSel) {
            rebalSel.addEventListener('change', function() {
                try {
                    GT.datamodel.ls_configs.update(config.id, { rebalanceMode: this.value || null });
                } catch (e) { alert(e.message); }
            });
        }

        // Save button (explicit save for fee rate)
        var saveBtn = $('lsed-save');
        if (saveBtn) {
            saveBtn.addEventListener('click', function() {
                var patch = {};
                var rateEl = $('lsed-feeRate');
                if (rateEl && rateEl.value !== '') {
                    patch.feeRate = parseFloat(rateEl.value);
                }
                if (Object.keys(patch).length === 0) return;
                try {
                    GT.datamodel.ls_configs.update(config.id, patch);
                    alert('已保存');
                } catch (e) { alert(e.message); }
            });
        }
    }

    // ---------------------------------------------------------------------------
    // Event handlers
    // ---------------------------------------------------------------------------

    function _onActiveLSConfigChanged() { if (_mounted) render(); }
    function _onLSConfigsChanged() { if (_mounted) render(); }

    // ---------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------

    function mount() {
        _mounted = true;
        GT.state.on('activeLSConfigChanged', _onActiveLSConfigChanged);
        GT.state.on('lsConfigsChanged', _onLSConfigsChanged);
        render();
    }

    function unmount() {
        _mounted = false;
        GT.state.off('activeLSConfigChanged', _onActiveLSConfigChanged);
        GT.state.off('lsConfigsChanged', _onLSConfigsChanged);
    }

    function refresh() { if (_mounted) render(); }

    // ---------------------------------------------------------------------------
    // Export
    // ---------------------------------------------------------------------------

    GT.panels.ls.editor = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
    };

    GT.log('panels.ls.editor loaded');
})();
