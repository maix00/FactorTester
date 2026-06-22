/**
 * shared/overlays/product_path_selection_products.js — Product-path selection overlay
 *
 * Clicking a product-path-selection chip opens a centered overlay showing the
 * product tree and the resolved product list.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) return;

    GT.overlays = GT.overlays || {};

    var OVERLAY_ID = 'grouptest-product-path-selection-overlay';
    var PANEL_ID   = 'grouptest-product-path-selection-panel';
    var _tree = null;

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
            if (e.target === overlay) closeProductPathSelectionOverlay();
        });

        var panel = document.createElement('div');
        panel.id = PANEL_ID;
        panel.style.cssText = 'position:relative;width:min(94vw,980px);height:min(86vh,680px);background:#fff;border-radius:10px;box-shadow:0 8px 40px rgba(0,0,0,0.2);display:flex;flex-direction:column;overflow:hidden;';
        overlay.appendChild(panel);

        document.body.appendChild(overlay);
        return overlay;
    }

    function buildProductsUrl(productName) {
        return '/products?product=' + encodeURIComponent(productName);
    }

    // ── Public API ──────────────────────────────────────────────────────────

    /**
     * Open product-path-selection overlay.
     * @param {string} selectionName - display name of the selection
     * @param {Array<{name:string, desc:string}>} products
     * @param {object=} selection
     */
    function openProductPathSelectionOverlay(selectionName, products, selection) {
        ensureOverlay();

        var panel = document.getElementById(PANEL_ID);
        if (!panel) return;
        var paths = (selection && (selection.paths || selection.selected_paths)) || [];

        var html = '';
        html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid #e5e7eb;background:#f9fafb;">';
        html += '<strong style="font-size:15px;color:#1f2937;">产品路径选择 — ' + escapeHTML(selectionName || '') + '</strong>';
        html += '<button id="' + PANEL_ID + '-close" style="background:none;border:none;font-size:22px;cursor:pointer;color:#888;line-height:1;">&times;</button>';
        html += '</div>';

        html += '<div style="flex:1;display:grid;grid-template-columns:minmax(320px,42%) minmax(360px,1fr);min-height:0;">';
        html += '<div style="min-width:0;min-height:0;border-right:1px solid #e5e7eb;display:flex;flex-direction:column;">';
        html += '<div style="padding:8px 12px;border-bottom:1px solid #eef2f7;font-size:12px;font-weight:700;color:#475467;">产品树</div>';
        html += '<div id="' + PANEL_ID + '-tree" style="flex:1;min-height:0;overflow:auto;padding:8px;background:#fff;"></div>';
        html += '</div>';
        html += '<div style="min-width:0;min-height:0;overflow-y:auto;padding:4px 0;">';
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
                html += '<a href="' + buildProductsUrl(name) + '" target="_blank" style="font-weight:600;font-family:monospace;color:#0078d4;text-decoration:none;" onmouseover="this.style.textDecoration=\'underline\'" onmouseout="this.style.textDecoration=\'none\'">' + escapeHTML(name) + '</a>';
                html += '</td>';
                html += '<td style="padding:8px 14px;color:#555;">' + escapeHTML(desc) + '</td>';
                html += '</tr>';
            }
        }

        html += '</tbody></table>';
        html += '</div>';
        html += '</div>';

        panel.innerHTML = html;

        // Bind close button
        var closeBtn = document.getElementById(PANEL_ID + '-close');
        if (closeBtn) closeBtn.addEventListener('click', closeProductPathSelectionOverlay);
        mountProductTree(paths);

        // Show
        document.getElementById(OVERLAY_ID).style.display = 'flex';
    }

    function mountProductTree(paths) {
        var treeEl = document.getElementById(PANEL_ID + '-tree');
        if (!treeEl) return;
        if (!window.ProductSelector || !window.jQuery) {
            treeEl.innerHTML = '<div style="padding:12px;color:#667085;font-size:12px;">产品树组件未加载</div>';
            return;
        }
        window.ProductSelector.createTree(window.jQuery(treeEl), {
            onInit: function(tree) {
                _tree = tree;
                window.ProductSelector.restoreChecks(tree, paths || []);
            },
        });
    }

    function closeProductPathSelectionOverlay() {
        var overlay = document.getElementById(OVERLAY_ID);
        if (overlay) overlay.style.display = 'none';
    }

    // Expose to GT.overlays
    GT.overlays.productPathSelectionProducts = {
        open:  openProductPathSelectionOverlay,
        close: closeProductPathSelectionOverlay,
    };
})();
