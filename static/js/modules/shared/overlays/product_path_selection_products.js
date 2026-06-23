/**
 * shared/overlays/product_path_selection_products.js — Product-path selection overlay
 *
 * Clicking a product-path-selection chip opens a centered overlay showing the
 * selected path list and the resolved product list.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) return;

    GT.overlays = GT.overlays || {};

    var OVERLAY_ID = 'grouptest-product-path-selection-overlay';
    var PANEL_ID   = 'grouptest-product-path-selection-panel';
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
        panel.style.cssText = 'position:relative;width:min(92vw,860px);height:min(78vh,560px);background:#fff;border-radius:8px;box-shadow:0 8px 40px rgba(0,0,0,0.2);display:flex;flex-direction:column;overflow:hidden;';
        overlay.appendChild(panel);

        document.body.appendChild(overlay);
        return overlay;
    }

    function buildProductsUrl(productName) {
        return '/products?product=' + encodeURIComponent(productName);
    }

    function normalizePaths(selection) {
        var raw = (selection && (selection.paths || selection.selected_paths || selection.product_paths)) || [];
        return (raw || []).map(function(item) {
            if (typeof item === 'string') return normalizePathItem(item, '');
            if (!item) return null;
            var label = item.path || item.label || item.name || item.key || '';
            var desc = item.desc || item.description || '';
            return label ? normalizePathItem(label, desc) : null;
        }).filter(Boolean);
    }

    function normalizePathItem(label, desc) {
        var text = String(label || '');
        var sign = '+';
        if (text.charAt(0) === '-') {
            sign = '-';
            text = text.slice(1);
        } else if (text.charAt(0) === '+') {
            text = text.slice(1);
        }
        return { sign: sign, label: text, desc: desc || '' };
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
        var paths = normalizePaths(selection);

        var html = '';
        html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid #e5e7eb;background:#f9fafb;">';
        html += '<div style="min-width:0;">';
        html += '<strong style="font-size:13px;color:#1f2937;">产品路径组</strong>';
        html += '<span style="margin-left:8px;font-size:12px;color:#475467;">' + escapeHTML(selectionName || '') + '</span>';
        html += '</div>';
        html += '<button type="button" id="' + PANEL_ID + '-close" style="background:none;border:none;font-size:20px;cursor:pointer;color:#888;line-height:1;">&times;</button>';
        html += '</div>';

        html += '<div style="flex:1;display:grid;grid-template-columns:minmax(360px,58%) minmax(260px,42%);min-height:0;">';
        html += '<div style="min-width:0;min-height:0;border-right:1px solid #e5e7eb;display:flex;flex-direction:column;">';
        html += '<div style="padding:7px 10px;border-bottom:1px solid #eef2f7;font-size:12px;font-weight:700;color:#475467;">路径列表 <span style="font-weight:500;color:#98a2b3;">' + paths.length + '</span></div>';
        html += '<div style="flex:1;min-height:0;overflow:auto;background:#fff;">';
        if (!paths.length) {
            html += '<div style="padding:14px;text-align:center;color:#888;font-size:12px;">暂无路径数据</div>';
        } else {
            html += '<ul style="list-style:none;margin:0;padding:4px 0;">';
            for (var pi = 0; pi < paths.length; pi++) {
                var signColor = paths[pi].sign === '-' ? '#b42318' : '#166534';
                var signBg = paths[pi].sign === '-' ? '#fef2f2' : '#ecfdf3';
                html += '<li style="display:grid;grid-template-columns:24px minmax(0,1fr);gap:6px;align-items:start;padding:5px 10px;border-bottom:1px solid #f1f5f9;font-size:12px;line-height:1.35;color:#334155;">';
                html += '<span style="display:inline-flex;align-items:center;justify-content:center;width:20px;height:18px;border-radius:4px;background:' + signBg + ';color:' + signColor + ';font-weight:700;font-size:12px;line-height:1;">' + paths[pi].sign + '</span>';
                html += '<span style="min-width:0;">';
                html += '<div style="font-family:monospace;white-space:normal;overflow:visible;word-break:break-all;" title="' + escapeHTML(paths[pi].label) + '">' + escapeHTML(paths[pi].label) + '</div>';
                if (paths[pi].desc) html += '<div style="margin-top:1px;color:#94a3b8;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + escapeHTML(paths[pi].desc) + '</div>';
                html += '</span>';
                html += '</li>';
            }
            html += '</ul>';
        }
        html += '</div>';
        html += '</div>';
        html += '<div style="min-width:0;min-height:0;overflow-y:auto;padding:4px 0;">';
        html += '<table style="width:100%;border-collapse:collapse;font-size:12px;">';
        html += '<thead><tr style="background:#f0f4f8;position:sticky;top:0;">';
        html += '<th style="padding:6px 10px;text-align:left;">产品 <span style="font-weight:500;color:#64748b;">' + (products ? products.length : 0) + '</span></th>';
        html += '<th style="padding:6px 10px;text-align:left;">描述</th>';
        html += '</tr></thead><tbody>';

        if (!products || !products.length) {
            html += '<tr><td colspan="2" style="padding:24px;text-align:center;color:#888;">暂无产品数据</td></tr>';
        } else {
            for (var i = 0; i < products.length; i++) {
                var p = products[i];
                var name = p.name || '';
                var desc = p.desc || '';
                html += '<tr style="border-bottom:1px solid #eef2f7;">';
                html += '<td style="padding:5px 10px;">';
                html += '<a href="' + buildProductsUrl(name) + '" target="_blank" style="font-weight:600;font-family:monospace;color:#0078d4;text-decoration:none;" onmouseover="this.style.textDecoration=\'underline\'" onmouseout="this.style.textDecoration=\'none\'">' + escapeHTML(name) + '</a>';
                html += '</td>';
                html += '<td style="padding:5px 10px;color:#555;">' + escapeHTML(desc) + '</td>';
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

        // Show
        document.getElementById(OVERLAY_ID).style.display = 'flex';
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
