/**
 * panels/config/fee/modification.js — Modification history + edit panel.
 *
 * Two sections:
 *   1. Modification history list — shows all saved FeeModification entries,
 *      each with [编辑] and [删除] buttons.
 *   2. Edit panel — appears when a table row is selected. Shows editable fields
 *      for the selected variety, time range inputs, and [提交] button.
 *
 * Depends on GT.fee.* (index.js) for data management.
 * Communicates with table.js via _configFee.table.getSelectedCode().
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) return;

    GT.overlays = GT.overlays || {};
    var _configFee = GT.overlays._configFee || {};
    GT.overlays._configFee = _configFee;

    // ── Constants ──────────────────────────────────────────────────────────

    var VALID_FEE_FIELDS = ['open_ratio', 'close_yesterday_ratio', 'close_today_ratio',
                            'open_fixed', 'close_yesterday_fixed', 'close_today_fixed'];

    var FIELD_LABELS = {
        open_ratio:           '开仓比率',
        open_fixed:           '开仓费用',
        close_yesterday_ratio:'平昨比率',
        close_yesterday_fixed:'平昨费用',
        close_today_ratio:    '平今比率',
        close_today_fixed:    '平今费用',
    };

    // ── Helpers ────────────────────────────────────────────────────────────

    function esc(str) { return GT.escapeHTML ? GT.escapeHTML(str) : String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

    function fmtNum(v, dec) {
        var n = Number(v);
        if (isNaN(n)) return '—';
        return n.toFixed(dec || 6);
    }

    /** Format a timestamp to local datetime string. */
    function fmtTimestamp(ts) {
        if (!ts) return '';
        var d = new Date(ts);
        return d.toLocaleString();
    }

    /** Format a fields dict to a short summary. */
    function fmtFieldsSummary(fields) {
        var parts = [];
        var keys = Object.keys(fields || {});
        for (var i = 0; i < keys.length; i++) {
            var k = keys[i];
            var label = FIELD_LABELS[k] || k;
            parts.push(label + '=' + fmtNum(fields[k]));
        }
        return parts.join(', ') || '(empty)';
    }

    // ── State ──────────────────────────────────────────────────────────────

    var _editingIndex = -1;  // -1 = new modification, >=0 = editing existing entry

    // ── Render: Modification history list ──────────────────────────────────

    var MOD_LIST_ID = 'fee-mod-list';

    /**
     * Render the modification history list into a container.
     */
    function renderModList(container) {
        var mods = [];
        if (GT.fee && typeof GT.fee.getModifications === 'function') {
            mods = GT.fee.getModifications();
        }

        var html = '';
        html += '<div id="' + MOD_LIST_ID + '" style="margin-bottom:8px;">';

        if (mods.length === 0) {
            html += '<div style="padding:8px 12px;font-size:12px;color:#888;text-align:center;">暂无修改记录。选中下方表格行后编辑字段并提交。</div>';
        } else {
            html += '<div style="font-size:12px;font-weight:600;color:#374151;margin-bottom:4px;padding:0 4px;">📝 修改记录 (' + mods.length + '条，后提交的优先)</div>';
            // Show newest first (reverse of stored order, since stored is timestamp ASC for apply)
            // We sort DESC for display
            var display = mods.slice().sort(function(a, b) {
                return (b.timestamp || 0) - (a.timestamp || 0);
            });
            for (var i = 0; i < display.length; i++) {
                var m = display[i];
                // Find original index in _feeModifications
                var origIdx = mods.indexOf(display[i]);
                var timeRange = '';
                if (m.time_from || m.time_to) {
                    timeRange = (m.time_from || '…') + ' ~ ' + (m.time_to || '…');
                } else {
                    timeRange = '全部时段';
                }

                html += '<div style="display:flex;align-items:center;gap:8px;padding:6px 8px;margin:2px 0;background:#f9fafb;border-radius:6px;border:1px solid #e5e7eb;font-size:12px;">';
                html += '<span style="font-weight:600;font-family:monospace;color:#1d4ed8;min-width:50px;">' + esc(m.variety_code) + '</span>';
                html += '<span style="flex:1;color:#555;">' + esc(fmtFieldsSummary(m.fields)) + '</span>';
                html += '<span style="color:#888;font-size:11px;">' + esc(timeRange) + '</span>';
                html += '<span style="color:#aaa;font-size:10px;" title="' + esc(fmtTimestamp(m.timestamp)) + '">' + esc(fmtTimestamp(m.timestamp)) + '</span>';
                html += '<button data-mod-edit="' + origIdx + '" style="padding:2px 8px;font-size:11px;border:1px solid #0078d4;border-radius:3px;background:#fff;color:#0078d4;cursor:pointer;">编辑</button>';
                html += '<button data-mod-del="' + origIdx + '" style="padding:2px 8px;font-size:11px;border:1px solid #dc3545;border-radius:3px;background:#fff;color:#dc3545;cursor:pointer;">删除</button>';
                html += '</div>';
            }
        }

        html += '</div>';
        container.innerHTML = html;

        // Bind edit/delete buttons
        var modList = document.getElementById(MOD_LIST_ID);
        if (modList) {
            var editBtns = modList.querySelectorAll('[data-mod-edit]');
            for (var j = 0; j < editBtns.length; j++) {
                editBtns[j].addEventListener('click', function() {
                    var idx = parseInt(this.getAttribute('data-mod-edit'));
                    _startEditModification(idx);
                });
            }
            var delBtns = modList.querySelectorAll('[data-mod-del]');
            for (var k = 0; k < delBtns.length; k++) {
                delBtns[k].addEventListener('click', function() {
                    var idx = parseInt(this.getAttribute('data-mod-del'));
                    _deleteModification(idx);
                });
            }
        }
    }

    // ── Render: Edit panel ─────────────────────────────────────────────────

    var EDIT_PANEL_ID = 'fee-edit-panel';

    /**
     * Render the edit panel into a container.
     * @param {string|null} varietyCode - selected variety code, or null (hide panel)
     * @param {object|null} rowData     - raw row data for pre-filling values
     */
    function renderEditPanel(container, varietyCode, rowData) {
        if (!varietyCode || !rowData) {
            container.innerHTML = '';
            _editingIndex = -1;
            return;
        }

        // Get existing values for this variety from modifications or raw data
        var existing = {
            open_ratio: rowData.open_ratio != null ? Number(rowData.open_ratio) : 0,
            open_fixed: rowData.open_fixed != null ? Number(rowData.open_fixed) : 0,
            close_yesterday_ratio: rowData.close_ratio != null ? Number(rowData.close_ratio) : 0,
            close_yesterday_fixed: rowData.close_fixed != null ? Number(rowData.close_fixed) : 0,
            close_today_ratio: rowData.closetoday_ratio != null ? Number(rowData.closetoday_ratio) : 0,
            close_today_fixed: rowData.closetoday_fixed != null ? Number(rowData.closetoday_fixed) : 0,
        };

        var editingLabel = _editingIndex >= 0 ? ' (编辑第' + (_editingIndex + 1) + '条)' : '';

        var html = '';
        html += '<div id="' + EDIT_PANEL_ID + '" style="padding:10px 12px;margin-bottom:8px;background:#f0f7ff;border:1px solid #b3d4ff;border-radius:8px;">';
        html += '<div style="font-size:12px;font-weight:600;color:#1d4ed8;margin-bottom:8px;">✏️ 编辑费率 — ' + esc(varietyCode) + esc(editingLabel) + '</div>';

        // Field inputs in two columns
        html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px 12px;margin-bottom:8px;">';
        for (var fi = 0; fi < VALID_FEE_FIELDS.length; fi++) {
            var f = VALID_FEE_FIELDS[fi];
            var label = FIELD_LABELS[f] || f;
            var val = existing[f];
            var readOnly = (_editingIndex >= 0) ? '' : ''; // always editable
            html += '<div style="display:flex;align-items:center;gap:6px;">';
            html += '<label style="font-size:11px;color:#555;min-width:56px;">' + esc(label) + '</label>';
            html += '<input id="fee-edit-' + f + '" type="number" step="0.000001" min="0" value="' + val + '" style="flex:1;padding:4px 6px;font-size:12px;border:1px solid #ccc;border-radius:4px;font-family:monospace;">';
            html += '</div>';
        }
        html += '</div>';

        // Time range inputs
        html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">';
        html += '<label style="font-size:11px;color:#555;">时间范围</label>';
        html += '<input id="fee-edit-time-from" type="text" placeholder="YYYY-MM-DD (可选)" style="flex:1;padding:4px 6px;font-size:12px;border:1px solid #ccc;border-radius:4px;">';
        html += '<span style="color:#888;">~</span>';
        html += '<input id="fee-edit-time-to" type="text" placeholder="YYYY-MM-DD (可选)" style="flex:1;padding:4px 6px;font-size:12px;border:1px solid #ccc;border-radius:4px;">';
        html += '</div>';

        // Action buttons
        html += '<div style="display:flex;gap:6px;">';
        html += '<button id="fee-edit-submit" style="padding:6px 16px;font-size:12px;border:1px solid #0078d4;border-radius:4px;background:#0078d4;color:#fff;cursor:pointer;">✓ 提交修改记录</button>';
        if (_editingIndex >= 0) {
            html += '<button id="fee-edit-cancel" style="padding:6px 16px;font-size:12px;border:1px solid #ccc;border-radius:4px;background:#fff;color:#333;cursor:pointer;">取消编辑</button>';
        }
        html += '</div>';

        html += '</div>';
        container.innerHTML = html;

        // If editing an existing modification, pre-fill from it
        if (_editingIndex >= 0) {
            var mods = GT.fee && typeof GT.fee.getModifications === 'function' ? GT.fee.getModifications() : [];
            var mod = mods[_editingIndex];
            if (mod) {
                // Pre-fill fields
                var mFields = mod.fields || {};
                for (var fi2 = 0; fi2 < VALID_FEE_FIELDS.length; fi2++) {
                    var f2 = VALID_FEE_FIELDS[fi2];
                    var input = document.getElementById('fee-edit-' + f2);
                    if (input && mFields[f2] != null) {
                        input.value = mFields[f2];
                    }
                }
                // Pre-fill time range
                var tf = document.getElementById('fee-edit-time-from');
                var tt = document.getElementById('fee-edit-time-to');
                if (tf) tf.value = mod.time_from || '';
                if (tt) tt.value = mod.time_to || '';
            }
        }

        // Bind submit
        var submitBtn = document.getElementById('fee-edit-submit');
        if (submitBtn) {
            submitBtn.addEventListener('click', function() {
                _submitModification(varietyCode);
            });
        }

        var cancelBtn = document.getElementById('fee-edit-cancel');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', function() {
                _editingIndex = -1;
                // Re-render edit panel without editing state
                renderEditPanel(container, varietyCode, rowData);
            });
        }
    }

    // ── Actions ────────────────────────────────────────────────────────────

    /** Called by [编辑] button on a history entry. */
    function _startEditModification(index) {
        _editingIndex = index;

        // Trigger re-render of edit panel with current selected row
        var varietyCode = _configFee.table ? _configFee.table.getSelectedCode() : null;
        if (varietyCode) {
            var group = (_configFee && _configFee.getGroup) ? _configFee.getGroup() : null;
            var rows = _configFee.table.buildRowData(group);
            var rowData = null;
            for (var i = 0; i < rows.length; i++) {
                if (rows[i].code === varietyCode) { rowData = rows[i]; break; }
            }
            var epContainer = document.getElementById('fee-edit-panel-container');
            if (epContainer && rowData) {
                renderEditPanel(epContainer, varietyCode, rowData);
            }
        }
    }

    /** Called by [提交修改记录] button. */
    function _submitModification(varietyCode) {
        var fields = {};
        for (var i = 0; i < VALID_FEE_FIELDS.length; i++) {
            var f = VALID_FEE_FIELDS[i];
            var input = document.getElementById('fee-edit-' + f);
            if (input) {
                var val = parseFloat(input.value);
                if (!isNaN(val) && val >= 0) {
                    fields[f] = val;
                }
            }
        }

        if (Object.keys(fields).length === 0) {
            _showToast('请至少输入一个有效的费率字段', 2000);
            return;
        }

        var timeFrom = document.getElementById('fee-edit-time-from');
        var timeTo   = document.getElementById('fee-edit-time-to');
        var tf = timeFrom ? timeFrom.value.trim() : '';
        var tt = timeTo   ? timeTo.value.trim()   : '';

        if (_editingIndex >= 0) {
            // Editing existing: remove old, add new
            if (GT.fee && typeof GT.fee.removeModification === 'function') {
                GT.fee.removeModification(_editingIndex);
            }
            _editingIndex = -1;
        }

        if (GT.fee && typeof GT.fee.addModification === 'function') {
            GT.fee.addModification(varietyCode, null, fields, tf || null, tt || null);
        }

        // Trigger re-render (caller handles via 'feeDataChanged' event)
        if (GT.events && typeof GT.events.emit === 'function') {
            GT.events.emit('feeDataChanged');
        }

        _showToast('✓ 修改记录已提交', 1500);
    }

    /** Called by [删除] button on a history entry. */
    function _deleteModification(index) {
        if (GT.fee && typeof GT.fee.removeModification === 'function') {
            GT.fee.removeModification(index);
        }
        // If we were editing this entry, cancel edit
        if (_editingIndex === index) {
            _editingIndex = -1;
        } else if (_editingIndex > index) {
            _editingIndex--; // adjust index after removal
        }

        if (GT.events && typeof GT.events.emit === 'function') {
            GT.events.emit('feeDataChanged');
        }
        _showToast('已删除修改记录', 1500);
    }

    // ── Toast ──────────────────────────────────────────────────────────────

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
    }

    // ── Register row selection callback ────────────────────────────────────

    /**
     * Called by table.js when a row is clicked.
     * Auto-opens the edit panel for the selected variety.
     */
    _configFee.onSelectRow = function(varietyCode, rowData) {
        _editingIndex = -1; // new modification, not editing existing
        var editContainer = document.getElementById('fee-edit-panel-container');
        if (editContainer) {
            renderEditPanel(editContainer, varietyCode, rowData);
        }
    };

    // ── Public API ─────────────────────────────────────────────────────────

    _configFee.modification = {
        renderModList: renderModList,
        renderEditPanel: renderEditPanel,
        getEditingIndex: function() { return _editingIndex; },
    };

    // Register render hooks on overlay (loaded before modification.js via script order)
    if (GT.overlays && GT.overlays.configFeeTable) {
        GT.overlays.configFeeTable._renderModHistory = function(container) {
            renderModList(container);
        };
        GT.overlays.configFeeTable._renderModEdit = function(container) {
            renderEditPanel(container);
        };
    }


})();