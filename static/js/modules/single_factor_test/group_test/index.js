/**
 * GroupTest entrypoint.
 *
 * This file provides a stable namespaced API (window.GroupTest.*).
 * The actual UI implementation currently lives in group_test/app.js and
 * is attached to GT.ui.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    // ---- Tabs / navigation hook ----
    function renderTabs(submissions) {
        if (GT.ui && typeof GT.ui.renderTabs === 'function') return GT.ui.renderTabs(submissions);
        GT.log('GroupTest.ui.renderTabs not ready yet');
    }

    // Do not override if another module already defined it.
    if (!GT.renderTabs) GT.renderTabs = renderTabs;

    // Compatibility: other modules still call window.renderGroupTabs(...)
    // Keep it as a stable facade pointing at GroupTest.renderTabs.
    if (!window.renderGroupTabs) {
        window.renderGroupTabs = function(submissions) { return GT.renderTabs(submissions); };
    }

    // ---- Metrics helpers (sectioned summary table) ----
    function renderSectionedMetricsTable(metricsByGroup, groups) {
        if (!GT.metrics || !GT.metrics.table || !GT.metrics.table.build) return;
        var out = GT.metrics.table.build(metricsByGroup || {}, groups || []);
        var head = document.getElementById('metrics_head');
        var body = document.getElementById('metrics_body');
        if (head) head.innerHTML = out.headHtml || '';
        if (body) body.innerHTML = out.bodyHtml || '';
    }

    if (!GT.renderSectionedMetricsTable) GT.renderSectionedMetricsTable = renderSectionedMetricsTable;
})();
