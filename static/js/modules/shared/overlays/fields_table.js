/**
 * shared/overlays/fields_table.js — render a reflect_public_fields()-shaped
 * {key: {value, type}} dict as a simple two-column table.
 * Shared by the factor-info and product-path-selection info overlays' "后端信息" tab.
 */
(function() {
    function escapeHTML(str) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(str == null ? '' : String(str)));
        return div.innerHTML;
    }

    function formatValue(value) {
        if (value === null || value === undefined) return '<span style="color:#aaa;">null</span>';
        if (typeof value === 'object') {
            try { return escapeHTML(JSON.stringify(value)); } catch (e) { return escapeHTML(String(value)); }
        }
        return escapeHTML(String(value));
    }

    /** @param {Object<string,{value:*,type:string}>} fields */
    function renderHtml(fields) {
        var keys = Object.keys(fields || {});
        if (!keys.length) {
            return '<div style="padding:14px;text-align:center;color:#888;font-size:12px;">暂无后端字段信息</div>';
        }
        // "class" first, then alphabetical for stable, scannable order.
        keys.sort(function(a, b) {
            if (a === 'class') return -1;
            if (b === 'class') return 1;
            return a.localeCompare(b);
        });
        var html = '<table style="width:100%;border-collapse:collapse;font-size:12px;">';
        html += '<thead><tr style="background:#f0f4f8;position:sticky;top:0;">';
        html += '<th style="padding:6px 10px;text-align:left;">字段</th>';
        html += '<th style="padding:6px 10px;text-align:left;">值</th>';
        html += '<th style="padding:6px 10px;text-align:left;width:90px;">类型</th>';
        html += '</tr></thead><tbody>';
        keys.forEach(function(key) {
            var entry = fields[key] || {};
            var label = entry.label || key;
            var note = entry.note || entry.source_note || '';
            var source = entry.source || '';
            html += '<tr style="border-bottom:1px solid #eef2f7;">';
            html += '<td style="padding:5px 10px;color:#334155;">';
            html += '<div style="font-weight:600;">' + escapeHTML(label) + '</div>';
            if (label !== key) html += '<div style="font-family:monospace;color:#94a3b8;font-size:11px;">' + escapeHTML(key) + '</div>';
            if (source) html += '<div style="color:#64748b;font-size:11px;margin-top:1px;">' + escapeHTML(source) + '</div>';
            if (note) html += '<div style="color:#667085;font-size:11px;line-height:1.35;margin-top:2px;">' + escapeHTML(note) + '</div>';
            html += '</td>';
            html += '<td style="padding:5px 10px;color:#555;word-break:break-all;">' + formatValue(entry.value) + '</td>';
            html += '<td style="padding:5px 10px;color:#94a3b8;">' + escapeHTML(entry.type || '') + '</td>';
            html += '</tr>';
        });
        html += '</tbody></table>';
        return html;
    }

    window.OverlayFieldsTable = { renderHtml: renderHtml };
})();
