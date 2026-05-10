(function() {
    function hasValues(values) {
        return Array.isArray(values) && values.some(function(v) {
            return v !== null && v !== undefined && !Number.isNaN(Number(v));
        });
    }

    function normalizePriceApi(apiData) {
        if (!apiData || !apiData.success || !Array.isArray(apiData.data) || apiData.data.length === 0) {
            return { error: (apiData && apiData.error) || '无价格数据' };
        }
        const rows = apiData.data.slice().sort(function(a, b) {
            return (a.timestamp || 0) - (b.timestamp || 0);
        });
        const series = {
            product: apiData.product || '',
            desc: apiData.desc || '',
            adjusted: !!apiData.adjusted,
            supports_adjusted: !!apiData.supports_adjusted,
            has_term_structure: !!apiData.is_futures || !!apiData.has_term_structure,
            dates: rows.map(d => d.timestamp),
            OPEN: rows.map(d => d.open),
            HIGH: rows.map(d => d.high),
            LOW: rows.map(d => d.low),
            CLOSE: rows.map(d => d.close),
            VOLUME: rows.map(d => d.volume == null ? null : d.volume),
            OPEN_INTEREST: rows.map(d => d.open_interest == null ? null : d.open_interest),
            raw: rows,
        };
        series.has_volume = hasValues(series.VOLUME);
        series.has_open_interest = !!apiData.has_oi && hasValues(series.OPEN_INTEREST);
        return series;
    }

    function setCheckboxVisibility(inputId, wrapId, available, defaultChecked) {
        const input = document.getElementById(inputId);
        const wrap = document.getElementById(wrapId);
        if (wrap) wrap.style.display = available ? 'inline-block' : 'none';
        if (input) {
            input.disabled = !available;
            if (!available) input.checked = false;
            else if (defaultChecked !== undefined) input.checked = !!defaultChecked;
        }
    }

    function toOhlc(rows) {
        return (rows || [])
            .filter(d => d && d.timestamp != null && d.open != null && d.high != null && d.low != null && d.close != null)
            .map(d => [d.timestamp, d.open, d.high, d.low, d.close]);
    }

    function toColumn(rows, field) {
        return (rows || [])
            .filter(d => d && d.timestamp != null && d[field] != null)
            .map(d => [d.timestamp, d[field]]);
    }

    function contractOverlayFromApi(apiData) {
        if (!apiData || !apiData.success || !Array.isArray(apiData.data)) return null;
        const rows = apiData.data.slice().sort(function(a, b) {
            return (a.timestamp || 0) - (b.timestamp || 0);
        });
        const ohlc = toOhlc(rows);
        if (!ohlc.length) return null;
        return {
            name: apiData.contract_name || apiData.product || apiData.contract_uid || '合约',
            data: ohlc,
            volume: toColumn(rows, 'volume'),
            open_interest: toColumn(rows, 'open_interest'),
            has_volume: rows.some(d => d && d.volume != null),
            has_open_interest: !!apiData.has_oi && rows.some(d => d && d.open_interest != null),
        };
    }

    window.PriceDisplay = {
        hasValues,
        normalizePriceApi,
        setCheckboxVisibility,
        toOhlc,
        toColumn,
        contractOverlayFromApi,
    };
})();
