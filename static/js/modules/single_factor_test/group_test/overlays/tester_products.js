/**
 * overlays/tester_products.js — Tester product list overlay
 *
 * Clicking a tester link opens a centered overlay showing all products
 * with their descriptions. Each product name links to the price viewer.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) return;

    GT.overlays = GT.overlays || {};

    var OVERLAY_ID = 'grouptest-tester-products-overlay';
    var PANEL_ID   = 'grouptest-tester-products-panel';

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
            if (e.target === overlay) closeTesterProductsOverlay();
        });

        var panel = document.createElement('div');
        panel.id = PANEL_ID;
        panel.style.cssText = 'position:relative;width:min(92vw,700px);max-height:min(85vh,600px);background:#fff;border-radius:10px;box-shadow:0 8px 40px rgba(0,0,0,0.2);display:flex;flex-direction:column;overflow:hidden;';
        overlay.appendChild(panel);

        document.body.appendChild(overlay);
        return overlay;
    }

    function buildPriceViewerUrl(productName) {
        // Navigate to price_viewer page with product name as param
        return '/price_viewer?product=' + encodeURIComponent(productName);
    }

    // ── Public API ──────────────────────────────────────────────────────────

    /**
     * Open tester products overlay.
     * @param {string} testerName - display name of the tester
     * @param {Array<{name:string, desc:string}>} products
     */
    function openTesterProductsOverlay(testerName, products) {
        ensureOverlay();

        var panel = document.getElementById(PANEL_ID);
        if (!panel) return;

        var html = '';
        html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid #e5e7eb;background:#f9fafb;">';
        html += '<strong style="font-size:15px;color:#1f2937;">📦 测试器产品 — ' + escapeHTML(testerName || '') + '</strong>';
        html += '<button id="' + PANEL_ID + '-close" style="background:none;border:none;font-size:22px;cursor:pointer;color:#888;line-height:1;">&times;</button>';
        html += '</div>';

        html += '<div style="flex:1;overflow-y:auto;padding:4px 0;">';
        html += '<table style="width:100%;border-collapse:collapse;font-size:13px;">';
        html += '<thead><tr style="background:#f0f4f8;position:sticky;top:0;">';
        html += '<th style="padding:8px 14px;text-align:left;">品种</th>';
        html += '<th style="padding:8px 14px;text-align:left;">描述</th>';
        html += '</tr></thead><tbody>';

        if (!products || !products.length) {
            html += '<tr><td colspan="2" style="padding:24px;text-align:center;color:#888;">暂无产品数据</td></tr>';
        } else {
            for (var i = 0; i < products.length; i++) {
                var p = products[i];
                var name = p.name || '';
                var desc = p.desc || '';
                html += '<tr style="border-bottom:1px solid #eef2f7;">';
                html += '<td style="padding:8px 14px;">';
                html += '<a href="' + escapeHTML(buildPriceViewerUrl(name)) + '" target="_blank" style="font-weight:600;font-family:monospace;color:#0078d4;text-decoration:none;">' + escapeHTML(name) + '</a>';
                html += '</td>';
                html += '<td style="padding:8px 14px;color:#555;">' + escapeHTML(desc) + '</td>';
                html += '</tr>';
            }
        }

        html += '</tbody></table>';
        html += '</div>';

        panel.innerHTML = html;

        // Bind close button
        var closeBtn = document.getElementById(PANEL_ID + '-close');
        if (closeBtn) closeBtn.addEventListener('click', closeTesterProductsOverlay);

        // Show
        document.getElementById(OVERLAY_ID).style.display = 'flex';
    }

    function closeTesterProductsOverlay() {
        var overlay = document.getElementById(OVERLAY_ID);
        if (overlay) overlay.style.display = 'none';
    }

    // Expose to GT.overlays
    GT.overlays.testerProducts = {
        open:  openTesterProductsOverlay,
        close: closeTesterProductsOverlay,
    };
})();
