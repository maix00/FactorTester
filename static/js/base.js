/**
 * static/js/base.js
 * 全局共享的工具函数和页面初始化逻辑。
 *
 * 函数列表：
 *   searchFactors()         — 因子搜索（回车触发），携带 include_subordinates 参数
 *   shutdownServer()        — 管理员关闭服务器（POST /shutdown）
 *   pad(n)                  — 数字补零到两位
 *   formatNumber(v, [dec])  — 数值格式化：null→—, 整数不显示小数, 否则默认6位
 */

/** 因子搜索：收集搜索框输入，拼 URL 参数后跳转 */
function searchFactors() {
    var query = document.getElementById('search').value;
    var includeSubordinates = document.getElementById('include-subordinates')?.checked;
    var params = new URLSearchParams();
    if (query.trim()) {
        params.set('search', query);
    }
    if (includeSubordinates) params.set('include_subordinates', '1');
    window.location.href = '?' + params.toString();
}

function shutdownServer() {
    if (confirm('确定要关闭服务器吗？')) {
        fetch('/shutdown', {method: 'POST'}).then(function() {
            window.close();
        }).catch(function() {
            window.location.href = '/shutdown';
        });
    }
}

function pad(n) {
    n = parseInt(n);
    return n < 10 ? '0' + n : n.toString();
}

function formatNumber(value, decimals) {
    if (value === null || value === undefined || value === '') return '—';
    if (typeof value === 'number') {
        return decimals !== undefined ? value.toFixed(decimals) : (Number.isInteger(value) ? value : value.toFixed(6));
    }
    return String(value);
}

/*
 * The legacy home page cannot load the Manager Web bundle, but it still
 * consumes the same module manifest.  Keep the adapter semantic: sfSymbol is
 * the identity, while this small inline SVG set is only the browser renderer.
 * Unknown symbols deliberately render the link shape instead of raw text or
 * a missing image, and retain data-symbol for diagnostics and tests.
 */
(function () {
    var moduleSymbols = {
        'ic-test': 'chart.xyaxis.line',
        jobs: 'list.bullet.rectangle',
        backtest: 'chart.line.uptrend.xyaxis.circle',
        products: 'chart.line.uptrend.xyaxis',
        sqlite_web: 'cylinder.split.1x2',
        custom_factors: 'atom',
        admin_users: 'building.columns',
        server_operations: 'server.rack',
        docs: 'book'
    };

    var legacySymbols = {
        IC: 'chart.xyaxis.line',
        任务: 'list.bullet.rectangle',
        BT: 'chart.line.uptrend.xyaxis.circle',
        SQL: 'cylinder.split.1x2',
        OPS: 'server.rack',
        server: 'server.rack',
        book: 'book'
    };

    var shapes = {
        'chart.xyaxis.line': '<path d="M4 20V4M4 20h17"/><path d="m7 15 3-4 3 2 5-7 3 2"/>',
        'list.bullet.rectangle': '<rect x="6" y="4" width="14" height="16" rx="2"/><path d="M10 9h6M10 13h6M10 17h4M3.5 9h.1M3.5 13h.1M3.5 17h.1"/>',
        'chart.line.uptrend.xyaxis.circle': '<circle cx="15.5" cy="8.5" r="5.5"/><path d="M4 20V5M4 20h17M7 16l3-4 3 2"/><path d="m13 8 2 2 3-4 2 1"/>',
        'chart.line.uptrend.xyaxis': '<path d="M4 20V4M4 20h17"/><path d="m7 16 4-5 3 2 6-8"/><path d="M17 5h3v3"/>',
        'cylinder.split.1x2': '<ellipse cx="12" cy="5" rx="7.5" ry="2.5"/><path d="M4.5 5v9c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5V5M12 8v8.5M12 8c0 1.2-1.7 2.1-3.8 2.1S4.5 9.2 4.5 8"/>',
        atom: '<circle cx="12" cy="12" r="2"/><ellipse cx="12" cy="12" rx="9" ry="4" transform="rotate(30 12 12)"/><ellipse cx="12" cy="12" rx="9" ry="4" transform="rotate(-30 12 12)"/>',
        'building.columns': '<path d="M4 20h16M5 20V9h14v11M3 9l9-5 9 5M8 12v8M12 12v8M16 12v8"/>',
        'server.rack': '<rect x="4" y="4" width="16" height="5" rx="1"/><rect x="4" y="10" width="16" height="5" rx="1"/><rect x="4" y="16" width="16" height="4" rx="1"/><path d="M7 6.5h.1M7 12.5h.1M7 18h.1M10 6.5h7M10 12.5h7M10 18h7"/>',
        book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5Z"/><path d="M4 5.5v16M8 7h8M8 11h8"/>',
        link: '<path d="M9.5 14.5 8 16a3.5 3.5 0 0 1-5-5l2-2a3.5 3.5 0 0 1 5 0M14.5 9.5 16 8a3.5 3.5 0 0 1 5 5l-2 2a3.5 3.5 0 0 1-5 0M8 12h8"/>'
    };

    function escapeAttribute(value) {
        return String(value || '').replace(/[&<>"']/g, function (character) {
            return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character];
        });
    }

    function moduleSymbol(value) {
        if (value && typeof value === 'object') {
            var semantic = String(value.sfSymbol || '').trim();
            if (semantic) return semantic;
            var id = String(value.id || '').replace(/-/g, '_');
            return moduleSymbols[id] || moduleSymbol(value.icon);
        }
        var raw = String(value || '').trim();
        return moduleSymbols[raw] || legacySymbols[raw] || 'link';
    }

    function moduleIcon(value) {
        var symbol = moduleSymbol(value);
        var shape = shapes[symbol] || shapes.link;
        var fallback = shapes[symbol] ? '' : ' data-fallback="true"';
        return '<span class="ft-icon legacy-module-icon" data-symbol="'
            + escapeAttribute(symbol) + '"' + fallback + ' aria-hidden="true">'
            + '<svg class="ft-icon-svg" viewBox="0 0 24 24" focusable="false" aria-hidden="true">'
            + '<g fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
            + shape + '</g></svg></span>';
    }

    window.FTModuleIcons = Object.freeze({moduleSymbol: moduleSymbol, moduleIcon: moduleIcon});
}());

document.addEventListener('DOMContentLoaded', function() {
    var searchInput = document.getElementById('search');
    if (searchInput) {
        searchInput.addEventListener('keyup', function(e) {
            if (e.key === 'Enter') searchFactors();
        });
    }
    var includeSubordinates = document.getElementById('include-subordinates');
    if (includeSubordinates) {
        includeSubordinates.addEventListener('change', searchFactors);
    }
});
