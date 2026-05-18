/**
 * GroupTest bootstrap
 *
 * This file must be loaded BEFORE any other group_test/*.js files.
 * It creates a single global namespace: window.GroupTest.
 */
(function() {
    if (window.GroupTest) return;

    /** @type {any} */
    var GT = {
        version: '0.1.0',
        // submodules filled by later scripts
        api: null,
        state: null,
        fee: null,
        charts: null,
        metrics: null,
        overlays: null,
        ui: null,

        /** lightweight logger for dev */
        log: function() {
            try { console.log.apply(console, ['[GroupTest]'].concat([].slice.call(arguments))); }
            catch (_) {}
        },
    };

    window.GroupTest = GT;
})();

