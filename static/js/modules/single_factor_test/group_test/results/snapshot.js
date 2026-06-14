/**
 * Group snapshot drawer — "图上每个分组的每期每组产品信息"
 *
 * 点击图表上任一时间点时，展示该时刻所有分组（可见的图线上各组）
 * 的完整产品持仓。当前只渲染单一仓位矩阵，并复用分组列表的展开态。
 *
 * Exposes GT.results.snapshot with:
 *   - fetchGroupSnapshot(timestampMs)
 *   - openSnapshotDrawer()
 *   - closeSnapshotDrawer()
 *   - bindSnapshotDrawerEvents()
 *   - renderGroupSnapshot(data, timestampMs)
 *
 * Issue: #98、#99
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    GT.results = GT.results || {};

    // ---------- 快照导航状态 ----------
    var _snapshotTimestamps = [];  // 所有可用时间点（epoch ms）
    var _snapshotCurrentMs = null; // 当前显示的时间点
    var _snapshotPrevChangeMs = null;
    var _snapshotNextChangeMs = null;

    function _selection() {
        return GT.panels && GT.panels.list && GT.panels.list.selection;
    }

    function _activeSubmissionId() {
        // 优先从最近的分组测试结果中获取 submission_id，
        // 这样用户无需在分组列表中手动选中即可查看快照 (refs #100)。
        var c = GT.groupSettings && GT.groupSettings.cache ? GT.groupSettings.cache : null;
        var grossData = c ? c.getLastGrossData() : null;
        if (grossData && grossData.length > 0) {
            var first = grossData[0];
            if (first && first.submission_id) return first.submission_id;
        }
        // fallback: 从分组列表 selection 获取
        var sel = _selection();
        return sel && typeof sel.getFirstSubmissionId === 'function' ? sel.getFirstSubmissionId() : null;
    }

    function _escape(value) {
        return GT.escapeHTML ? GT.escapeHTML(value) : String(value == null ? '' : value);
    }

    // ---------- 获取并展示分组快照 ----------
    function fetchGroupSnapshot(timestampMs) {
        var submissionId = _activeSubmissionId();
        if (!submissionId) {
            alert('请先在提交列表中选中一条提交记录，再点击图表查看持仓快照。');
            return;
        }

        timestampMs = Number(timestampMs);
        if (!isFinite(timestampMs)) {
            document.getElementById('snapshot_title').innerHTML = '📋 分组持仓快照 — 错误';
            document.getElementById('snapshot_body').innerHTML = '<div style="padding:20px;color:#d40000;">图表点击未能定位到有效时间点</div>';
            document.getElementById('snapshot_flow_stats').innerHTML = '';
            _updateSnapshotNavButtons(null);
            openSnapshotDrawer();
            return;
        }

        timestampMs = Math.round(timestampMs);
        _snapshotCurrentMs = timestampMs;

        // 加载中：禁用导航按钮并显示加载提示
        var prevBtn = document.getElementById('snapshot-prev-btn');
        var nextBtn = document.getElementById('snapshot-next-btn');
        var prevChangeBtn = document.getElementById('snapshot-prev-change-btn');
        var nextChangeBtn = document.getElementById('snapshot-next-change-btn');
        [prevBtn, nextBtn, prevChangeBtn, nextChangeBtn].forEach(function(btn) {
            if (btn) { btn.disabled = true; btn.textContent = '⏳ 加载中...'; btn.style.opacity = '0.6'; }
        });
        document.getElementById('snapshot_title').innerHTML = '📋 分组持仓快照 — 加载中';
        document.getElementById('snapshot_body').innerHTML = '<div class="snapshot-empty-tab">正在加载持仓快照...</div>';
        document.getElementById('snapshot_flow_stats').innerHTML = '';
        openSnapshotDrawer();

        var endpoint = '/get_group_snapshot';
        if (window.location && window.location.origin && window.location.origin !== 'null') {
            endpoint = window.location.origin.replace(/\/$/, '') + '/get_group_snapshot';
        }
        var requestOptions = {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                submission_id: submissionId,
                timestamp_ms: timestampMs
            })
        };

        Promise.resolve().then(function() {
            return fetch(endpoint, requestOptions);
        })
        .then(function(res) {
            return res.text().then(function(text) {
                var data = null;
                try {
                    data = text ? JSON.parse(text) : {};
                } catch (e) {
                    throw new Error('快照接口返回的内容不是标准 JSON: ' + text.slice(0, 300));
                }
                if (!res.ok && data && !data.error) {
                    data.error = 'HTTP ' + res.status;
                }
                return data;
            });
        })
        .then(function(data) {
            if (!data.success) {
                document.getElementById('snapshot_title').innerHTML = '📋 分组持仓快照 — 错误';
                document.getElementById('snapshot_body').innerHTML = '<div style="padding:20px;color:#d40000;">' + (data.error || '未知错误') + '</div>';
                document.getElementById('snapshot_flow_stats').innerHTML = '';
                _updateSnapshotNavButtons(null);
                openSnapshotDrawer();
                return;
            }
            _snapshotTimestamps = data.all_timestamps_ms || [];
            _snapshotCurrentMs = data.timestamp_ms;
            _snapshotPrevChangeMs = data.prev_change_timestamp_ms || null;
            _snapshotNextChangeMs = data.next_change_timestamp_ms || null;

            try {
                renderGroupSnapshot(data, data.timestamp_ms);
                _updateSnapshotNavButtons(data);
            } catch (e) {
                console.error('[snapshot] renderGroupSnapshot error:', e);
                document.getElementById('snapshot_title').innerHTML = '📋 分组持仓快照 — 渲染失败';
                document.getElementById('snapshot_body').innerHTML = '<div style="padding:20px;color:#d40000;">渲染快照时出错: ' + (e.message || e) + '</div>';
                document.getElementById('snapshot_flow_stats').innerHTML = '';
                _updateSnapshotNavButtons(null);
            }
            openSnapshotDrawer();
        })
        .catch(function(err) {
            document.getElementById('snapshot_title').innerHTML = '📋 分组持仓快照 — 错误';
            document.getElementById('snapshot_body').innerHTML = '<div style="padding:20px;color:#d40000;">请求失败: ' + err.message + '</div>';
            document.getElementById('snapshot_flow_stats').innerHTML = '';
            _updateSnapshotNavButtons(null);
            openSnapshotDrawer();
        });
    }

    /** 更新前/后导航按钮状态 */
    function _updateSnapshotNavButtons(data) {
        var prevBtn = document.getElementById('snapshot-prev-btn');
        var nextBtn = document.getElementById('snapshot-next-btn');
        var prevChangeBtn = document.getElementById('snapshot-prev-change-btn');
        var nextChangeBtn = document.getElementById('snapshot-next-change-btn');

        if (prevBtn) prevBtn.textContent = '◀ 前一时刻';
        if (nextBtn) nextBtn.textContent = '后一时刻 ▶';
        if (prevChangeBtn) prevChangeBtn.textContent = '◀ 前一变化';
        if (nextChangeBtn) nextChangeBtn.textContent = '后一变化 ▶';

        if (!data) {
            [prevBtn, nextBtn, prevChangeBtn, nextChangeBtn].forEach(function(btn) {
                if (btn) { btn.disabled = true; btn.style.opacity = '0.4'; }
            });
            return;
        }

        if (prevBtn) {
            prevBtn.disabled = !data.has_prev;
            prevBtn.style.opacity = data.has_prev ? '1' : '0.4';
        }
        if (nextBtn) {
            nextBtn.disabled = !data.has_next;
            nextBtn.style.opacity = data.has_next ? '1' : '0.4';
        }
        if (prevChangeBtn) {
            prevChangeBtn.disabled = !data.has_prev_change;
            prevChangeBtn.style.opacity = data.has_prev_change ? '1' : '0.4';
        }
        if (nextChangeBtn) {
            nextChangeBtn.disabled = !data.has_next_change;
            nextChangeBtn.style.opacity = data.has_next_change ? '1' : '0.4';
        }
    }

    /** 导航到上一个/下一个时点 */
    function navigateSnapshot(direction) {
        if (!_snapshotTimestamps.length) return;
        var idx = _snapshotTimestamps.indexOf(_snapshotCurrentMs);
        if (idx < 0) return;
        var newIdx = idx + (direction === 'next' ? 1 : -1);
        if (newIdx < 0 || newIdx >= _snapshotTimestamps.length) return;
        fetchGroupSnapshot(_snapshotTimestamps[newIdx]);
    }

    function navigateSnapshotChange(direction) {
        var target = direction === 'next' ? _snapshotNextChangeMs : _snapshotPrevChangeMs;
        if (target === null || target === undefined) return;
        fetchGroupSnapshot(target);
    }

    function openSnapshotDrawer() {
        var overlay = document.getElementById('group-snapshot-drawer');
        if (overlay) overlay.classList.add('open');
    }

    function closeSnapshotDrawer() {
        var overlay = document.getElementById('group-snapshot-drawer');
        if (overlay) overlay.classList.remove('open');
    }

    /** 绑定快照抽屉事件（关闭按钮 + 遮罩点击 + 前/后导航） */
    function bindSnapshotDrawerEvents() {
        var overlay = document.getElementById('group-snapshot-drawer');
        var closeBtn = document.getElementById('group-snapshot-drawer-close');
        var prevBtn = document.getElementById('snapshot-prev-btn');
        var nextBtn = document.getElementById('snapshot-next-btn');
        var prevChangeBtn = document.getElementById('snapshot-prev-change-btn');
        var nextChangeBtn = document.getElementById('snapshot-next-change-btn');
        if (closeBtn) closeBtn.addEventListener('click', closeSnapshotDrawer);
        if (prevBtn) prevBtn.addEventListener('click', function() { navigateSnapshot('prev'); });
        if (nextBtn) nextBtn.addEventListener('click', function() { navigateSnapshot('next'); });
        if (prevChangeBtn) prevChangeBtn.addEventListener('click', function() { navigateSnapshotChange('prev'); });
        if (nextChangeBtn) nextChangeBtn.addEventListener('click', function() { navigateSnapshotChange('next'); });
        if (overlay) overlay.addEventListener('click', function(e) {
            if (e.target === overlay) closeSnapshotDrawer();
        });
    }

    /** 格式化时间戳 */
    function _fmtTs(ts, timezone) {
        var d = new Date(ts);
        if (timezone && typeof Intl !== 'undefined' && Intl.DateTimeFormat) {
            try {
                var parts = new Intl.DateTimeFormat('zh-CN', {
                    timeZone: timezone,
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                    hour12: false,
                }).formatToParts(d);
                var values = {};
                parts.forEach(function(part) {
                    if (part.type !== 'literal') values[part.type] = part.value;
                });
                return values.year + '-' + values.month + '-' + values.day + ' '
                    + values.hour + ':' + values.minute + ':' + values.second;
            } catch (err) {
                // Fall back to browser-local formatting below.
            }
        }
        return d.getFullYear() + '-' +
            String(d.getMonth() + 1).padStart(2, '0') + '-' +
            String(d.getDate()).padStart(2, '0') + ' ' +
            String(d.getHours()).padStart(2, '0') + ':' +
            String(d.getMinutes()).padStart(2, '0') + ':' +
            String(d.getSeconds()).padStart(2, '0');
    }

    // ──────────── 辅助渲染函数 ────────────

    var _snapshotPayload = null;
    var _snapshotMatrixKey = 'raw';

    function _matrixByKey(key) {
        var matrices = _snapshotPayload && Array.isArray(_snapshotPayload.matrices) ? _snapshotPayload.matrices : [];
        if (!matrices.length) return null;
        for (var i = 0; i < matrices.length; i++) {
            if (matrices[i] && matrices[i].key === key) return matrices[i];
        }
        return matrices[0];
    }

    function _nextTimestampMs(ts) {
        var idx = _snapshotTimestamps.indexOf(ts);
        if (idx >= 0 && idx + 1 < _snapshotTimestamps.length) return _snapshotTimestamps[idx + 1];
        return null;
    }

    function _formatAmount(v) {
        if (v === null || v === undefined || v === '') return '';
        var num = Number(v);
        if (!isFinite(num)) return '';
        return Math.abs(num) >= 1 ? num.toFixed(2) : num.toFixed(6);
    }

    function _formatSigned(v) {
        var num = Number(v);
        if (!isFinite(num) || Math.abs(num) <= 1e-12) return '0.000000';
        return (num > 0 ? '+' : '') + num.toFixed(6);
    }

    function _formatQuantity(v) {
        var num = Number(v);
        if (!isFinite(num)) return '';
        return String(Math.round(num));
    }

    function _formatSignedQuantity(v) {
        var num = Number(v);
        if (!isFinite(num) || Math.abs(num) <= 1e-12) return '0';
        var rounded = Math.round(num);
        return (rounded > 0 ? '+' : '') + String(rounded);
    }

    function _formatSignedAmount(v) {
        var num = Number(v);
        if (!isFinite(num) || Math.abs(num) <= 1e-12) return '0.00';
        return (num > 0 ? '+' : '') + _formatAmount(num);
    }

    function _renderProduct(p) {
        if (!p) return '—';
        if (typeof p === 'string') return '<span class="snapshot-product-name">' + _escape(p) + '</span>';
        var name = _escape(p.name || '');
        var isSummary = p.name === '总资产' || p.name === '现金';
        var desc = !isSummary && p.desc && p.desc !== p.name ? ' <span class="snapshot-product-desc">' + _escape(p.desc) + '</span>' : '';
        var feeHtml = '';
        if (p.fee) {
            var parts = [];
            if (p.fee.open_ratio !== undefined) parts.push('开' + (Number(p.fee.open_ratio) * 100).toFixed(3) + '%');
            if (p.fee.close_ratio !== undefined) parts.push('平' + (Number(p.fee.close_ratio) * 100).toFixed(3) + '%');
            if (parts.length) feeHtml = ' <span class="snapshot-product-fee">[' + parts.join(' ') + ']</span>';
        }
        var sourceHtml = '';
        if (Array.isArray(p.source_names) && p.source_names.length > 1) {
            sourceHtml = ' <span class="snapshot-product-source">(' + _escape(p.source_names.join(' / ')) + ')</span>';
        }
        return '<span class="snapshot-product-name" title="' + name + '">' + name + desc + feeHtml + sourceHtml + '</span>';
    }

    function _renderMatrixCell(cell) {
        if (!cell || cell.status === 'absent') return '<span class="snapshot-cell-empty">—</span>';
        var parts = [];
        var statusLabels = {
            entering: '新增',
            increasing: '增加',
            decreasing: '减少',
            exiting: '退出',
            pending_exit: '待卖',
            holding: '持有',
            selected: '选中',
        };
        if (statusLabels[cell.status]) {
            parts.push('<div class="snapshot-status-label">' + statusLabels[cell.status] + '</div>');
        }
        parts.push(_renderProduct(cell.product));
        if (cell.selected) {
            parts.push('<div class="snapshot-selected-hint">已选中</div>');
        }
        var meta = [];
        if (cell.selected) {
            if (cell.planned_qty !== null && cell.planned_qty !== undefined) {
                meta.push('可开 ' + _formatQuantity(cell.planned_qty) + ' 手');
            }
            if (cell.planned_amount !== null && cell.planned_amount !== undefined) {
                meta.push('计划金额 ' + _formatAmount(cell.planned_amount));
            }
            if (cell.target_budget_amount !== null && cell.target_budget_amount !== undefined) {
                meta.push('目标预算 ' + _formatAmount(cell.target_budget_amount));
            }
            if (cell.liquidity_cap_amount !== null && cell.liquidity_cap_amount !== undefined) {
                meta.push('成交额限额 ' + _formatAmount(cell.liquidity_cap_amount));
            }
        }
        if (cell.quantity !== null && cell.quantity !== undefined && (Math.abs(Number(cell.quantity)) > 1e-12 || Math.abs(Number(cell.amount || 0)) > 1e-12)) {
            meta.push('持仓 ' + _formatQuantity(cell.quantity));
            if (cell.amount !== null && cell.amount !== undefined) meta.push('金额 ' + _formatAmount(cell.amount));
        } else if (cell.pre_rebalance_amount !== null && cell.pre_rebalance_amount !== undefined
            && cell.post_rebalance_amount !== null && cell.post_rebalance_amount !== undefined
            && cell.end_amount !== null && cell.end_amount !== undefined) {
            parts.push('<div class="snapshot-summary-amounts">'
                + '<div>调仓前 ' + _formatAmount(cell.pre_rebalance_amount) + '</div>'
                + '<div>调仓后 ' + _formatAmount(cell.post_rebalance_amount) + '</div>'
                + '<div>期末 ' + _formatAmount(cell.end_amount) + '</div>'
                + '</div>');
            if (cell.buy_fee_amount !== null && cell.buy_fee_amount !== undefined) {
                parts.push('<div class="snapshot-summary-fees">买入费 ' + _formatAmount(cell.buy_fee_amount) + '</div>');
            }
            if (cell.sell_fee_amount !== null && cell.sell_fee_amount !== undefined) {
                parts.push('<div class="snapshot-summary-fees">卖出费 ' + _formatAmount(cell.sell_fee_amount) + '</div>');
            }
        } else if (cell.amount !== null && cell.amount !== undefined) {
            meta.push('金额 ' + _formatAmount(cell.amount));
        }
        if (cell.open_reason) {
            meta.push(cell.open_reason);
        }
        if (meta.length) {
            parts.push('<div class="snapshot-cell-meta">');
            meta.forEach(function(line) {
                parts.push('<div>' + _escape(line) + '</div>');
            });
            parts.push('</div>');
        }
        var deltaParts = [];
        if (cell.delta_quantity !== null && cell.delta_quantity !== undefined) {
            deltaParts.push('变化 ' + _formatSignedQuantity(cell.delta_quantity));
        }
        if (cell.delta_amount !== null && cell.delta_amount !== undefined) {
            deltaParts.push('金额 ' + _formatSignedAmount(cell.delta_amount));
        }
        if (deltaParts.length) {
            var direction = cell.change_direction || 'flat';
            parts.push('<div class="snapshot-cell-delta snapshot-delta-' + _escape(direction) + '">' + deltaParts.join(' · ') + '</div>');
        }
        return parts.join('');
    }

    function _renderMatrixToggle() {
        var toggleEl = document.getElementById('snapshot_matrix_toggle');
        if (!toggleEl) return;
        var matrices = _snapshotPayload && Array.isArray(_snapshotPayload.matrices) ? _snapshotPayload.matrices : [];
        if (matrices.length <= 1) {
            toggleEl.innerHTML = '';
            return;
        }
        var html = '<div class="snapshot-matrix-switch" role="tablist">';
        matrices.forEach(function(matrix) {
            var active = matrix.key === _snapshotMatrixKey ? ' active' : '';
            html += '<button type="button" class="snapshot-matrix-switch-btn' + active + '" data-matrix-key="' + _escape(matrix.key) + '">' + _escape(matrix.label || matrix.key) + '</button>';
        });
        html += '</div>';
        toggleEl.innerHTML = html;
        var buttons = toggleEl.querySelectorAll ? toggleEl.querySelectorAll('.snapshot-matrix-switch-btn') : [];
        for (var i = 0; i < buttons.length; i++) {
            buttons[i].onclick = function(evt) {
                var key = evt.currentTarget.getAttribute('data-matrix-key');
                if (!key) return;
                _snapshotMatrixKey = key;
                renderGroupSnapshot(_snapshotPayload, _snapshotPayload.timestamp_ms);
            };
        }
    }

    function _renderSnapshotMatrix(matrix) {
        if (!matrix) return '<div class="snapshot-empty-tab">暂无分组数据</div>';
        var html = '';
        html += '<div class="snapshot-batch-section">';
        html += '<div class="snapshot-batch-header">仓位矩阵 · ' + _escape(matrix.label || matrix.key || '默认') + '</div>';
        html += '<div class="snapshot-semantics-note">本矩阵按标题所示期间展示。表头数字表示该组该时刻被选中的品种数；单元格里“选中”表示 membership 已命中，但可能因为最小手数、资金、保证金或流动性限制未实际开仓。单元格中的“分配开仓”“一手保证金”“一手总需求”都指本期调仓前的计划值；产品金额变化为本期调仓前旧持仓估值到调仓后新持仓金额的变化；总资产/现金变化为调仓后到期末的持有期间变化，期末指下一次调仓前。</div>';
        html += '<div class="snapshot-matrix-scroll">';
        html += '<table class="snapshot-matrix-table"><thead><tr>';
        html += '<th class="snapshot-prod-name-cell">产品</th>';
        (matrix.columns || []).forEach(function(col) {
            var label = col.label || col.name || '';
            var count = col.count !== undefined && col.count !== null ? Number(col.count) : null;
            var countLabel = col.count_label || '持仓品种数(xxx)';
            html += '<th><div class="snapshot-col-label">' + _escape(label) + '</div>';
            if (count !== null && isFinite(count)) {
                html += '<div class="snapshot-col-count">' + count + '</div>';
                html += '<div class="snapshot-col-count-label">' + _escape(countLabel) + '</div>';
            }
            html += '</th>';
        });
        html += '</tr></thead><tbody>';

        (matrix.rows || []).forEach(function(row, rowIndex) {
            html += '<tr>';
            html += '<td class="snapshot-prod-name-cell">' + _renderProduct(row) + '</td>';
            (matrix.cells && matrix.cells[rowIndex] ? matrix.cells[rowIndex] : []).forEach(function(cell) {
                var status = cell && cell.status ? cell.status : 'absent';
                var direction = cell && cell.change_direction ? cell.change_direction : 'flat';
                html += '<td class="snapshot-cell-' + status + ' snapshot-change-' + _escape(direction) + '">' + _renderMatrixCell(cell) + '</td>';
            });
            html += '</tr>';
        });

        html += '</tbody></table></div></div>';
        return html;
    }

    function renderGroupSnapshot(data, timestampMs) {
        if (!data || !Array.isArray(data.matrices)) return;

        _snapshotPayload = data;
        if (Array.isArray(data.all_timestamps_ms)) {
            _snapshotTimestamps = data.all_timestamps_ms;
        }
        if (!_snapshotMatrixKey || !_matrixByKey(_snapshotMatrixKey)) {
            _snapshotMatrixKey = data.default_matrix_key || (data.matrices[0] && data.matrices[0].key) || 'raw';
        }

        var timezone = data.display_timezone || data.timezone || null;
        var timeStr = _fmtTs(timestampMs, timezone);
        var nextTs = _nextTimestampMs(timestampMs);
        var titlePeriod = nextTs ? (timeStr + ' 至 ' + _fmtTs(nextTs, timezone)) : (timeStr + ' 起');
        document.getElementById('snapshot_title').innerHTML = '📋 分组持仓快照 — ' + titlePeriod;

        var bodyEl = document.getElementById('snapshot_body');
        var statsEl = document.getElementById('snapshot_flow_stats');
        if (!bodyEl) return;

        var matrix = _matrixByKey(_snapshotMatrixKey);
        if (!matrix) {
            bodyEl.innerHTML = '<div class="snapshot-empty-tab">暂无分组数据</div>';
            if (statsEl) statsEl.innerHTML = '';
            _renderMatrixToggle();
            return;
        }

        bodyEl.innerHTML = _renderSnapshotMatrix(matrix);

        if (statsEl) {
            var summary = data.summary || {};
            var totalChanged = summary.total_changed !== undefined ? summary.total_changed : 0;
            var totalProdCount = summary.total_prod_count !== undefined ? summary.total_prod_count : 0;
            var avgTurnover = summary.avg_turnover !== undefined ? summary.avg_turnover : 0;
            var statsHtml = '';
            if (data.capital_warning) {
                statsHtml += '<div style="margin-bottom:8px;padding:8px 10px;border:1px solid #f59e0b;background:#fffbeb;color:#92400e;border-radius:6px;line-height:1.5;">'
                    + '⚠️ ' + _escape(data.capital_warning)
                    + '</div>';
            }
            statsHtml += '<div><b>📊 总体流动统计：</b> 换手率 ≈ ' + avgTurnover + '%';
            statsHtml += ' &nbsp;|&nbsp; 总进出 = ' + totalChanged + ' 品种';
            statsHtml += '</div>';
            statsEl.innerHTML = statsHtml;
        }
        _renderMatrixToggle();
    }

    // ---------- 导出 ----------
    GT.results.snapshot = {
        fetchGroupSnapshot: fetchGroupSnapshot,
        openSnapshotDrawer: openSnapshotDrawer,
        closeSnapshotDrawer: closeSnapshotDrawer,
        bindSnapshotDrawerEvents: bindSnapshotDrawerEvents,
        renderGroupSnapshot: renderGroupSnapshot,
    };
})();
