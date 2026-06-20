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

    function getCurrencyInput() {
        return document.getElementById('group_base_currency');
    }

    function getConversionFeeInput() {
        return document.getElementById('group_currency_conversion_fee_rate');
    }

    function normalize(value) {
        var num = Number(value);
        if (!isFinite(num) || num <= 0) return null;
        return num;
    }

    function normalizeCurrency(value) {
        var text = String(value || 'CNY').trim().toUpperCase();
        return text || 'CNY';
    }

    function normalizeRate(value) {
        var num = Number(value);
        if (!isFinite(num) || num < 0) return null;
        return num;
    }

    function ensureExtraControls() {
        // Controls are now defined in HTML template — verify they exist.
        getInput();
        getCurrencyInput();
        getConversionFeeInput();
    }

    function collect() {
        ensureExtraControls();
        var input = getInput();
        var currencyInput = getCurrencyInput();
        var conversionFeeInput = getConversionFeeInput();
        return {
            initialCapital: normalize(input && input.value),
            baseCurrency: normalizeCurrency(currencyInput && currencyInput.value),
            currencyConversionFeeRate: normalizeRate(conversionFeeInput && conversionFeeInput.value)
        };
    }

    function apply(data) {
        ensureExtraControls();
        var input = getInput();
        if (!input) return;
        var value = normalize(data && data.initialCapital);
        if (value !== null) input.value = String(value);
        var currencyInput = getCurrencyInput();
        if (currencyInput) currencyInput.value = normalizeCurrency(data && data.baseCurrency);
        var conversionFeeInput = getConversionFeeInput();
        var feeRate = normalizeRate(data && data.currencyConversionFeeRate);
        if (conversionFeeInput && feeRate !== null) conversionFeeInput.value = String(feeRate);
    }

    function summarize(data) {
        var value = normalize(data && data.initialCapital);
        if (value === null) return null;
        return '初始金额: ' + String(value) + ' ' + normalizeCurrency(data && data.baseCurrency);
    }

    function validateRunPayload(fields) {
        var value = normalize(fields.initialCapital);
        if (value === null) return ['请设置有效的初始金额'];
        if (!normalizeCurrency(fields.baseCurrency)) return ['请设置基础货币'];
        if (normalizeRate(fields.currencyConversionFeeRate) === null) return ['请设置有效的换汇佣金率'];
        return [];
    }

    function getStructureKeyParts(fields) {
        return [
            String(normalize(fields.initialCapital) || ''),
            normalizeCurrency(fields.baseCurrency),
            String(normalizeRate(fields.currencyConversionFeeRate) || 0)
        ];
    }

    GT.localSettings.register({
        key: 'initialCapital',
        order: 20,
        tabLabel: '初始金额',
        collect: collect,
        apply: apply,
        bind: ensureExtraControls,
        runFields: ['initialCapital', 'baseCurrency', 'currencyConversionFeeRate'],
        runPayload: [
            { field: 'initialCapital', key: 'initial_capital' },
            { field: 'baseCurrency', key: 'base_currency' },
            { field: 'currencyConversionFeeRate', key: 'currency_conversion_fee_rate' },
        ],
        validateRunPayload: validateRunPayload,
        getStructureKeyParts: getStructureKeyParts,
        summarize: summarize,
    });
})();
