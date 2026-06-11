/**
 * panels/config/fee/table.js — Read-only fee table with row selection.
 *
 * Renders the fee table for the overlay. Supports:
 *   - Product filtering (only tester's products)
 *   - Row click → select (highlight blue), single selection
 *   - Modifications applied visually (modified cells get yellow bg)
 *   - Per-lot fee calculation columns
 *
 * Depends on GT.fee.* (index.js) for data + modifications.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) return;

    GT.overlays = GT.overlays || {};
    var _configFee = GT.overlays._configFee || {};
    GT.overlays._configFee = _configFee;

    // ── Constants ──────────────────────────────────────────────────────────

    var TABLE_THEAD_BG = '#f0f4f8';
    var ROW_HOVER_BG   = '#f8fafc';
    var ROW_SELECTED_BG = '#dbeafe';
    var CELL_MODIFIED_BG = '#fff3cd';
    var TEXT_MUTED      = '#888';

    // ── Helpers ────────────────────────────────────────────────────────────

    function esc(str) { return GT.escapeHTML ? GT.escapeHTML(str) : String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

    function fmtNum(v, dec) {
        var n = Number(v);
        if (isNaN(n)) return '—';
        return n.toFixed(dec || 6);
    }

    /**
     * Get tester products as uppercase variety codes.
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
                        var raw = typeof p === 'string' ? p : (p.name || '');
                        var dotIdx = raw.indexOf('.');
                        return (dotIdx >= 0 ? raw.substring(0, dotIdx) : raw).toUpperCase();
                    });
                }
                break;
            }
        }
        return [];
    }

    /**
     * Build row data from raw fee rows + modifications.
     *
     * Returns [{code, name, exchange, multiplier, min_tick,
     *           open_ratio, close_ratio, closetoday_ratio,
     *           open_fixed, close_fixed, closetoday_fixed,
     *           fieldsModified: {open_ratio:true, ...},
     *           buyPerLot, sellPerLot}]
     */
    function _buildRowData(group) {
        var rawRows = (GT.fee && typeof GT.fee.getFeeRows === 'function') ? GT.fee.getFeeRows() : [];
        var productSet = null;
        var products = _getProductCodes(group);
        if (products.length > 0) {
            productSet = {};
            for (var i = 0; i < products.length; i++) {
                productSet[products[i].toUpperCase()] = true;
            }
        }

        var rows = [];
        for (var j = 0; j < rawRows.length; j++) {
            var r = rawRows[j];
            var code = String(r.variety_code || r.code || '').toUpperCase();
            if (productSet && !productSet[code]) continue;

            // Apply modifications (sorted by timestamp, later wins)
            var applied = {};
            if (GT.fee && typeof GT.fee.applyModificationsToRow === 'function') {
                applied = GT.fee.applyModificationsToRow(code, r, null);
            } else {
                applied = {
                    open_ratio: r.open_ratio, close_ratio: r.close_ratio, closetoday_ratio: r.closetoday_ratio,
                    open_fixed: r.open_fixed, close_fixed: r.close_fixed, closetoday_fixed: r.closetoday_fixed,
                    fieldsModified: {}
                };
            }

            // Per-lot fee: (open_ratio + close_ratio) * price_approx → but we don't have price;
            // show components: ratio% * multiplier and fixed fees
            var mlt = Number(r.multiplier) || 1;
            var openRatio  = Number(applied.open_ratio)  || 0;
            var closeRatio = Number(applied.close_ratio) || 0;
            var cTDRatio   = Number(applied.closetoday_ratio) || 0;
            var openFixed  = Number(applied.open_fixed)  || 0;
            var closeFixed = Number(applied.close_fixed) || 0;
            var cTDFixed   = Number(applied.closetoday_fixed) || 0;

            // Approximate per-lot fee (no price): percentage part * multiplier ≈ notional-based
            // Show both ratio-based total and fixed total separately
            var buyPerLotPct  = (openRatio + closeRatio) * 100;  // percentage
            var buyPerLotFix  = openFixed + closeFixed;
            var sellPerLotPct = (openRatio + cTDRatio) * 100;
            var sellPerLotFix = openFixed + cTDFixed;

            rows.push({
                code:             code,
                name:             r.name || r.variety_name || '',
                exchange:         r.exchange || '',
                multiplier:       mlt,
                min_tick:         (r.min_tick != null) ? r.min_tick : '',
                open_ratio:       openRatio,
                close_ratio:      closeRatio,
                closetoday_ratio: cTDRatio,
                open_fixed:       openFixed,
                close_fixed:      closeFixed,
                closetoday_fixed: cTDFixed,
                fieldsModified:   applied.fieldsModified || {},
                // Per-lot fee components
                buyPerLotPct:     buyPerLotPct,
                buyPerLotFix:     buyPerLotFix,
                sellPerLotPct:    sellPerLotPct,
                sellPerLotFix:    sellPerLotFix,
            });
        }
        return rows;
    }

    // ── State ──────────────────────────────────────────────────────────────

    var _selectedCode = null;        // currently selected variety_code

    // ── Render ─────────────────────────────────────────────────────────────

    /**
     * Render the fee table into a container element.
     *
     * @param {HTMLElement} container - target DOM element
     * @param {object}      [group]   - group settings (falls back to _configFee.getGroup())
     */
    function renderFeeTable(container, group) {
        if (!group) group = (_configFee && _configFee.getGroup) ? _configFee.getGroup() : null;

        var rows = _buildRowData(group);

        var html = '';
        html += '<div id="fee-table-scroll" style="flex:1;overflow-y:auto;padding:4px 0;">';
        html += '<table id="fee-table" style="width:100%;border-collapse:collapse;font-size:12px;">';

        // ── Header ──
        html += '<thead><tr style="background:' + TABLE_THEAD_BG + ';position:sticky;top:0;z-index:2;border-bottom:2px solid #d0d7de;">';
        html += '<th style="padding:8px 10px;text-align:left;color:#0f4c81;font-weight:600;">品种代码</th>';
        html += '<th style="padding:8px 10px;text-align:left;color:#0f4c81;font-weight:600;">名称</th>';
        html += '<th style="padding:8px 10px;text-align:left;color:#0f4c81;font-weight:600;">交易所</th>';
        html += '<th style="padding:8px 8px;text-align:right;color:#0f4c81;font-weight:600;">乘数</th>';
        html += '<th style="padding:8px 8px;text-align:right;color:#0f4c81;font-weight:600;">最小变动</th>';
        html += '<th style="padding:8px 8px;text-align:right;color:#0f4c81;font-weight:600;">开仓比率</th>';
        html += '<th style="padding:8px 8px;text-align:right;color:#0f4c81;font-weight:600;">开仓费用</th>';
        html += '<th style="padding:8px 8px;text-align:right;color:#0f4c81;font-weight:600;">平今比率</th>';
        html += '<th style="padding:8px 8px;text-align:right;color:#0f4c81;font-weight:600;">平今费用</th>';
        html += '<th style="padding:8px 8px;text-align:right;color:#0f4c81;font-weight:600;">平昨比率</th>';
        html += '<th style="padding:8px 8px;text-align:right;color:#0f4c81;font-weight:600;">平昨费用</th>';
        html += '<th style="padding:8px 8px;text-align:right;color:#0f4c81;font-weight:600;">买1手(‰)</th>';
        html += '<th style="padding:8px 8px;text-align:right;color:#0f4c81;font-weight:600;">卖1手(‰)</th>';
        html += '</tr></thead><tbody>';

        // ── Rows ──
        for (var i = 0; i < rows.length; i++) {
            var row = rows[i];
            var fm = row.fieldsModified;
            var hasMod = (fm.open_ratio || fm.close_ratio || fm.closetoday_ratio ||
                          fm.open_fixed || fm.close_fixed || fm.closetoday_fixed);
            var isSelected = (_selectedCode === row.code);
            var rowStyle = 'border-bottom:1px solid #eef2f7;cursor:pointer;';
            if (isSelected) rowStyle += 'background:' + ROW_SELECTED_BG + ';';

            html += '<tr data-fee-variety="' + row.code + '" style="' + rowStyle + '">';
            html += '<td style="padding:6px 10px;font-weight:600;font-family:monospace;">' + esc(row.code) + '</td>';
            html += '<td style="padding:6px 10px;color:#555;">' + esc(row.name) + '</td>';
            html += '<td style="padding:6px 10px;color:#555;">' + esc(row.exchange) + '</td>';
            html += '<td style="padding:6px 8px;text-align:right;">' + esc(row.multiplier) + '</td>';
            html += '<td style="padding:6px 8px;text-align:right;font-family:monospace;">' + esc(row.min_tick) + '</td>';

            // Ratio columns (with modification highlight)
            html += _cellTD(fmtNum(row.open_ratio),   fm.open_ratio);
            html += _cellTD(fmtNum(row.open_fixed, 2), fm.open_fixed);
            html += _cellTD(fmtNum(row.closetoday_ratio),   fm.closetoday_ratio);
            html += _cellTD(fmtNum(row.closetoday_fixed, 2), fm.closetoday_fixed);
            html += _cellTD(fmtNum(row.close_ratio),   fm.close_ratio);
            html += _cellTD(fmtNum(row.close_fixed, 2), fm.close_fixed);

            // Per-lot fee: buy = open+close_yday, sell = open+close_today
            var buyPctStr  = row.buyPerLotPct > 0 ? row.buyPerLotPct.toFixed(2) + '‰' : '—';
            var sellPctStr = row.sellPerLotPct > 0 ? row.sellPerLotPct.toFixed(2) + '‰' : '—';
            html += '<td style="padding:6px 8px;text-align:right;font-family:monospace;">' + buyPctStr + '</td>';
            html += '<td style="padding:6px 8px;text-align:right;font-family:monospace;">' + sellPctStr + '</td>';

            html += '</tr>';
        }

        if (rows.length === 0) {
            html += '<tr><td colspan="13" style="padding:24px;text-align:center;color:' + TEXT_MUTED + ';">暂无匹配的品种费率</td></tr>';
        }

        html += '</tbody></table>';
        html += '</div>';

        container.innerHTML = html;

        // ── Bind row clicks ──
        var table = container.querySelector('#fee-table');
        if (table) {
            var trs = table.querySelectorAll('tbody tr[data-fee-variety]');
            for (var k = 0; k < trs.length; k++) {
                trs[k].addEventListener('click', _onRowClick);
                trs[k].addEventListener('mouseenter', function() {
                    if (this.getAttribute('data-fee-variety') !== _selectedCode) {
                        this.style.background = ROW_HOVER_BG;
                    }
                });
                trs[k].addEventListener('mouseleave', function() {
                    if (this.getAttribute('data-fee-variety') !== _selectedCode) {
                        this.style.background = '';
                    }
                });
            }
        }
    }

    // ── Cell helper ────────────────────────────────────────────────────────

    function _cellTD(text, isModified) {
        var style = 'padding:6px 8px;text-align:right;font-family:monospace;';
        if (isModified) style += 'background:' + CELL_MODIFIED_BG + ';';
        return '<td style="' + style + '">' + text + '</td>';
    }

    // ── Events ─────────────────────────────────────────────────────────────

    function _onRowClick() {
        var table = document.getElementById('fee-table');
        if (!table) return;

        // Clear previous selection
        var prevSelected = table.querySelectorAll('tr.fee-row-selected');
        for (var i = 0; i < prevSelected.length; i++) {
            prevSelected[i].classList.remove('fee-row-selected');
            prevSelected[i].style.background = '';
        }

        // Select this row
        var code = this.getAttribute('data-fee-variety');
        this.classList.add('fee-row-selected');
        this.style.background = ROW_SELECTED_BG;
        _selectedCode = code;

        // Find row data
        var group = (_configFee && _configFee.getGroup) ? _configFee.getGroup() : null;
        var rows = _buildRowData(group);
        var rowData = null;
        for (var j = 0; j < rows.length; j++) {
            if (rows[j].code === code) { rowData = rows[j]; break; }
        }

        // Fire the onSelectRow callback (set by modification.js)
        if (_configFee && typeof _configFee.onSelectRow === 'function') {
            _configFee.onSelectRow(code, rowData);
        }
    }

    // ── Public API ─────────────────────────────────────────────────────────

    /**
     * Get the currently selected variety code.
     */
    function getSelectedCode() {
        return _selectedCode;
    }

    /**
     * Clear selection (programmatic).
     */
    function clearSelection() {
        _selectedCode = null;
        var table = document.getElementById('fee-table');
        if (table) {
            var rows = table.querySelectorAll('tr.fee-row-selected');
            for (var i = 0; i < rows.length; i++) {
                rows[i].classList.remove('fee-row-selected');
                rows[i].style.background = '';
            }
        }
    }

    _configFee.table = {
        render: renderFeeTable,
        getSelectedCode: getSelectedCode,
        clearSelection: clearSelection,
        buildRowData: _buildRowData,
    };

    // Register render hook on overlay (loaded before table.js via script order)
    if (GT.overlays && GT.overlays.configFeeTable) {
        GT.overlays.configFeeTable._renderTable = function(container) {
            renderFeeTable(container);
        };
    }

})();


