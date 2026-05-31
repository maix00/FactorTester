/**
 * panels/config/fee/overlay.js — Config-level per-product fee table overlay
 *
 * Used by the fee config panel (edit mode) and list chip click (view mode).
 *
 * Modes:
 *   'edit'   — editable cells, changes stage into REG.setDirty('feeMap', ...)
 *   'view'   — read-only table, no save bar
 *
 * Product filtering: only shows products belonging to the group's tester.
 * Uses GT.fee.getFeeRows() for raw fee data, applies feeMap overrides from group.
 *
 * UI mirrors the master-branch fee table: code|name|exchange|multiplier|
 *   open_ratio|close_ratio|closetoday_ratio|bilateral_total
 *
 * Modified cells get yellow background (fee-cell-modified class).
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) return;

    GT.overlays = GT.overlays || {};

    var OVERLAY_ID = 'grouptest-config-fee-overlay';
    var PANEL_ID   = 'grouptest-config-fee-panel';

    // ── DOM helpers ──────────────────────────────────────────────────────────

    function escapeHTML(str) {
        if (str === null || str === undefined) return '';
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(String(str)));
        return div.innerHTML;
    }

    function ensureOverlay() {
        var overlay = document.getElementById(OVERLAY_ID);
        if (overlay) return overlay;

        overlay = document.createElement('div');
        overlay.id = OVERLAY_ID;
        overlay.style.cssText = 'display:none;position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,0.35);align-items:center;justify-content:center;';
        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) closeConfigFeeOverlay();
        });

        var panel = document.createElement('div');
        panel.id = PANEL_ID;
        panel.style.cssText = 'position:relative;width:min(96vw,1100px);max-height:min(90vh,700px);background:#fff;border-radius:10px;box-shadow:0 8px 40px rgba(0,0,0,0.2);display:flex;flex-direction:column;overflow:hidden;';
        overlay.appendChild(panel);

        document.body.appendChild(overlay);
        return overlay;
    }

    // ── State ────────────────────────────────────────────────────────────────

    var _state = null; // { group, mode, products, feeMap, dirtyMap, closeFn }

    /**
     * Get tester products as array of product codes (uppercased).
     */
    function _getProductCodes(group) {
        var testerId = group && group.testerId;
        if (!testerId) return [];

        var subs = window.submissions || [];
        for (var i = 0; i < subs.length; i++) {
            if (String(subs[i].id) === String(testerId)) {
                var products = subs[i].products;
                if (Array.isArray(products)) {
                    return products.map(function(p) {
                        return typeof p === 'string' ? p.toUpperCase() : (p.name || '').toUpperCase();
                    });
                }
                break;
            }
        }
        return [];
    }

    /**
     * Merge group.feeMap overrides onto the raw fee rows.
     * Returns [{ code, name, exchange, multiplier, open_ratio, close_ratio,
     *            closetoday_ratio, openModified, closeModified, closeTodayModified }]
     */
    function _buildRows(group, products) {
        var rawRows = (GT.fee && typeof GT.fee.getFeeRows === 'function') ? GT.fee.getFeeRows() : [];
        var feeMap = group.feeMap || {};

        // Build product filter set
        var filterSet = null;
        if (products && products.length > 0) {
            filterSet = {};
            for (var i = 0; i < products.length; i++) {
                filterSet[String(products[i]).toUpperCase()] = true;
            }
        }

        var useCT = !!group.useCloseToday;
        var rows = [];

        for (var j = 0; j < rawRows.length; j++) {
            var r = rawRows[j];
            var code = String(r.code).toUpperCase();
            if (filterSet && !filterSet[code]) continue;

            var override = feeMap[code.toLowerCase()] || feeMap[code] || {};

            var openR  = r.open_ratio;
            var closeR = r.close_ratio;
            var closeTodayR = r.closetoday_ratio;
            var openMod  = false;
            var closeMod = false;
            var closeTodayMod = false;

            if (typeof override.open_ratio === 'number')   { openR = override.open_ratio;   openMod = true; }
            if (typeof override.close_ratio === 'number')  { closeR = override.close_ratio;  closeMod = true; }
            if (typeof override.closetoday_ratio === 'number') { closeTodayR = override.closetoday_ratio; closeTodayMod = true; }

            rows.push({
                code:             code,
                name:             r.name || '',
                exchange:         r.exchange || '',
                multiplier:       r.multiplier || '',
                open_ratio:       openR,
                close_ratio:      closeR,
                closetoday_ratio: closeTodayR,
                openModified:     openMod,
                closeModified:    closeMod,
                closeTodayModified: closeTodayMod,
            });
        }

        return rows;
    }

    // ── Render ───────────────────────────────────────────────────────────────

    function _render() {
        if (!_state) return;
        var group = _state.group;
        var mode  = _state.mode;
        var products = _state.products;
        var isEdit = (mode === 'edit');

        var useCT = !!group.useCloseToday;
        var ctLabel = useCT ? '平今仓' : '平昨仓';
        var rows = _buildRows(group, products);

        var panel = document.getElementById(PANEL_ID);
        if (!panel) return;

        var title = (group.name || ('#' + group.id));
        var modeLabel = isEdit ? '(编辑模式)' : '(查看模式)';

        var html = '';

        // ── Header ──
        html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid #e5e7eb;background:#f9fafb;flex-shrink:0;">';
        html += '<div>';
        html += '<strong style="font-size:15px;color:#1f2937;">📊 品种费率 — ' + escapeHTML(title) + '</strong>';
        html += '<span style="margin-left:8px;font-size:12px;color:#888;">' + modeLabel + '</span>';
        html += '<span style="margin-left:8px;font-size:12px;color:#888;">平仓口径：' + ctLabel + '</span>';
        html += '</div>';
        html += '<button id="' + PANEL_ID + '-close" style="background:none;border:none;font-size:22px;cursor:pointer;color:#888;line-height:1;">&times;</button>';
        html += '</div>';

        // ── Table ──
        html += '<div style="flex:1;overflow-y:auto;padding:8px 0;">';
        html += '<table style="width:100%;border-collapse:collapse;font-size:12px;">';
        html += '<thead><tr style="background:#f0f4f8;position:sticky;top:0;z-index:2;">';
        html += '<th style="padding:8px 10px;text-align:left;border-bottom:1px solid #dbe7f3;color:#0f4c81;font-weight:600;">品种代码</th>';
        html += '<th style="padding:8px 10px;text-align:left;border-bottom:1px solid #dbe7f3;color:#0f4c81;font-weight:600;">品种名称</th>';
        html += '<th style="padding:8px 10px;text-align:left;border-bottom:1px solid #dbe7f3;color:#0f4c81;font-weight:600;">交易所</th>';
        html += '<th style="padding:8px 10px;text-align:right;border-bottom:1px solid #dbe7f3;color:#0f4c81;font-weight:600;">乘数</th>';
        html += '<th style="padding:8px 10px;text-align:right;border-bottom:1px solid #dbe7f3;color:#0f4c81;font-weight:600;">开仓比率</th>';
        html += '<th style="padding:8px 10px;text-align:right;border-bottom:1px solid #dbe7f3;color:#0f4c81;font-weight:600;">平今比率</th>';
        html += '<th style="padding:8px 10px;text-align:right;border-bottom:1px solid #dbe7f3;color:#0f4c81;font-weight:600;">平昨比率</th>';
        html += '<th style="padding:8px 10px;text-align:right;border-bottom:1px solid #dbe7f3;color:#0f4c81;font-weight:600;">双边合计(%)</th>';
        html += '</tr></thead><tbody>';

        var anyModified = false;
        for (var i = 0; i < rows.length; i++) {
            var row = rows[i];
            var modCellClass = 'fee-cell-modified';
            var openClass  = row.openModified  ? ' class="' + modCellClass + '"' : '';
            var closeTodayClass = row.closeTodayModified ? ' class="' + modCellClass + '"' : '';
            var closeClass = row.closeModified ? ' class="' + modCellClass + '"' : '';
            if (row.openModified || row.closeModified || row.closeTodayModified) anyModified = true;

            var openR  = Number(row.open_ratio).toFixed(6);
            var closeR = Number(row.close_ratio).toFixed(6);
            var closeTodayR = Number(row.closetoday_ratio).toFixed(6);
            var totalPct = ((Number(row.open_ratio) + Number(row.close_ratio)) * 100);
            var totalStr = totalPct > 0 ? totalPct.toFixed(4) + '%' : '—';

            html += '<tr style="border-bottom:1px solid #eef2f7;">';
            html += '<td style="padding:6px 10px;font-weight:600;font-family:monospace;">' + escapeHTML(row.code) + '</td>';
            html += '<td style="padding:6px 10px;color:#555;">' + escapeHTML(row.name) + '</td>';
            html += '<td style="padding:6px 10px;color:#555;">' + escapeHTML(row.exchange) + '</td>';
            html += '<td style="padding:6px 10px;text-align:right;">' + escapeHTML(row.multiplier) + '</td>';

            if (isEdit) {
                html += '<td' + openClass + ' contenteditable="true" data-cf-variety="' + row.code.toLowerCase() + '" data-cf-field="open_ratio" style="padding:6px 10px;text-align:right;outline:none;">' + openR + '</td>';
                html += '<td' + closeTodayClass + ' contenteditable="true" data-cf-variety="' + row.code.toLowerCase() + '" data-cf-field="closetoday_ratio" style="padding:6px 10px;text-align:right;outline:none;">' + closeTodayR + '</td>';
                html += '<td' + closeClass + ' contenteditable="true" data-cf-variety="' + row.code.toLowerCase() + '" data-cf-field="close_ratio" style="padding:6px 10px;text-align:right;outline:none;">' + closeR + '</td>';
            } else {
                html += '<td style="padding:6px 10px;text-align:right;font-family:monospace;">' + openR + '</td>';
                html += '<td style="padding:6px 10px;text-align:right;font-family:monospace;">' + closeTodayR + '</td>';
                html += '<td style="padding:6px 10px;text-align:right;font-family:monospace;">' + closeR + '</td>';
            }

            html += '<td style="padding:6px 10px;text-align:right;font-family:monospace;">' + totalStr + '</td>';
            html += '</tr>';
        }

        if (rows.length === 0) {
            html += '<tr><td colspan="8" style="padding:24px;text-align:center;color:#888;">暂无匹配的品种费率（请先获取费率数据）</td></tr>';
        }

        html += '</tbody></table>';
        html += '</div>';

        // ── Footer / Save bar (edit mode only) ──
        if (isEdit) {
            html += '<div id="' + PANEL_ID + '-footer" style="padding:12px 18px;border-top:1px solid #e5e7eb;background:' + (anyModified ? '#fff8e1' : '#f9fafb') + ';display:flex;align-items:center;justify-content:space-between;gap:8px;flex-shrink:0;">';
            html += '<span style="font-size:12px;color:#888;">提示：修改过的单元格以 <span style="background:#fff3cd;padding:1px 4px;border-radius:3px;">黄色背景</span> 标记。修改暂存在会话中，点击下方保存按钮写入。</span>';
            html += '<div style="display:flex;gap:6px;flex-shrink:0;">';
            html += '<button id="' + PANEL_ID + '-commit-btn" style="padding:6px 16px;font-size:12px;border:1px solid #0078d4;border-radius:4px;background:#0078d4;color:#fff;cursor:pointer;">✓ 写入暂存</button>';
            html += '<button id="' + PANEL_ID + '-close-btn" style="padding:6px 16px;font-size:12px;border:1px solid #ccc;border-radius:4px;background:#fff;color:#333;cursor:pointer;">关闭</button>';
            html += '</div>';
            html += '</div>';
        } else {
            html += '<div style="padding:10px 18px;border-top:1px solid #e5e7eb;background:#f9fafb;text-align:right;flex-shrink:0;">';
            html += '<button id="' + PANEL_ID + '-close-btn" style="padding:6px 16px;font-size:12px;border:1px solid #ccc;border-radius:4px;background:#fff;color:#333;cursor:pointer;">关闭</button>';
            html += '</div>';
        }

        panel.innerHTML = html;

        // ── Bind events ──
        var closeBtn = document.getElementById(PANEL_ID + '-close');
        var closeBtn2 = document.getElementById(PANEL_ID + '-close-btn');
        if (closeBtn)  closeBtn.addEventListener('click', closeConfigFeeOverlay);
        if (closeBtn2) closeBtn2.addEventListener('click', closeConfigFeeOverlay);

        if (isEdit) {
            var commitBtn = document.getElementById(PANEL_ID + '-commit-btn');
            if (commitBtn) commitBtn.addEventListener('click', _commitDirtyRows);

            // Bind editable cell blur
            var panelEl = document.getElementById(PANEL_ID);
            if (panelEl) {
                panelEl.querySelectorAll('[contenteditable="true"]').forEach(function(cell) {
                    cell.addEventListener('blur', _onCellBlur);
                    cell.addEventListener('keydown', function(e) {
                        if (e.key === 'Enter') { e.preventDefault(); this.blur(); }
                        if (e.key === 'Escape') { this.blur(); }
                    });
                });
            }
        }

        // Show
        document.getElementById(OVERLAY_ID).style.display = 'flex';
    }

    // ── Cell editing ─────────────────────────────────────────────────────────

    function _onCellBlur() {
        var variety = this.getAttribute('data-cf-variety');
        var field   = this.getAttribute('data-cf-field');
        var rawVal  = (this.textContent || '').trim();
        var val     = parseFloat(rawVal);

        if (isNaN(val) || val < 0) {
            // Restore original from raw rows
            _render(); // full re-render to restore
            return;
        }

        // Get original from raw fee rows
        var rawRows = (GT.fee && typeof GT.fee.getFeeRows === 'function') ? GT.fee.getFeeRows() : [];
        var origVal = null;
        for (var i = 0; i < rawRows.length; i++) {
            if (String(rawRows[i].code).toLowerCase() === variety) {
                origVal = rawRows[i][field];
                break;
            }
        }
        if (origVal === null || origVal === undefined) {
            origVal = 0;
        }

        var formatted = Number(val).toFixed(6);
        this.textContent = formatted;

        // Mark modified if differs from original
        if (Math.abs(val - Number(origVal)) < 1e-9) {
            this.classList.remove('fee-cell-modified');
        } else {
            this.classList.add('fee-cell-modified');
        }

        // Update bilateral total for this row
        _refreshTotal(variety);
    }

    function _refreshTotal(variety) {
        var panel = document.getElementById(PANEL_ID);
        if (!panel) return;

        var openCell = panel.querySelector('td[data-cf-variety="' + variety + '"][data-cf-field="open_ratio"]');
        var closeCell = panel.querySelector('td[data-cf-variety="' + variety + '"][data-cf-field="close_ratio"]');
        if (!openCell || !closeCell) return;

        var openVal  = parseFloat(openCell.textContent) || 0;
        var closeVal = parseFloat(closeCell.textContent) || 0;
        var totalPct = (openVal + closeVal) * 100;

        var tr = openCell.parentElement;
        if (tr) {
            var lastTd = tr.querySelector('td:last-child');
            if (lastTd) lastTd.textContent = totalPct > 0 ? totalPct.toFixed(4) + '%' : '—';
        }
    }

    /**
     * Collect all modified cells into feeMap and stage via REG.setDirty.
     */
    function _commitDirtyRows() {
        if (!_state || _state.mode !== 'edit') return;

        var REG = window.GT_CONFIG_REGISTRY;
        if (!REG) return;

        var panel = document.getElementById(PANEL_ID);
        if (!panel) return;

        var group  = _state.group;
        var existing = group.feeMap ? JSON.parse(JSON.stringify(group.feeMap)) : {};

        // Scan all editable cells
        var cells = panel.querySelectorAll('[contenteditable="true"]');
        for (var i = 0; i < cells.length; i++) {
            var cell     = cells[i];
            var variety  = cell.getAttribute('data-cf-variety');
            var field    = cell.getAttribute('data-cf-field');
            var rawVal   = parseFloat((cell.textContent || '').trim());
            if (isNaN(rawVal) || rawVal < 0) continue;

            // Get original to determine if actually modified
            var rawRows = (GT.fee && typeof GT.fee.getFeeRows === 'function') ? GT.fee.getFeeRows() : [];
            var origVal = null;
            for (var j = 0; j < rawRows.length; j++) {
                if (String(rawRows[j].code).toLowerCase() === variety) {
                    origVal = rawRows[j][field];
                    break;
                }
            }
            if (origVal === null || origVal === undefined) origVal = 0;

            if (Math.abs(rawVal - Number(origVal)) < 1e-9) continue; // not modified

            // Stage
            if (!existing[variety]) existing[variety] = {};
            existing[variety][field] = rawVal;
        }

        // Remove entries with no fields
        var cleaned = {};
        var keys = Object.keys(existing);
        for (var k = 0; k < keys.length; k++) {
            if (existing[keys[k]] && Object.keys(existing[keys[k]]).length > 0) {
                cleaned[keys[k]] = existing[keys[k]];
            }
        }

        REG.setDirty('feeMap', Object.keys(cleaned).length > 0 ? cleaned : null);

        // Update state for chip re-render
        _state.group.feeMap = cleaned;
        closeConfigFeeOverlay();
    }

    // ── Public API ──────────────────────────────────────────────────────────

    /**
     * Open the config fee overlay.
     *
     * @param {object}  group            — base group from datamodel
     * @param {string}  mode             — 'edit' or 'view'
     * @param {function} [onClose]       — called after overlay closes (e.g. to re-render chips)
     */
    var _fetchPromise = null; // Prevent concurrent fetches

    function openConfigFeeOverlay(group, mode, onClose) {
        ensureOverlay();

        // Ensure fee data is loaded
        var feeRows = (GT.fee && typeof GT.fee.getFeeRows === 'function') ? GT.fee.getFeeRows() : [];
        if (feeRows.length === 0) {
            if (GT.fee && typeof GT.fee.fetchFeeTable === 'function') {
                if (!_fetchPromise) {
                    _fetchPromise = GT.fee.fetchFeeTable(false).then(function(rows) {
                        _fetchPromise = null;
                        if (!rows || rows.length === 0) return; // fetch returned empty, don't retry
                        openConfigFeeOverlay(group, mode, onClose);
                    }).catch(function() {
                        _fetchPromise = null;
                    });
                }
            }
            return;
        }

        var products = _getProductCodes(group);

        _state = {
            group:    group,
            mode:     mode || 'view',
            products: products,
            closeFn:  onClose || null,
        };

        _render();
    }

    function closeConfigFeeOverlay() {
        var overlay = document.getElementById(OVERLAY_ID);
        if (overlay) overlay.style.display = 'none';

        if (_state && typeof _state.closeFn === 'function') {
            try { _state.closeFn(); } catch (e) {}
        }
        _state = null;
    }

    // ── Export ───────────────────────────────────────────────────────────────

    GT.overlays.configFeeTable = {
        open:  openConfigFeeOverlay,
        close: closeConfigFeeOverlay,
    };
})();
