/**
 * core/local-settings/initial-capital.js — registers GroupTest initial capital.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT || !GT.localSettings) {
        console.warn('[GT local-settings/initial-capital] dependencies missing');
        return;
    }

    function getInput() {
        return document.getElementById('group_initial_capital');
    }

    function normalize(value) {
        var num = Number(value);
        if (!isFinite(num) || num <= 0) return null;
        return num;
    }

    function collect() {
        var input = getInput();
        return { initialCapital: normalize(input && input.value) };
    }

    function apply(data) {
        var input = getInput();
        if (!input) return;
        var value = normalize(data && data.initialCapital);
        if (value !== null) input.value = String(value);
    }

    function summarize(data) {
        var value = normalize(data && data.initialCapital);
        if (value === null) return null;
        return '初始金额: ' + String(value);
    }

    function validateRunPayload(fields) {
        var value = normalize(fields.initialCapital);
        if (value === null) return ['请设置有效的初始金额'];
        return [];
    }

    function getStructureKeyParts(fields) {
        return [String(normalize(fields.initialCapital) || '')];
    }

    GT.localSettings.register({
        key: 'initialCapital',
        order: 20,
        tabLabel: '初始金额',
        collect: collect,
        apply: apply,
        runFields: ['initialCapital'],
        runPayload: [
            { field: 'initialCapital', key: 'initial_capital' },
        ],
        validateRunPayload: validateRunPayload,
        getStructureKeyParts: getStructureKeyParts,
        summarize: summarize,
    });
})();
