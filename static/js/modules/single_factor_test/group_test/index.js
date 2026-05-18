/**
 * GroupTest entrypoint.
 *
 * For now we still rely on legacy implementation in group_test_module.js.
 * This file provides a stable namespaced API (window.GroupTest.*) and
 * small additive helpers as we migrate piece-by-piece.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    // ---- Tabs / navigation hook (legacy bridge) ----
    function hasLegacyRenderTabs() {
        return typeof window.renderGroupTabs === 'function';
    }

    function renderTabs(submissions) {
        if (!hasLegacyRenderTabs()) {
            GT.log('legacy renderGroupTabs not available yet');
            return;
        }
        return window.renderGroupTabs(submissions);
    }

    // Do not override if another module already defined it.
    if (!GT.renderTabs) GT.renderTabs = renderTabs;

    // Compatibility: keep the old global for existing callers.
    // (Will be removed once all callers migrate to GroupTest and legacy is removed in #52.)
    if (!window.renderGroupTabs) window.renderGroupTabs = renderTabs;

    // ---- Metrics helpers (sectioned summary table) ----
    function renderSectionedMetricsTable(metricsByGroup) {
        if (!GT.metrics || !GT.metrics.table || !GT.metrics.table.render) return;
        var out = GT.metrics.table.render(metricsByGroup || {});
        var head = document.getElementById('metrics_head');
        var body = document.getElementById('metrics_body');
        if (head) head.innerHTML = out.headHtml || '';
        if (body) body.innerHTML = out.bodyHtml || '';
    }

    if (!GT.renderSectionedMetricsTable) GT.renderSectionedMetricsTable = renderSectionedMetricsTable;
})();
