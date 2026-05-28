/**
 * GroupTest.fee
 *
 * Goal: encapsulate fee drawer + fee table edit state so that:
 * - state can be snapshotted/restored (for param snapshots)
 * - UI wiring is centralized
 * - legacy globals can be shimmed during migration
 *
 * NOTE: This module is designed to be loaded after GroupTest bootstrap.
 * If GroupTest is missing, it safely no-ops.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) return;

    // ---- internal state ----
    var _useCloseToday = false;
    var _feeTableData = [];
    var _feeModifications = {}; // { variety_code: { open_ratio, close_ratio, closetoday_ratio } }

    function deepClone(obj) {
        return JSON.parse(JSON.stringify(obj || {}));
    }

    function getModifications() {
        return deepClone(_feeModifications);
    }

    function applyModifications(mods) {
        _feeModifications = {};
        if (mods && typeof mods === 'object') {
            Object.keys(mods).forEach(function(code) { _feeModifications[code] = mods[code]; });
        }
        if (_feeTableData.length) renderFeeTable();
    }

    function setUseCloseToday(flag) {
        _useCloseToday = !!flag;
        updateClosetodayUI();
        if (_feeTableData.length) renderFeeTable();
    }

    function toggleUseCloseToday() {
        setUseCloseToday(!_useCloseToday);
    }

    function _getEffectiveRow(row) {
        var code = (row.variety_code || '').toLowerCase();
        var mod = _feeModifications[code] || {};
        var closeField = _useCloseToday ? 'closetoday_ratio' : 'close_ratio';
        var openR = (mod.open_ratio !== undefined) ? mod.open_ratio : (parseFloat(row.open_ratio) || 0);
        var closeR = (mod[closeField] !== undefined)
            ? mod[closeField]
            : (_useCloseToday ? (parseFloat(row.closetoday_ratio) || 0) : (parseFloat(row.close_ratio) || 0));
        return { code: code, openR: openR, closeR: closeR };
    }

    // ---- UI helpers (minimal for now; full migration will move legacy functions here) ----
    function openDrawer() {
        var overlay = document.getElementById('group-fee-drawer');
        var badge = document.getElementById('user-badge');
        if (overlay) overlay.classList.add('open');
        if (badge) badge.style.display = 'none';
    }

    function closeDrawer() {
        var overlay = document.getElementById('group-fee-drawer');
        var badge = document.getElementById('user-badge');
        if (overlay) overlay.classList.remove('open');
        if (badge) badge.style.display = '';
    }

    function updateClosetodayUI() {
        var stateText = document.getElementById('closetoday_state_text');
        if (stateText) stateText.textContent = _useCloseToday ? '平今仓' : '平昨仓';
        var btn = document.getElementById('use_closetoday_btn');
        if (btn) btn.textContent = _useCloseToday ? '切换为平昨仓' : '切换为平今仓';
    }

    function renderFeeTable() {
        // Placeholder: legacy module still renders the table today.
        // We keep this hook for the migration step.
        // If the legacy renderer is present, call it to avoid functionality loss.
        if (typeof window.renderFeeTable === 'function') {
            try { window.renderFeeTable(); } catch (_) {}
        }
    }

    // Fetch fee table (kept generic; legacy endpoint)
    function fetchFeeTable(forceRefresh) {
        return fetch('/get_fee_table', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force_refresh: !!forceRefresh }),
        })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data || !data.success) throw new Error((data && data.error) || '获取失败');
                _feeTableData = data.rows || [];
                renderFeeTable();
                updateClosetodayUI();
                return data;
            });
    }

    // ---- public surface ----
    GT.fee = {
        getModifications: getModifications,
        applyModifications: applyModifications,
        setUseCloseToday: setUseCloseToday,
        toggleUseCloseToday: toggleUseCloseToday,
        fetchFeeTable: fetchFeeTable,
        openDrawer: openDrawer,
        closeDrawer: closeDrawer,
    };

    // ---- legacy global shims (will be removed once legacy module is removed) ----
    window._getFeeModifications = window._getFeeModifications || getModifications;
    window._applyFeeModifications = window._applyFeeModifications || applyModifications;
})();
