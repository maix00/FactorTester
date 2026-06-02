/**
 * Pure formatting helpers for group detail overlay.
 * No DOM access, no module deps beyond GT.escapeHTML.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    function fmtPct(value) {
        return value == null ? '—' : (value * 100).toFixed(3) + '%';
    }

    function fmtBp(value) {
        return value == null ? '—' : (value * 10000).toFixed(5) + ' bp';
    }

    function fmtFeeRate(value) {
        if (value == null || isNaN(value) || !isFinite(value)) return '—';
        var bp = value * 10000;
        return bp.toFixed(5) + ' bp';
    }

    /** Check if a row's product.fee._is_real_fee flag is set. */
    function isRealFee(row) {
        return !!(row && row.product && row.product.fee && row.product.fee._is_real_fee);
    }

    function escapeHtml(value) {
        return GT.escapeHTML(value);
    }

    function formatGroupProduct(product) {
        if (!product) return '—';
        if (typeof product === 'string') return product;
        var name = product.name || '';
        var desc = product.desc && product.desc !== name ? ' · ' + product.desc : '';
        return name + desc;
    }

    function formatGroupProducts(products) {
        return (products || []).map(formatGroupProduct).join('、');
    }

    function formatAdaptiveTime(timestamp, stepMs) {
        return GT.utils.dates.formatAdaptiveTime(timestamp, stepMs);
    }

    function formatCompactTime(timestamp) {
        return formatAdaptiveTime(timestamp, null);
    }

    GT.metrics = GT.metrics || {};
    GT.metrics.detailOverlay = GT.metrics.detailOverlay || {};
    GT.metrics.detailOverlay.format = {
        fmtPct: fmtPct,
        fmtBp: fmtBp,
        fmtFeeRate: fmtFeeRate,
        isRealFee: isRealFee,
        escapeHtml: escapeHtml,
        formatGroupProduct: formatGroupProduct,
        formatGroupProducts: formatGroupProducts,
        formatAdaptiveTime: formatAdaptiveTime,
        formatCompactTime: formatCompactTime,
    };
})();
