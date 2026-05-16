(function() {
    if (window.SingleFactorSubmissionContext) return;

    function getSubmissionIdFromTab(tab, panelPrefix) {
        if (!tab) return null;
        var explicitId = tab.getAttribute('data-submission-id');
        if (explicitId) return explicitId;

        var panelId = tab.getAttribute('data-bs-target') || '';
        var prefix = '#' + panelPrefix + '-';
        if (panelId.indexOf(prefix) === 0) {
            return panelId.slice(prefix.length);
        }
        return null;
    }

    function findSubmissionById(submissionId) {
        var list = Array.isArray(window.submissions) ? window.submissions : [];
        return list.find(function(sub) {
            return String(sub.id) === String(submissionId);
        }) || null;
    }

    function findFactorByLabel(label) {
        var factors = Array.isArray(window.factorList) ? window.factorList : [];
        return factors.find(function(f) {
            return f.name === label || f.alias === label;
        }) || null;
    }

    function getActiveFactorContext(options) {
        options = options || {};
        var tab = document.querySelector(options.tabSelector || '');
        if (!tab) return null;

        var submissionId = getSubmissionIdFromTab(tab, options.panelPrefix || '');
        var panelSelector = tab.getAttribute('data-bs-target') || '';
        if (!submissionId || !panelSelector) return null;

        var panel = document.querySelector(panelSelector);
        if (!panel) return null;

        var factorTab = panel.querySelector(options.factorTabSelector || '.factor-tabs-container .nav-link.active');
        if (!factorTab) return null;

        var factorLabel = factorTab.getAttribute('data-factor-alias') || factorTab.textContent.trim();
        var factor = findFactorByLabel(factorLabel);
        if (!factor) return null;

        return {
            submission_id: submissionId,
            submission: findSubmissionById(submissionId),
            factor_alias: factor.alias,
            factor: factor,
        };
    }

    window.SingleFactorSubmissionContext = {
        getSubmissionIdFromTab: getSubmissionIdFromTab,
        findSubmissionById: findSubmissionById,
        getActiveFactorContext: getActiveFactorContext,
    };
})();
