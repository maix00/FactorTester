(function() {
    var formatterCache = {};

    function normalizeCurrency(currency) {
        var text = String(currency || '').trim().toUpperCase();
        return text || '';
    }

    function finiteNumber(value) {
        if (value === null || value === undefined || value === '') return null;
        var num = Number(value);
        return isFinite(num) ? num : null;
    }

    function getDecimalFormatter(locale, decimals) {
        var key = 'decimal|' + locale + '|' + decimals;
        if (!formatterCache[key]) {
            formatterCache[key] = new Intl.NumberFormat(locale, {
                minimumFractionDigits: decimals,
                maximumFractionDigits: decimals,
            });
        }
        return formatterCache[key];
    }

    function getCurrencyFormatter(locale, currency, decimals) {
        var key = 'currency|' + locale + '|' + currency + '|' + decimals;
        if (!formatterCache[key]) {
            formatterCache[key] = new Intl.NumberFormat(locale, {
                style: 'currency',
                currency: currency,
                currencyDisplay: 'code',
                minimumFractionDigits: decimals,
                maximumFractionDigits: decimals,
            });
        }
        return formatterCache[key];
    }

    function formatMajor(value, options) {
        options = options || {};
        var num = finiteNumber(value);
        if (num === null) return options.empty || '';
        var decimals = options.decimals === undefined ? 2 : Math.max(0, Number(options.decimals) || 0);
        var locale = options.locale || 'zh-CN';
        var currency = normalizeCurrency(options.currency);
        var formatted;
        if (currency && typeof Intl !== 'undefined' && Intl.NumberFormat) {
            try {
                formatted = getCurrencyFormatter(locale, currency, decimals).format(num);
            } catch (err) {
                formatted = getDecimalFormatter(locale, decimals).format(num) + ' ' + currency;
            }
        } else if (typeof Intl !== 'undefined' && Intl.NumberFormat) {
            formatted = getDecimalFormatter(locale, decimals).format(num);
        } else {
            formatted = num.toFixed(decimals) + (currency ? ' ' + currency : '');
        }
        return formatted;
    }

    function formatSignedMajor(value, options) {
        options = options || {};
        var num = finiteNumber(value);
        if (num === null) return options.empty || '';
        if (Math.abs(num) <= 1e-12) return formatMajor(0, options);
        var absFormatted = formatMajor(Math.abs(num), options);
        return (num > 0 ? '+' : '-') + absFormatted;
    }

    window.MoneyDisplay = {
        normalizeCurrency: normalizeCurrency,
        formatMajor: formatMajor,
        formatSignedMajor: formatSignedMajor,
    };
})();
