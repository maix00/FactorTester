/**
 * GroupTest entrypoint augmentation for metrics rendering.
 *
 * This file is expected to be merged with the skeleton issue (#47).
 * It is additive: if other entrypoints exist, we do not override them.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) return; // safe under any load order

    function renderSectionedMetricsTable(metricsByGroup) {
        if (!GT.metrics || !GT.metrics.table || !GT.metrics.table.render) return;
        var out = GT.metrics.table.render(metricsByGroup || {});
        var head = document.getElementById('metrics_head');
        var body = document.getElementById('metrics_body');
        if (head) head.innerHTML = out.headHtml || '';
        if (body) body.innerHTML = out.bodyHtml || '';
    }

    GT.renderSectionedMetricsTable = GT.renderSectionedMetricsTable || renderSectionedMetricsTable;
})();

