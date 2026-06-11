/**
 * panels/config/fee/overlay.js — Fee table overlay shell
 *
 * Assembles the fee table (table.js), modification history list, and edit panel
 * (modification.js) into a modal overlay. Handles overlay open/close, product
 * filtering, and save-to-backend.
 *
 * Uses _configFee internal namespace for shared state between the sub-modules:
 *   - _configFee.getGroup() / _configFee.getMode() / _configFee.getProducts()
 *   - _configFee.getTradingDay() / _configFee.getSubmissionId()
 *   - _configFee.onRefresh(fn) — register re-render callback
 *   - _configFee.refresh() — trigger table + modification re-render
 *
 * Public API:
 *   GT.overlays.configFeeTable.open(group, mode, onClose)
 *   GT.overlays.configFeeTable.close()
 *
 * Dependencies: GT.fee (index.js), _configFee (internal namespace)
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) return;

    GT.overlays = GT.overlays || {};

    var OVERLAY_ID = 'grouptest-config-fee-overlay';
    var PANEL_ID   = 'grouptest-config-fee-panel';

    // ═══════════════════════════════════════════════════════════════════════════
    // Internal shared state (_configFee)
    // ═══════════════════════════════════════════════════════════════════════════

    var _refreshHandlers = [];

    var _state = {
        group: null,        // current group config object
        mode: 'view',       // 'edit' or 'view'
        products: [],       // filtered product codes (from tester)
        tradingDay: null,   // current trading day for time-range filtering
        submissionId: null, // current submission ID for backend save
        onClose: null,      // close callback
    };

    /** Internal namespace used by table.js and modification.js */
    GT.overlays._configFee = {
        getGroup:       function()       { return _state.group; },
        getMode:        function()       { return _state.mode; },
        getProducts:    function()       { return _state.products; },
        getTradingDay:  function()       { return _state.tradingDay; },
        getSubmissionId: function()      { return _state.submissionId; },

        /** Register a refresh callback (called on data changes). */
        onRefresh: function(fn) {
            if (typeof fn === 'function' && _refreshHandlers.indexOf(fn) < 0) {
                _refreshHandlers.push(fn);
            }
        },

        /** Trigger all registered refresh callbacks. */
        refresh: function() {
            for (var i = 0; i < _refreshHandlers.length; i++) {
                try { _refreshHandlers[i](); } catch (e) {}
            }
        },
    };

    // ═══════════════════════════════════════════════════════════════════════════
    // DOM helpers
    // ═══════════════════════════════════════════════════════════════════════════

    function escapeHTML(str) { return GT.escapeHTML(str); }

    function ensureOverlay() {
        var overlay = document.getElementById(OVERLAY_ID);
        if (overlay) return overlay;

        overlay = document.createElement('div');
        overlay.id = OVERLAY_ID;
        overlay.style.cssText = 'display:none;position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,0.35);align-items:center;justify-content:center;';
        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) closeOverlay();
        });

        var panel = document.createElement('div');
        panel.id = PANEL_ID;
        panel.style.cssText = 'position:relative;width:min(96vw,1150px);max-height:min(92vh,750px);background:#fff;border-radius:10px;box-shadow:0 8px 40px rgba(0,0,0,0.2);display:flex;flex-direction:column;overflow:hidden;';
        overlay.appendChild(panel);

        document.body.appendChild(overlay);
        return overlay;
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // Product code extraction & param resolution
    // ═══════════════════════════════════════════════════════════════════════════

    function _getProductCodes(group) {
        var testerId = group && group.testerId;
        if (!testerId) return [];

        var subs = window.submissions || [];
        for (var i = 0; i < subs.length; i++) {
            if (String(subs[i].id) === String(testerId)) {
                var products = subs[i].products;
                if (Array.isArray(products)) {
                    return products.map(function(p) {
                        var raw = typeof p === 'string' ? p : (p.name || '');
                        var dotIdx = raw.indexOf('.');
                        var code = (dotIdx >= 0) ? raw.substring(0, dotIdx) : raw;
                        return code.toUpperCase();
                    });
                }
                break;
            }
        }
        return [];
    }

    function _resolveTradingDay() {
        // Try to get tradingDay from the group or global state
        if (_state.group && _state.group.tradingDay) return _state.group.tradingDay;
        if (GT.state && GT.state.tradingDay) return GT.state.tradingDay;
        return null;
    }

    function _resolveSubmissionId() {
        if (_state.group && _state.group.submissionId) return _state.group.submissionId;
        if (GT.state && GT.state.submissionId) return GT.state.submissionId;
        return null;
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // Toast
    // ═══════════════════════════════════════════════════════════════════════════

    function _showToast(msg, durationMs) {
        var toast = document.createElement('div');
        toast.textContent = msg;
        toast.style.cssText = 'position:fixed;top:16px;left:50%;transform:translateX(-50%);z-index:99999;'
            + 'padding:10px 24px;background:#1f2937;color:#fff;border-radius:8px;'
            + 'font-size:14px;font-weight:500;box-shadow:0 4px 16px rgba(0,0,0,0.25);'
            + 'pointer-events:none;transition:opacity 0.3s;';
        document.body.appendChild(toast);
        if (durationMs && durationMs > 0) {
            setTimeout(function() {
                toast.style.opacity = '0';
                setTimeout(function() {
                    if (toast.parentNode) toast.parentNode.removeChild(toast);
                }, 300);
            }, durationMs);
        }
        return toast;
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // Render (assembles header + sub-modules + footer)
    // ═══════════════════════════════════════════════════════════════════════════

    // Unique IDs for sub-module mount points (set once in ensureOverlay, reused)
    var MOD_HISTORY_ID = PANEL_ID + '-mod-history';
    var MOD_EDIT_ID    = PANEL_ID + '-mod-edit';
    var TABLE_ID       = PANEL_ID + '-table';
    var FOOTER_ID      = PANEL_ID + '-footer';

    function _render() {
        var group = _state.group;
        var mode  = _state.mode;
        var isEdit = (mode === 'edit');

        var useCT = !!group.useCloseToday;
        var ctLabel = useCT ? '平今仓' : '平昨仓';
        var title = (group.name || ('#' + group.id));
        var modeLabel = isEdit ? '(编辑模式)' : '(查看模式)';

        var panel = document.getElementById(PANEL_ID);
        if (!panel) return;

        // ── Build HTML skeleton ──
        var html = '';

        // Header
        html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:12px 18px;border-bottom:1px solid #e5e7eb;background:#f9fafb;flex-shrink:0;">';
        html += '<div>';
        html += '<strong style="font-size:15px;color:#1f2937;">📊 品种费率 — ' + escapeHTML(title) + '</strong>';
        html += '<span style="margin-left:8px;font-size:12px;color:#888;">' + modeLabel + '</span>';
        html += '<span style="margin-left:8px;font-size:12px;color:#888;">平仓口径：' + ctLabel + '</span>';
        html += '</div>';
        html += '<button id="' + PANEL_ID + '-close-top" style="background:none;border:none;font-size:22px;cursor:pointer;color:#888;line-height:1;">&times;</button>';
        html += '</div>';

        // Scrollable body: modification history (edit only) + edit panel (edit only) + table
        html += '<div style="flex:1;overflow-y:auto;padding:8px 12px;">';

        // Modification history list (edit mode only, rendered by modification.js)
        if (isEdit) {
            html += '<div id="' + MOD_HISTORY_ID + '" style="margin-bottom:10px;"></div>';
        }

        // Edit panel (edit mode only, rendered by modification.js)
        if (isEdit) {
            html += '<div id="' + MOD_EDIT_ID + '" style="margin-bottom:10px;"></div>';
        }

        // Fee table (rendered by table.js)
        html += '<div id="' + TABLE_ID + '"></div>';

        html += '</div>'; // end scrollable body

        // Footer
        html += '<div id="' + FOOTER_ID + '" style="padding:10px 18px;border-top:1px solid #e5e7eb;background:#f9fafb;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;">';
        html += '<span style="font-size:11px;color:#888;">' + (isEdit ? '点击表格行选中品种 → 编辑区修改字段 → 提交记录显示在上方列表' : '只读模式，无法修改') + '</span>';
        html += '<div style="display:flex;gap:6px;">';
        if (isEdit) {
            html += '<button id="' + PANEL_ID + '-save-btn" style="padding:6px 16px;font-size:12px;border:1px solid #0078d4;border-radius:4px;background:#0078d4;color:#fff;cursor:pointer;">💾 保存到后端</button>';
        }
        html += '<button id="' + PANEL_ID + '-close-btn" style="padding:6px 16px;font-size:12px;border:1px solid #ccc;border-radius:4px;background:#fff;color:#333;cursor:pointer;">关闭</button>';
        html += '</div>';
        html += '</div>';

        panel.innerHTML = html;

        // ── Bind events ──
        var closeTop = document.getElementById(PANEL_ID + '-close-top');
        var closeBtn = document.getElementById(PANEL_ID + '-close-btn');
        if (closeTop) closeTop.addEventListener('click', closeOverlay);
        if (closeBtn) closeBtn.addEventListener('click', closeOverlay);

        if (isEdit) {
            var saveBtn = document.getElementById(PANEL_ID + '-save-btn');
            if (saveBtn) saveBtn.addEventListener('click', _saveToBackend);
        }

        // ── Render sub-modules ──
        _renderSubModules();
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // Sub-module rendering (table.js + modification.js)
    // ═══════════════════════════════════════════════════════════════════════════

    function _renderSubModules() {
        var isEdit = (_state.mode === 'edit');

        // Fee table (always)
        var tableContainer = document.getElementById(TABLE_ID);
        if (tableContainer && GT.overlays.configFeeTable._renderTable) {
            GT.overlays.configFeeTable._renderTable(tableContainer);
        }

        if (!isEdit) return;

        // Modification history list
        var histContainer = document.getElementById(MOD_HISTORY_ID);
        if (histContainer && GT.overlays.configFeeTable._renderModHistory) {
            GT.overlays.configFeeTable._renderModHistory(histContainer);
        }

        // Edit panel
        var editContainer = document.getElementById(MOD_EDIT_ID);
        if (editContainer && GT.overlays.configFeeTable._renderModEdit) {
            GT.overlays.configFeeTable._renderModEdit(editContainer);
        }
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // Save to backend
    // ═══════════════════════════════════════════════════════════════════════════

    function _saveToBackend() {
        var mods = (GT.fee && GT.fee.getModifications) ? GT.fee.getModifications() : [];
        var subId = _state.submissionId;
        if (!subId) {
            _showToast('⚠️ 无法获取 submission_id，请重新打开', 3000);
            return;
        }

        var toast = _showToast('⏳ 正在保存费率修改...');
        fetch('/save_fee_modifications', {
            method: 'POST',
            headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },
            body: JSON.stringify({ submission_id: subId, modifications: mods })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            toast.style.opacity = '0';
            setTimeout(function() {
                if (toast.parentNode) toast.parentNode.removeChild(toast);
            }, 300);
            if (data && data.success) {
                _showToast('✅ 费率修改已保存 (' + (data.count || mods.length) + ' 条)', 3000);
                // Update local modifications with cleaned backend version
                if (GT.fee && GT.fee.applyModifications && Array.isArray(data.modifications)) {
                    GT.fee.applyModifications(data.modifications);
                }
                closeOverlay();
            } else {
                _showToast('❌ 保存失败: ' + (data && data.message || '未知错误'), 5000);
            }
        })
        .catch(function(err) {
            toast.style.opacity = '0';
            setTimeout(function() {
                if (toast.parentNode) toast.parentNode.removeChild(toast);
            }, 300);
            _showToast('❌ 保存失败: ' + (err && err.message || err), 5000);
            console.error('[configFeeTable.save] FAILED:', err);
        });
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // Open / Close
    // ═══════════════════════════════════════════════════════════════════════════

    var _fetchPromise = null;

    function openOverlay(group, mode, onClose) {
        ensureOverlay();

        // Ensure fee data is loaded
        var feeRows = (GT.fee && typeof GT.fee.getFeeRows === 'function') ? GT.fee.getFeeRows() : [];
        if (feeRows.length === 0) {
            if (GT.fee && typeof GT.fee.fetchFeeTable === 'function') {
                if (!_fetchPromise) {
                    var toast = _showToast('⏳ 正在加载分品种费率数据...');
                    _fetchPromise = GT.fee.fetchFeeTable(false).then(function(rows) {
                        _fetchPromise = null;
                        toast.style.opacity = '0';
                        setTimeout(function() {
                            if (toast.parentNode) toast.parentNode.removeChild(toast);
                        }, 300);
                        if (!rows || rows.length === 0) {
                            _showToast('⚠️ 费率数据为空，请检查数据源', 3000);
                            return;
                        }
                        openOverlay(group, mode, onClose);
                    }).catch(function(err) {
                        _fetchPromise = null;
                        toast.style.opacity = '0';
                        setTimeout(function() {
                            if (toast.parentNode) toast.parentNode.removeChild(toast);
                        }, 300);
                        _showToast('❌ 费率数据加载失败: ' + (err && err.message || err), 5000);
                        console.error('[configFeeTable.open] fetch FAILED:', err);
                    });
                }
            } else {
                _showToast('⚠️ 费率模块未加载，无法配置分品种费率', 3000);
            }
            return;
        }

        // Reset refresh handlers (sub-modules re-register on render)
        _refreshHandlers = [];

        _state.group = group;
        _state.mode = mode || 'view';
        _state.products = _getProductCodes(group);
        _state.tradingDay = _resolveTradingDay();
        _state.submissionId = _resolveSubmissionId();
        _state.onClose = onClose || null;

        _render();

        var overlay = document.getElementById(OVERLAY_ID);
        if (overlay) overlay.style.display = 'flex';
    }

    function closeOverlay() {
        var overlay = document.getElementById(OVERLAY_ID);
        if (overlay) overlay.style.display = 'none';

        // Fire registered close callback
        if (_state && typeof _state.onClose === 'function') {
            try { _state.onClose(); } catch (e) {}
        }
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // Export
    // ═══════════════════════════════════════════════════════════════════════════

    GT.overlays.configFeeTable = {
        open:  openOverlay,
        close: closeOverlay,
        // Internal hooks for sub-modules (table.js, modification.js)
        _renderTable:      null, // set by table.js
        _renderModHistory: null, // set by modification.js
        _renderModEdit:    null, // set by modification.js
    };
})();
