/**
 * Intraday window state and interaction for group detail overlay.
 * Manages _groupIntradayRows / _groupIntradayWindows state arrays.
 * Depends on GT.metrics.detailOverlay.tables.*
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    var T = GT.metrics.detailOverlay.tables;
    if (!T) throw new Error('detailOverlay/tables.js must be loaded first');

    var _groupIntradayRows = [];
    var _groupIntradayWindows = [];

    function setRows(rows) {
        _groupIntradayRows = rows || [];
        _groupIntradayWindows = [];
    }

    function getRows() { return _groupIntradayRows; }
    function getWindows() { return _groupIntradayWindows; }

    function summarizeWindow(start, end) {
        var rows = (_groupIntradayRows || []).filter(function(row) {
            return row.time >= start && row.time <= end;
        });
        var total = (_groupIntradayRows || []).reduce(function(sum, row) { return sum + (row.sum || 0); }, 0);
        var contribution = rows.reduce(function(sum, row) { return sum + (row.sum || 0); }, 0);
        var count = rows.reduce(function(sum, row) { return sum + (row.count || 0); }, 0);
        return {
            label: start + '-' + end,
            count: count,
            sum: contribution,
            share_of_total_sum: total !== 0 ? contribution / total : null,
        };
    }

    function renderSelectedWindows() {
        var target = document.getElementById('group-detail-intraday-windows');
        if (target) target.innerHTML = T.renderIntradayWindows(_groupIntradayWindows);
    }

    function addWindow() {
        var startEl = document.getElementById('group-intraday-window-start');
        var endEl = document.getElementById('group-intraday-window-end');
        if (!startEl || !endEl || !startEl.value || !endEl.value || startEl.value > endEl.value) return;
        _groupIntradayWindows.push(summarizeWindow(startEl.value, endEl.value));
        renderSelectedWindows();
    }

    GT.metrics.detailOverlay.intraday = {
        setRows: setRows,
        getRows: getRows,
        getWindows: getWindows,
        summarizeWindow: summarizeWindow,
        renderSelectedWindows: renderSelectedWindows,
        addWindow: addWindow,
    };
})();
