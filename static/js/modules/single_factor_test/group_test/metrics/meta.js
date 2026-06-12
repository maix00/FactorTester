/**
 * Metric metadata for GroupTest — single-source from backend.
 *
 * Defaults are empty; real data comes from backend metrics_meta
 * injected by results/renderer.js on group test completion.
 *
 * Used by:
 * - sectioned metrics table (CN display names)
 * - hover popup (description + MathJax formula)
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) return;

    GT.metrics = GT.metrics || {};
    if (GT.metrics.meta) return; // already injected by backend

    GT.metrics.meta = { cn: {}, desc: {}, math: {} };
})();
