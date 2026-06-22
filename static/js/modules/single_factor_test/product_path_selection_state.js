/**
 * Product-path selection state for IC/group test configuration.
 *
 * The page no longer owns a product-category overlay.  Test modules keep their
 * own settings UI and can still share this transition state while they migrate
 * from earlier page-level product selection naming.
 */
(function() {
    if (window.ProductPathSelectionState) return;

    var selections = Array.isArray(window.productPathSelections)
        ? window.productPathSelections
        : (Array.isArray(window.submissions) ? window.submissions : []);
    window.productPathSelections = selections;
    window.getProductPathSelections = function() { return selections; };

    function cloneList(list) {
        return Array.isArray(list) ? list.slice() : [];
    }

    function notify() {
        var snapshot = cloneList(selections);
        var bus = window.SingleFactorSubmissionBus;
        if (bus && typeof bus.emit === 'function') {
            bus.emit(bus.EVENTS.SYNCED, { submissions: snapshot });
        }
        if (typeof window.renderICTabs === 'function') {
            Promise.resolve(window.renderICTabs(snapshot)).catch(function(e) {
                console.error('刷新 IC 标签失败:', e);
            });
        }
        if (typeof window.renderGroupTabs === 'function') {
            try { window.renderGroupTabs(snapshot); } catch (e) { console.error('刷新分组标签失败:', e); }
        }
    }

    function apply(newSelections, options) {
        selections = cloneList(newSelections);
        window.productPathSelections = selections;
        window.submissions = selections;
        window.submissionRecords = selections;
        if (!options || options.notify !== false) notify();
        return selections;
    }

    window.ProductPathSelectionState = {
        getAll: function() { return cloneList(selections); },
        apply: apply,
    };
    window._getCurrentProductPathSelections = function() { return cloneList(selections); };
    window._applyProductPathSelections = function(newSelections) { return apply(newSelections); };
    window._getCurrentSubmissions = function() { return cloneList(selections); };
    window._applySubmissions = function(newSelections) { return apply(newSelections); };
})();
