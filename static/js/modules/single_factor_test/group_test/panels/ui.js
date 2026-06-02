/**
 * panels/ui.js — 分组测试 UI 工具函数
 *
 * 从 app.js 解耦提取。
 * 提供纯 UI 渲染工具：HTML 转义、费率格式化、产品格式化等。
 * 挂载到 GT.panels.ui 命名空间。
 */
(function(){
    var GT = window.GroupTest;
    if (!GT) { console.warn('[GT panels/ui] bootstrap missing'); return; }
    GT.panels = GT.panels || {};
    if (GT.panels.ui) { console.warn('[GT panels/ui] already loaded'); return; }

    var ui = {};

    /**
     * HTML 转义字符串
     */
    ui.escapeHtml = function(value) {
        return GT.escapeHTML(value);
    };

    /**
     * CSS 转义（用于选择器）
     */
    ui.cssEscape = function(value) {
        if (window.CSS && typeof window.CSS.escape === 'function') return window.CSS.escape(value);
        return String(value).replace(/["\\]/g, '\\$&');
    };

    /**
     * 安全 HTML 转义（用于属性插值）
     */
    ui.escAttr = function(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    };

    /**
     * 格式化费率值为 bp 字符串
     * @param {number|null|undefined} value — 费率值（小数，如 0.0025）
     * @returns {string} 如 "25.00000 bp" 或 "—"
     */
    ui.fmtFeeRate = function(value) {
        if (value == null || isNaN(value) || !isFinite(value)) return '—';
        var bp = value * 10000;
        return bp.toFixed(5) + ' bp';
    };

    /**
     * 格式化单个产品显示
     * @param {string|object} product — 产品名或 {name, desc}
     * @returns {string} — 如 "RB · 螺纹钢"
     */
    ui.formatGroupProduct = function(product) {
        if (!product) return '—';
        if (typeof product === 'string') return product;
        var name = product.name || '';
        var desc = product.desc && product.desc !== name ? ' · ' + product.desc : '';
        return name + desc;
    };

    /**
     * 格式化多个产品（用顿号连接）
     */
    ui.formatGroupProducts = function(products) {
        return (products || []).map(ui.formatGroupProduct).join('、');
    };

    /**
     * 判断费率行是否为真实费率
     */
    ui.isRealFee = function(row) {
        return !!(row && row.product && row.product.fee && row.product.fee._is_real_fee);
    };

    /**
     * 格式化时间戳
     */
    ui.fmtTs = function(ts) {
        var d = new Date(ts);
        return d.getFullYear() + '-' +
            String(d.getMonth() + 1).padStart(2, '0') + '-' +
            String(d.getDate()).padStart(2, '0') + ' ' +
            String(d.getHours()).padStart(2, '0') + ':' +
            String(d.getMinutes()).padStart(2, '0') + ':' +
            String(d.getSeconds()).padStart(2, '0');
    };

    GT.panels.ui = ui;
})();
