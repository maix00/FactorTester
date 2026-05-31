/**
 * overlays/fee_table.js — Per-product fee table overlay
 *
 * Reusable overlay for displaying per-product fee rates from FeeData.
 * Accepts an optional productFilter (array of product codes) to show only
 * relevant rows. Product codes are displayed in UPPERCASE.
 *
 * If fee data hasn't been loaded yet, auto-fetches and opens on completion.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) return;

    GT.overlays = GT.overlays || {};

    var OVERLAY_ID = 'grouptest-fee-table-overlay';
    var PANEL_ID   = 'grouptest-fee-table-panel';

    // ── DOM helpers ──────────────────────────────────────────────────────────

    function escapeHTML(str) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    function ensureOverlay() {
        var overlay = document.getElementById(OVERLAY_ID);
        if (overlay) return overlay;

        overlay = document.createElement('div');
        overlay.id = OVERLAY_ID;
        overlay.style.cssText = 'display:none;position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,0.35);align-items:center;justify-content:center;';
        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) closeFeeTableOverlay();
        });

        var panel = document.createElement('div');
        panel.id = PANEL_ID;
        panel.style.cssText = 'position:relative;width:min(94vw,900px);max-height:min(88vh,650px);background:#fff;border-radius:10px;box-shadow:0 8px 40px rgba(0,0,0,0.2);display:flex;flex-direction:column;overflow:hidden;';
        overlay.appendChild(panel);

        document.body.appendChild(overlay);
        return overlay;
    }

    // ── Public API ──────────────────────────────────────────────────────────

    /**
     * Open fee table overlay.
     * @param {string} title - display title (e.g. group name)
     * @param {Array<string>|null} productFilter - optional product codes to filter by; null/empty = show all
     */
    function openFeeTableOverlay(title, productFilter) {
        ensureOverlay();

        var feeRows = (GT.fee && typeof GT.fee.getFeeRows === 'function') ? GT.fee.getFeeRows() : [];
        if (feeRows.length === 0) {
            // Auto-fetch then retry
            if (GT.fee && typeof GT.fee.fetchFeeTable === 'function') {
                GT.fee.fetchFeeTable(false).then(function() {
                    openFeeTableOverlay(title, productFilter);
                }).catch(function() {});
            }
            return;
        }

        // Build product filter set (uppercased for case-insensitive matching)
        var filterSet = null;
        if (productFilter && productFilter.length > 0) {
            filterSet = {};
            for (var fi = 0; fi < productFilter.length; fi++) {
                filterSet[String(productFilter[fi]).toUpperCase()] = true;
            }
        }

        var useCT = (GT.fee && typeof GT.fee.useCloseToday === 'function') ? GT.fee.useCloseToday() : false;
        var ctLabel = useCT ? '平今仓' : '平昨仓';

        var panel = document.getElementById(PANEL_ID);
        if (!panel) return;

        var html = '';
        html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid #e5e7eb;background:#f9fafb;">';
        html += '<div>';
        html += '<strong style="font-size:15px;color:#1f2937;">💰 品种费率 — ' + escapeHTML(title || '') + '</strong>';
        html += '<span style="margin-left:10px;font-size:12px;color:#888;">平仓口径：' + ctLabel + '</span>';
        html += '</div>';
        html += '<button id="' + PANEL_ID + '-close" style="background:none;border:none;font-size:22px;cursor:pointer;color:#888;line-height:1;">&times;</button>';
        html += '</div>';

        html += '<div style="flex:1;overflow-y:auto;padding:4px 0;">';
        html += '<table style="width:100%;border-collapse:collapse;font-size:13px;">';
        html += '<thead><tr style="background:#f0f4f8;position:sticky;top:0;">';
        html += '<th style="padding:8px 12px;text-align:left;">品种</th>';
        html += '<th style="padding:8px 12px;text-align:left;">描述</th>';
        html += '<th style="padding:8px 12px;text-align:right;">建仓</th>';
        html += '<th style="padding:8px 12px;text-align:right;">平仓(平昨)</th>';
        html += '<th style="padding:8px 12px;text-align:right;">平仓(平今)</th>';
        html += '<th style="padding:8px 12px;text-align:right;">双边(平昨)</th>';
        html += '<th style="padding:8px 12px;text-align:right;">双边(平今)</th>';
        html += '</tr></thead><tbody>';

        var shown = 0;
        for (var i = 0; i < feeRows.length; i++) {
            var row = feeRows[i];
            var code = String(row.code).toUpperCase();

            // Apply filter
            if (filterSet && !filterSet[code]) continue;

            shown++;
            var openRate = Number(row.open_ratio).toFixed(6);
            var closeYesterday = useCT ? '—' : Number(row.close_ratio).toFixed(6);
            var closeToday = useCT ? Number(row.closetoday_ratio).toFixed(6) : '—';
            var bothYesterday = useCT ? '—' : (Number(row.open_ratio) + Number(row.close_ratio)).toFixed(6);
            var bothToday = useCT ? (Number(row.open_ratio) + Number(row.closetoday_ratio)).toFixed(6) : '—';

            html += '<tr style="border-bottom:1px solid #eef2f7;">';
            html += '<td style="padding:8px 12px;font-weight:600;font-family:monospace;">' + escapeHTML(code) + '</td>';
            html += '<td style="padding:8px 12px;color:#555;">' + escapeHTML(row.name) + '</td>';
            html += '<td style="padding:8px 12px;text-align:right;font-family:monospace;">' + openRate + '</td>';
            html += '<td style="padding:8px 12px;text-align:right;font-family:monospace;">' + closeYesterday + '</td>';
            html += '<td style="padding:8px 12px;text-align:right;font-family:monospace;">' + closeToday + '</td>';
            html += '<td style="padding:8px 12px;text-align:right;font-family:monospace;">' + bothYesterday + '</td>';
            html += '<td style="padding:8px 12px;text-align:right;font-family:monospace;">' + bothToday + '</td>';
            html += '</tr>';
        }

        if (shown === 0) {
            html += '<tr><td colspan="7" style="padding:24px;text-align:center;color:#888;">暂无匹配的品种费率</td></tr>';
        }

        html += '</tbody></table>';
        html += '</div>';

        panel.innerHTML = html;

        // Bind close button
        var closeBtn = document.getElementById(PANEL_ID + '-close');
        if (closeBtn) closeBtn.addEventListener('click', closeFeeTableOverlay);

        // Show
        document.getElementById(OVERLAY_ID).style.display = 'flex';
    }

    function closeFeeTableOverlay() {
        var overlay = document.getElementById(OVERLAY_ID);
        if (overlay) overlay.style.display = 'none';
    }

    // Expose to GT.overlays
    GT.overlays.feeTable = {
        open:  openFeeTableOverlay,
        close: closeFeeTableOverlay,
    };
})();
