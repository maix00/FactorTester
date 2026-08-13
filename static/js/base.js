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
