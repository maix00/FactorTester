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
        if (prevBtn) { prevBtn.disabled = true; prevBtn.textContent = '⏳ 加载中...'; prevBtn.style.opacity = '0.6'; }
        if (nextBtn) { nextBtn.disabled = true; nextBtn.textContent = '⏳ 加载中...'; nextBtn.style.opacity = '0.6'; }
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
        if (!prevBtn || !nextBtn) return;

        prevBtn.textContent = '◀ 前一个';
        nextBtn.textContent = '后一个 ▶';

        if (!data) {
            prevBtn.disabled = true;
            nextBtn.disabled = true;
            prevBtn.style.opacity = '0.4';
            nextBtn.style.opacity = '0.4';
            return;
        }

        prevBtn.disabled = !data.has_prev;
        nextBtn.disabled = !data.has_next;
        prevBtn.style.opacity = data.has_prev ? '1' : '0.4';
        nextBtn.style.opacity = data.has_next ? '1' : '0.4';
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
        if (closeBtn) closeBtn.addEventListener('click', closeSnapshotDrawer);
        if (prevBtn) prevBtn.addEventListener('click', function() { navigateSnapshot('prev'); });
        if (nextBtn) nextBtn.addEventListener('click', function() { navigateSnapshot('next'); });
        if (overlay) overlay.addEventListener('click', function(e) {
            if (e.target === overlay) closeSnapshotDrawer();
        });
    }

    /** 格式化时间戳 */
    function _fmtTs(ts) {
        var d = new Date(ts);
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

    function _formatAmount(v) {
        if (v === null || v === undefined || v === '') return '';
        var num = Number(v);
        if (!isFinite(num)) return '';
        return Math.abs(num) >= 1 ? num.toFixed(2) : num.toFixed(6);
    }

    function _renderProduct(p) {
        if (!p) return '—';
        if (typeof p === 'string') return '<span class="snapshot-product-name">' + _escape(p) + '</span>';
        var name = _escape(p.name || '');
        var desc = p.desc && p.desc !== p.name ? ' <span class="snapshot-product-desc">' + _escape(p.desc) + '</span>' : '';
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
        parts.push(_renderProduct(cell.product));
        var meta = [];
        if (cell.quantity !== null && cell.quantity !== undefined) meta.push('持仓 ' + Number(cell.quantity).toFixed(6));
        if (cell.amount !== null && cell.amount !== undefined) meta.push('金额 ' + _formatAmount(cell.amount));
        if (meta.length) parts.push('<div class="snapshot-cell-meta">' + meta.join(' · ') + '</div>');
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
        html += '<div class="snapshot-matrix-scroll">';
        html += '<table class="snapshot-matrix-table"><thead><tr>';
        html += '<th class="snapshot-prod-name-cell">产品</th>';
        (matrix.columns || []).forEach(function(col) {
            var label = col.label || col.name || '';
            var count = col.count !== undefined && col.count !== null ? Number(col.count) : null;
            html += '<th><div class="snapshot-col-label">' + _escape(label) + '</div>';
            if (count !== null && isFinite(count)) {
                html += '<div class="snapshot-col-count">' + count + '</div>';
            }
            html += '</th>';
        });
        html += '</tr></thead><tbody>';

        (matrix.rows || []).forEach(function(row, rowIndex) {
            html += '<tr>';
            html += '<td class="snapshot-prod-name-cell">' + _renderProduct(row) + '</td>';
            (matrix.cells && matrix.cells[rowIndex] ? matrix.cells[rowIndex] : []).forEach(function(cell) {
                var status = cell && cell.status ? cell.status : 'absent';
                html += '<td class="snapshot-cell-' + status + '">' + _renderMatrixCell(cell) + '</td>';
            });
            html += '</tr>';
        });

        html += '</tbody></table></div></div>';
        return html;
    }

    function renderGroupSnapshot(data, timestampMs) {
        if (!data || !Array.isArray(data.matrices)) return;

        _snapshotPayload = data;
        if (!_snapshotMatrixKey || !_matrixByKey(_snapshotMatrixKey)) {
            _snapshotMatrixKey = data.default_matrix_key || (data.matrices[0] && data.matrices[0].key) || 'raw';
        }

        var timeStr = _fmtTs(timestampMs);
        document.getElementById('snapshot_title').innerHTML = '📋 分组持仓快照 — ' + timeStr;

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
            var statsHtml = '<b>📊 总体流动统计：</b> 换手率 ≈ ' + avgTurnover + '%';
            statsHtml += ' &nbsp;|&nbsp; 总进出 = ' + totalChanged + ' 品种';
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
