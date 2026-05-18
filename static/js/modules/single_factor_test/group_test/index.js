/**
 * GroupTest entrypoint.
 *
 * For now this is a thin wrapper that delegates to legacy
 * window.renderGroupTabs (defined in legacy group_test_module.js).
 *
 * Issue #52 will remove the legacy file; this index will then become
 * the true implementation entrypoint.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    function hasLegacy() {
        return typeof window.renderGroupTabs === 'function';
    }

    /**
     * Entry called by other modules (IC test/category filter) via global hook today.
     * We keep a compatibility bridge but prefer callers to use GroupTest.renderTabs.
     */
    function renderTabs(submissions) {
        if (!hasLegacy()) {
            GT.log('legacy renderGroupTabs not available yet');
            return;
        }
        return window.renderGroupTabs(submissions);
    }

    // Public API (single global surface)
    GT.renderTabs = renderTabs;

    // Compatibility: keep the old global for existing callers.
    // (Will be removed once all callers migrate to GroupTest.)
    window.renderGroupTabs = window.renderGroupTabs || renderTabs;
})();

