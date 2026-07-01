(function() {
    function pageRuntimeTimeRangeValues() {
        if (typeof window.getSharedRuntimeTimeRange !== 'function') return null;
        var source = window.getSharedRuntimeTimeRange();
        if (!source) return null;
        var tradingDay = !!source.is_trading_day;
        return {
            start_date: source.start_date || '',
            end_date: source.end_date || '',
            start_time: tradingDay ? '' : (source.start_time || ''),
            end_time: tradingDay ? '' : (source.end_time || ''),
            timezone: tradingDay ? '' : (source.timezone || ''),
            time_precision: tradingDay ? 'trading_day' : 'exact',
        };
    }

    function payloadFromValues(values) {
        values = values || {};
        var precision = values.time_precision || 'exact';
        var tradingDay = precision === 'trading_day';
        return {
            start_date: values.start_date || '',
            end_date: values.end_date || '',
            start_time: tradingDay ? '' : (values.start_time || '00:00'),
            end_time: tradingDay ? '' : (values.end_time || '23:59'),
            time_precision: precision,
            timezone: tradingDay ? '' : (values.timezone || 'Asia/Shanghai'),
        };
    }

    function boundsMs(values) {
        var payload = payloadFromValues(values);
        if (!payload.start_date || !payload.end_date) return { start: null, end: null };
        var startText = payload.start_date + (
            payload.time_precision === 'trading_day'
                ? 'T00:00:00'
                : ('T' + (payload.start_time || '00:00'))
        );
        var endText = payload.end_date + (
            payload.time_precision === 'trading_day'
                ? 'T23:59:59.999'
                : ('T' + (payload.end_time || '23:59'))
        );
        var start = new Date(startText).getTime();
        var end = new Date(endText).getTime();
        return {
            start: Number.isFinite(start) ? start : null,
            end: Number.isFinite(end) ? end : null,
        };
    }

    window.BacktestTimeWindowSettings = {
        pageRuntimeTimeRangeValues: pageRuntimeTimeRangeValues,
        payloadFromValues: payloadFromValues,
        boundsMs: boundsMs,
    };
})();
