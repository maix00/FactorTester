/**
 * shared/overlays/factor_info.js — Factor info overlay
 *
 * Clicking a factor candidate opens a centered overlay with two tabs:
 *   tab1 "公式与参数" — rendered LaTeX formula (via window.renderDrawerMathAndDesc,
 *        the same MathJax helper used by the parameter drawer) + resolved params
 *   tab2 "后端信息"   — reflected backend fields (window.OverlayFieldsTable)
 *
 * Expects a factor entry shaped like one item from /api/factor_list:
 *   {alias, name, latex, backend_fields, param_defs, ...}
 */
(function() {
    var OVERLAY_ID = 'factor-info-overlay';
    var PANEL_ID = 'factor-info-panel';
    var TAB_FORMULA = 'formula';
    var TAB_BACKEND = 'backend';
    var _activeTab = TAB_FORMULA;

    function escapeHTML(str) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(str == null ? '' : String(str)));
        return div.innerHTML;
    }

    function ensureOverlay() {
        var overlay = document.getElementById(OVERLAY_ID);
        if (overlay) return overlay;

        overlay = document.createElement('div');
        overlay.id = OVERLAY_ID;
        overlay.style.cssText = 'display:none;position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,0.35);align-items:center;justify-content:center;';
        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) closeFactorInfoOverlay();
        });

        var panel = document.createElement('div');
        panel.id = PANEL_ID;
        panel.style.cssText = 'position:relative;width:min(92vw,760px);height:min(78vh,560px);background:#fff;border-radius:8px;box-shadow:0 8px 40px rgba(0,0,0,0.2);display:flex;flex-direction:column;overflow:hidden;';
        overlay.appendChild(panel);

        document.body.appendChild(overlay);
        return overlay;
    }

    function renderParamRows(paramDefs) {
        var keys = Object.keys(paramDefs || {});
        if (!keys.length) return '<div style="color:#888;font-size:12px;padding:8px 0;">无参数</div>';
        var html = '<table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px;">';
        html += '<thead><tr style="background:#f0f4f8;"><th style="padding:5px 10px;text-align:left;">参数</th><th style="padding:5px 10px;text-align:left;">值</th></tr></thead><tbody>';
        keys.forEach(function(key) {
            var entry = paramDefs[key] || {};
            var display = entry.alias != null && entry.alias !== '' ? entry.alias : entry.value;
            html += '<tr style="border-bottom:1px solid #eef2f7;">';
            html += '<td style="padding:5px 10px;font-family:monospace;color:#334155;">' + escapeHTML(key) + '</td>';
            html += '<td style="padding:5px 10px;color:#555;">' + escapeHTML(display) + '</td>';
            html += '</tr>';
        });
        html += '</tbody></table>';
        return html;
    }

    function renderTabs(factorEntry) {
        var panel = document.getElementById(PANEL_ID);
        if (!panel) return;

        var html = '';
        html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid #e5e7eb;background:#f9fafb;">';
        html += '<div style="min-width:0;">';
        html += '<strong style="font-size:13px;color:#1f2937;">因子信息</strong>';
        html += '<span style="margin-left:8px;font-size:12px;color:#475467;font-family:monospace;">' + escapeHTML(factorEntry.alias || factorEntry.name || '') + '</span>';
        html += '</div>';
        html += '<button type="button" id="' + PANEL_ID + '-close" style="background:none;border:none;font-size:20px;cursor:pointer;color:#888;line-height:1;">&times;</button>';
        html += '</div>';

        html += '<div style="display:flex;gap:4px;padding:6px 10px 0;border-bottom:1px solid #e5e7eb;background:#fff;">';
        html += '<button type="button" class="factor-info-tab-btn" data-tab="' + TAB_FORMULA + '" style="border:none;background:none;padding:6px 10px;font-size:12px;cursor:pointer;border-bottom:2px solid ' + (_activeTab === TAB_FORMULA ? '#0078d4' : 'transparent') + ';color:' + (_activeTab === TAB_FORMULA ? '#0078d4' : '#64748b') + ';font-weight:' + (_activeTab === TAB_FORMULA ? '600' : '400') + ';">公式与参数</button>';
        html += '<button type="button" class="factor-info-tab-btn" data-tab="' + TAB_BACKEND + '" style="border:none;background:none;padding:6px 10px;font-size:12px;cursor:pointer;border-bottom:2px solid ' + (_activeTab === TAB_BACKEND ? '#0078d4' : 'transparent') + ';color:' + (_activeTab === TAB_BACKEND ? '#0078d4' : '#64748b') + ';font-weight:' + (_activeTab === TAB_BACKEND ? '600' : '400') + ';">后端信息</button>';
        html += '</div>';

        html += '<div style="flex:1;min-height:0;overflow-y:auto;padding:12px 14px;">';
        if (_activeTab === TAB_FORMULA) {
            html += '<div id="' + PANEL_ID + '-math" style="min-height:48px;"></div>';
            html += '<div style="margin-top:10px;font-size:12px;font-weight:700;color:#475467;">参数</div>';
            html += renderParamRows(factorEntry.param_defs);
        } else {
            html += window.OverlayFieldsTable
                ? window.OverlayFieldsTable.renderHtml(factorEntry.backend_fields)
                : '<div style="color:#888;font-size:12px;">字段渲染组件未加载</div>';
        }
        html += '</div>';

        panel.innerHTML = html;

        var closeBtn = document.getElementById(PANEL_ID + '-close');
        if (closeBtn) closeBtn.addEventListener('click', closeFactorInfoOverlay);

        panel.querySelectorAll('.factor-info-tab-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                _activeTab = btn.getAttribute('data-tab');
                renderTabs(factorEntry);
            });
        });

        if (_activeTab === TAB_FORMULA) {
            var mathEl = document.getElementById(PANEL_ID + '-math');
            if (mathEl && window.renderDrawerMathAndDesc) {
                window.renderDrawerMathAndDesc(factorEntry.latex || '', '', mathEl, null, null);
            } else if (mathEl) {
                mathEl.textContent = factorEntry.latex || '无公式';
            }
        }
    }

    /** @param {{alias:string,name:string,latex:?string,backend_fields:object,param_defs:object}} factorEntry */
    function openFactorInfoOverlay(factorEntry) {
        if (!factorEntry) return;
        ensureOverlay();
        _activeTab = TAB_FORMULA;
        renderTabs(factorEntry);
        document.getElementById(OVERLAY_ID).style.display = 'flex';
    }

    function closeFactorInfoOverlay() {
        var overlay = document.getElementById(OVERLAY_ID);
        if (overlay) overlay.style.display = 'none';
    }

    window.FactorInfoOverlay = {
        open: openFactorInfoOverlay,
        close: closeFactorInfoOverlay,
    };
})();
