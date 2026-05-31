/**
 * GroupTest fee controls module
 *
 * Loaded after bootstrap.js, before app.js.
 * Exports: GT.fee.* — fee table, close-today, fee drawer, uniform/per-product modes.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    // ── State ────────────────────────────────────────────────────────────────
    var _useCloseToday = false;
    var _feeTableData = [];          // 原始费率数据（从后端获取的，不可变）
    var _feeModifications = {};      // 用户修改：{variety_code: {open_ratio, close_ratio, closetoday_ratio}}

    // ── Public API ───────────────────────────────────────────────────────────
    var api = {
        /** Whether close-today mode is active */
        useCloseToday: function() { return _useCloseToday; },
        /** Set close-today mode and fire refresh */
        setUseCloseToday: function(v) {
            _useCloseToday = !!v;
            updateClosetodayUI();
            if (_feeTableData.length) renderFeeTable();
        },

        /** Get fee modifications (for snapshot collection) */
        getModifications: function() { return JSON.parse(JSON.stringify(_feeModifications)); },

        /** Apply fee modifications (for snapshot restore) */
        applyModifications: function(mods) {
            _feeModifications = {};
            if (mods && typeof mods === 'object') {
                Object.keys(mods).forEach(function(code) {
                    _feeModifications[code] = mods[code];
                });
            }
            if (_feeTableData.length) renderFeeTable();
            updateFeeSummary();
        },

        /** Build fee_map from table data + modifications */
        buildFeeMap: function() {
            var map = {};
            _feeTableData.forEach(function(row) {
                var code = (row.variety_code || '').toLowerCase();
                if (!code) return;
                var mod = _feeModifications[code] || {};
                map[code] = {
                    open_ratio:        (mod.open_ratio  !== undefined) ? mod.open_ratio  : (parseFloat(row.open_ratio)        || 0),
                    close_ratio:       (mod.close_ratio !== undefined) ? mod.close_ratio : (parseFloat(row.close_ratio)       || 0),
                    closetoday_ratio:  (mod.closetoday_ratio !== undefined) ? mod.closetoday_ratio : (parseFloat(row.closetoday_ratio)  || 0),
                    open_fixed:        parseFloat(row.open_fixed)        || 0,
                    close_fixed:       parseFloat(row.close_fixed)       || 0,
                    closetoday_fixed:  parseFloat(row.closetoday_fixed)  || 0,
                };
            });
            return map;
        },

        /** Whether fee table data has been loaded */
        hasFeeData: function() { return _feeTableData.length > 0; },

        /** Get fee rows with applied modifications (for per-product expand display).
         *  Returns [{code, name, exchange, multiplier, open_ratio, close_ratio, closetoday_ratio, open_fixed, close_fixed, closetoday_fixed}] */
        getFeeRows: function() {
            return _feeTableData.map(function(row) {
                var code = (row.variety_code || '').toLowerCase();
                var mod = _feeModifications[code] || {};
                return {
                    code:             code,
                    name:             row.variety_name || '',
                    exchange:         row.exchange || '',
                    multiplier:       row.multiplier || '',
                    open_ratio:       (mod.open_ratio  !== undefined) ? mod.open_ratio  : (parseFloat(row.open_ratio)        || 0),
                    close_ratio:      (mod.close_ratio !== undefined) ? mod.close_ratio : (parseFloat(row.close_ratio)       || 0),
                    closetoday_ratio: (mod.closetoday_ratio !== undefined) ? mod.closetoday_ratio : (parseFloat(row.closetoday_ratio)  || 0),
                    open_fixed:       parseFloat(row.open_fixed)        || 0,
                    close_fixed:      parseFloat(row.close_fixed)       || 0,
                    closetoday_fixed: parseFloat(row.closetoday_fixed)  || 0,
                };
            });
        },

        /**
         * Build fee payload for API calls.
         * Returns Promise<{fee, fee_map}> — fetches table on demand in per_product mode.
         */
        buildFeePayload: async function() {
            var fee = 0.0;
            var fee_map = {};
            var feeMode = 'none';
            var feeModeEl = document.querySelector('input[name="fee_mode"]:checked');
            if (feeModeEl) feeMode = feeModeEl.value;
            if (feeMode === 'uniform') {
                fee = parseFloat(document.getElementById('fee_rate').value) || 0.0;
            } else if (feeMode === 'per_product') {
                if (!_feeTableData.length) {
                    var statusSpan = document.getElementById('group_test_status');
                    if (statusSpan) {
                        statusSpan.innerHTML = '正在获取品种费率...';
                        statusSpan.style.color = '#0078d4';
                    }
                    try {
                        await fetchFeeTable(false);
                    } catch (err) {
                        throw new Error('获取品种费率失败: ' + err.message);
                    }
                }
                fee_map = api.buildFeeMap();
            }
            return { fee: fee, fee_map: fee_map };
        },

        /** Fetch fee table from backend */
        fetchFeeTable: fetchFeeTable,

        /** Render fee table (re-render from cached data) */
        renderFeeTable: function() { renderFeeTable(); },

        /** Reset all fees to original values */
        resetAllFees: resetAllFees,

        /** Bind fee control events (drawer, radios, slider, close-today) */
        bind: bindFeeControls,
    };

    GT.fee = api;

    // ── Legacy window hooks (for snapshot compatibility) ─────────────────────
    window._getFeeModifications = function() { return api.getModifications(); };
    window._applyFeeModifications = function(mods) { api.applyModifications(mods); };

    // ── Implementation ───────────────────────────────────────────────────────

    function fetchFeeTable(forceRefresh) {
        var statusEl = document.getElementById('drawer_fee_fetch_status');
        if (statusEl) { statusEl.textContent = '加载中...'; statusEl.style.color = '#0078d4'; }
        return fetch('/get_fee_table', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force_refresh: !!forceRefresh })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) {
                if (statusEl) { statusEl.textContent = '获取失败: ' + data.error; statusEl.style.color = '#d40000'; }
                throw new Error(data.error || '获取失败');
            }
            _feeTableData = data.rows || [];
            renderFeeTable();
            updateFeeSummary();
            if (statusEl) { statusEl.textContent = '✓ 已加载 ' + _feeTableData.length + ' 个品种'; statusEl.style.color = '#28a745'; }
            return data;
        })
        .catch(function(err) {
            if (statusEl) { statusEl.textContent = '请求失败: ' + err.message; statusEl.style.color = '#d40000'; }
            throw err;
        });
    }

    function renderFeeTable() {
        var tbody = document.getElementById('fee_table_body');
        if (!tbody) return;
        if (!_feeTableData.length) {
            tbody.innerHTML = '<tr><td colspan="8" style="padding:16px;text-align:center;color:#888;">暂无数据</td></tr>';
            return;
        }
        var html = '';
        _feeTableData.forEach(function(row) {
            var code = (row.variety_code || '');
            var codeLower = code.toLowerCase();
            var mod = _feeModifications[codeLower] || {};
            var openR  = (mod.open_ratio  !== undefined) ? mod.open_ratio  : (parseFloat(row.open_ratio) || 0);
            var closeR = (mod.close_ratio !== undefined) ? mod.close_ratio : (parseFloat(row.close_ratio) || 0);
            var closeTodayR = (mod.closetoday_ratio !== undefined) ? mod.closetoday_ratio : (parseFloat(row.closetoday_ratio) || 0);
            var total  = (openR + closeR) * 100;

            var openModified  = !!(mod.open_ratio !== undefined);
            var closeModified = !!(mod.close_ratio !== undefined);
            var closeTodayModified = !!(mod.closetoday_ratio !== undefined);
            var openClass  = openModified  ? 'fee-cell-modified' : '';
            var closeClass = closeModified ? 'fee-cell-modified' : '';
            var closeTodayClass = closeTodayModified ? 'fee-cell-modified' : '';

            html += '<tr>';
            html += '<td style="padding:6px 10px;border-bottom:1px solid #eef2f7;font-weight:600;">' + code + '</td>';
            html += '<td style="padding:6px 10px;border-bottom:1px solid #eef2f7;">' + (row.variety_name || '') + '</td>';
            html += '<td style="padding:6px 10px;border-bottom:1px solid #eef2f7;">' + (row.exchange || '') + '</td>';
            html += '<td style="padding:6px 10px;border-bottom:1px solid #eef2f7;text-align:right;">' + (row.multiplier || '') + '</td>';
            html += '<td class="' + openClass + '" contenteditable="true" data-variety="' + codeLower + '" data-field="open_ratio" style="padding:6px 10px;border-bottom:1px solid #eef2f7;text-align:right;">' + openR.toFixed(6) + '</td>';
            html += '<td class="' + closeTodayClass + '" contenteditable="true" data-variety="' + codeLower + '" data-field="closetoday_ratio" style="padding:6px 10px;border-bottom:1px solid #eef2f7;text-align:right;">' + closeTodayR.toFixed(6) + '</td>';
            html += '<td class="' + closeClass + '" contenteditable="true" data-variety="' + codeLower + '" data-field="close_ratio" style="padding:6px 10px;border-bottom:1px solid #eef2f7;text-align:right;">' + closeR.toFixed(6) + '</td>';
            html += '<td style="padding:6px 10px;border-bottom:1px solid #eef2f7;text-align:right;">';
            html += total > 0 ? total.toFixed(4) + '%' : '—';
            html += '</td>';
            html += '</tr>';
        });
        tbody.innerHTML = html;

        // 绑定可编辑单元格事件
        tbody.querySelectorAll('[contenteditable="true"]').forEach(function(cell) {
            cell.addEventListener('blur', _onFeeCellBlur);
            cell.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') { e.preventDefault(); this.blur(); }
                if (e.key === 'Escape') { this.blur(); }
            });
        });
    }

    function _onFeeCellBlur() {
        var variety = this.getAttribute('data-variety');
        var field = this.getAttribute('data-field');
        var rawVal = (this.textContent || '').trim();
        var val = parseFloat(rawVal);
        if (isNaN(val) || val < 0) {
            var row = _feeTableData.find(function(r) { return (r.variety_code || '').toLowerCase() === variety; });
            if (row) {
                var origVal = parseFloat(row[field]) || 0;
                this.textContent = origVal.toFixed(6);
            }
            return;
        }

        var row = _feeTableData.find(function(r) { return (r.variety_code || '').toLowerCase() === variety; });
        if (!row) return;
        var origVal = parseFloat(row[field]) || 0;

        if (Math.abs(val - origVal) < 1e-9) {
            this.textContent = origVal.toFixed(6);
            this.classList.remove('fee-cell-modified');
            if (_feeModifications[variety]) {
                delete _feeModifications[variety][field];
                if (Object.keys(_feeModifications[variety]).length === 0) delete _feeModifications[variety];
            }
        } else {
            this.textContent = val.toFixed(6);
            this.classList.add('fee-cell-modified');
            if (!_feeModifications[variety]) _feeModifications[variety] = {};
            _feeModifications[variety][field] = val;
        }
        updateFeeSummary();
        _refreshTotalColumn(variety);
    }

    function _refreshTotalColumn(variety) {
        var row = _feeTableData.find(function(r) { return (r.variety_code || '').toLowerCase() === variety; });
        if (!row) return;
        var mod = _feeModifications[variety] || {};
        var openR  = (mod.open_ratio  !== undefined) ? mod.open_ratio  : (parseFloat(row.open_ratio) || 0);
        var closeR = (mod.close_ratio !== undefined) ? mod.close_ratio : (parseFloat(row.close_ratio) || 0);
        var total = (openR + closeR) * 100;
        var cells = document.querySelectorAll('#fee_table_body td[data-variety="' + variety + '"]');
        if (cells.length > 0) {
            var tr = cells[0].parentElement;
            if (tr) {
                var lastTd = tr.querySelector('td:last-child');
                if (lastTd) lastTd.innerHTML = total > 0 ? total.toFixed(4) + '%' : '—';
            }
        }
    }

    function updateFeeSummary() {
        var summaryEl = document.getElementById('group-fee-summary');
        if (!summaryEl) return;
        var total = _feeTableData.length;
        var modifiedCount = Object.keys(_feeModifications).length;
        if (total === 0) {
            summaryEl.textContent = '(暂无数据)';
        } else if (modifiedCount === 0) {
            summaryEl.textContent = '(' + total + '个)';
        } else {
            summaryEl.textContent = '(' + total + '个, ' + modifiedCount + '个已修改)';
            summaryEl.style.color = '#d97706';
        }
    }

    function resetAllFees() {
        _feeModifications = {};
        renderFeeTable();
        updateFeeSummary();
    }

    function updateClosetodayUI() {
        var stateEl = document.getElementById('closetoday_state_text');
        var ctBtn   = document.getElementById('use_closetoday_btn');
        if (stateEl) {
            stateEl.textContent = _useCloseToday ? '平今仓' : '平昨仓';
            stateEl.style.color = _useCloseToday ? '#d97706' : '#0078d4';
        }
        if (ctBtn) {
            ctBtn.textContent = _useCloseToday ? '切换为平昨仓' : '切换为平今仓';
            ctBtn.classList.toggle('btn-outline-secondary', !_useCloseToday);
            ctBtn.classList.toggle('btn-outline-warning', _useCloseToday);
        }
    }

    function openFeeDrawer() {
        var overlay = document.getElementById('group-fee-drawer');
        var badge = document.getElementById('user-badge');
        if (overlay) overlay.classList.add('open');
        if (badge) badge.style.display = 'none';
    }

    function closeFeeDrawer() {
        var overlay = document.getElementById('group-fee-drawer');
        var badge = document.getElementById('user-badge');
        if (overlay) overlay.classList.remove('open');
        if (badge) badge.style.display = '';
    }

    function bindFeeControls() {
        // 费率模式单选按钮
        document.querySelectorAll('input[name="fee_mode"]').forEach(function(radio) {
            radio.addEventListener('change', function() {
                var mode = this.value;
                var uniformWrap = document.getElementById('fee_uniform_row');
                if (uniformWrap) uniformWrap.style.display = (mode === 'uniform') ? 'flex' : 'none';
            });
        });

        // 打开费率抽屉
        var trigger = document.getElementById('group-fee-drawer-trigger');
        if (trigger) trigger.addEventListener('click', openFeeDrawer);

        // 关闭费率抽屉
        var closeBtn = document.getElementById('group-fee-drawer-close');
        if (closeBtn) closeBtn.addEventListener('click', closeFeeDrawer);

        // 点击遮罩层关闭
        var overlay = document.getElementById('group-fee-drawer');
        if (overlay) overlay.addEventListener('click', function(e) {
            if (e.target === overlay) closeFeeDrawer();
        });

        // 抽屉内获取费率按钮
        var fetchBtn = document.getElementById('drawer_fetch_fee_btn');
        if (fetchBtn) fetchBtn.addEventListener('click', function() { fetchFeeTable(false).catch(function() {}); });

        // 抽屉内恢复原始值按钮
        var resetBtn = document.getElementById('drawer_reset_fee_btn');
        if (resetBtn) resetBtn.addEventListener('click', resetAllFees);

        // 平今/平昨切换按钮
        var ctBtn = document.getElementById('use_closetoday_btn');
        if (ctBtn) ctBtn.addEventListener('click', function() {
            _useCloseToday = !_useCloseToday;
            updateClosetodayUI();
            if (_feeTableData.length) renderFeeTable();
            // 切换平今/平昨后重新生成所有精选组
            if (GT.ui && typeof GT.ui.onCloseTodayChanged === 'function') {
                GT.ui.onCloseTodayChanged();
            }
        });

        // 成本敏感性滑条（仅统一费率模式有效）
        var _sliderDebounceTimer = null;
        var slider = document.getElementById('fee_sensitivity_slider');
        if (slider) {
            function onSliderInput() {
                var feeModeEl = document.querySelector('input[name="fee_mode"]:checked');
                var mode = feeModeEl ? feeModeEl.value : 'none';
                if (mode !== 'uniform') return;
                var val = parseFloat(slider.value);
                updateSensitivityLabel(val);
                if (_sliderDebounceTimer) clearTimeout(_sliderDebounceTimer);
                _sliderDebounceTimer = setTimeout(function() {
                    if (GT.ui && typeof GT.ui.recalcWithFee === 'function') {
                        GT.ui.recalcWithFee(val);
                    }
                }, 50);
            }
            slider.addEventListener('input', onSliderInput);
            slider.addEventListener('change', function() {
                if (_sliderDebounceTimer) clearTimeout(_sliderDebounceTimer);
                var feeModeEl = document.querySelector('input[name="fee_mode"]:checked');
                var mode = feeModeEl ? feeModeEl.value : 'none';
                if (mode !== 'uniform') return;
                var val = parseFloat(this.value);
                updateSensitivityLabel(val);
                if (GT.ui && typeof GT.ui.recalcWithFee === 'function') {
                    GT.ui.recalcWithFee(val);
                }
            });
        }
    }

    function updateSensitivityLabel(val) {
        var lbl = document.getElementById('fee_sensitivity_label');
        if (lbl) lbl.textContent = parseFloat(val).toFixed(3) + '%';
    }
})();
