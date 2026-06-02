/**
 * Group snapshot drawer — fetch, navigate, and render per-period group holdings.
 *
 * Exposes GT.results.snapshot with:
 *   - fetchGroupSnapshot(timestampMs)
 *   - openSnapshotDrawer()
 *   - closeSnapshotDrawer()
 *   - bindSnapshotDrawerEvents()
 *   - renderGroupSnapshot(data, timestampMs)
 *
 * Depends on: GT.utils.dates.getActiveSubmissionId
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    GT.results = GT.results || {};

    // ---------- 快照导航状态 ----------
    var _snapshotTimestamps = [];  // 所有可用时间点（epoch ms）
    var _snapshotCurrentMs = null; // 当前显示的时间点

    // ---------- 获取并展示分组快照 ----------
    function fetchGroupSnapshot(timestampMs) {
        var submissionId = GT.utils.dates ? GT.utils.dates.getActiveSubmissionId() : null;
        if (!submissionId) return;

        timestampMs = Math.round(timestampMs);
        _snapshotCurrentMs = timestampMs;

        // 加载中：禁用导航按钮并显示加载提示
        var prevBtn = document.getElementById('snapshot-prev-btn');
        var nextBtn = document.getElementById('snapshot-next-btn');
        if (prevBtn) { prevBtn.disabled = true; prevBtn.textContent = '⏳ 加载中...'; prevBtn.style.opacity = '0.6'; }
        if (nextBtn) { nextBtn.disabled = true; nextBtn.textContent = '⏳ 加载中...'; nextBtn.style.opacity = '0.6'; }

        fetch('/get_group_snapshot', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                submission_id: submissionId,
                timestamp_ms: timestampMs
            })
        })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (!data.success) {
                document.getElementById('snapshot_title').innerHTML = '📋 分组持仓快照 — 错误';
                document.getElementById('snapshot_head').innerHTML = '';
                document.getElementById('snapshot_body').innerHTML = '<tr><td colspan="10" style="color:#d40000;">' + data.error + '</td></tr>';
                document.getElementById('snapshot_flow_stats').innerHTML = '';
                _updateSnapshotNavButtons(null);
                openSnapshotDrawer();
                return;
            }
            _snapshotTimestamps = data.all_timestamps_ms || [];
            _snapshotCurrentMs = data.timestamp_ms;
            renderGroupSnapshot(data, data.timestamp_ms);
            _updateSnapshotNavButtons(data);
            openSnapshotDrawer();
        })
        .catch(function(err) {
            document.getElementById('snapshot_title').innerHTML = '📋 分组持仓快照 — 错误';
            document.getElementById('snapshot_head').innerHTML = '';
            document.getElementById('snapshot_body').innerHTML = '<tr><td colspan="10" style="color:#d40000;">请求失败: ' + err.message + '</td></tr>';
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

    /** 渲染分组快照抽屉内容 */
    function renderGroupSnapshot(data, timestampMs) {
        var d = new Date(timestampMs);
        var timeStr = d.getFullYear() + '-' +
            String(d.getMonth() + 1).padStart(2, '0') + '-' +
            String(d.getDate()).padStart(2, '0') + ' ' +
            String(d.getHours()).padStart(2, '0') + ':' +
            String(d.getMinutes()).padStart(2, '0') + ':' +
            String(d.getSeconds()).padStart(2, '0');
        document.getElementById('snapshot_title').innerHTML = '📋 分组持仓快照 — ' + timeStr;

        var groups = data.groups || [];

        var colWidth = groups.length > 0 ? (100 / groups.length).toFixed(2) + '%' : '100%';

        var headHtml = '<tr><th style="width:40px;"></th>';
        groups.forEach(function(g) {
            headHtml += '<th style="width:' + colWidth + ';">' + g.name + ' <span style="font-weight:normal;color:#888;">(' + g.count + '品种)</span></th>';
        });
        headHtml += '</tr>';
        document.getElementById('snapshot_head').innerHTML = headHtml;

        function _renderProduct(p) {
            if (!p) return '';
            if (typeof p === 'string') return p;
            if (p.desc && p.desc !== p.name) {
                return '<span title="' + p.name + '">' + p.name + ' <span style="color:#888;font-size:11px;">' + p.desc + '</span></span>';
            }
            return p.name || '';
        }

        var maxRows = Math.max.apply(null, groups.map(function(g) {
            return Math.max(g.products_in.length, g.products_out.length, g.products.length);
        }));

        var tdStyleFull = 'style="width:' + colWidth + ';"';
        var tdStyleWidth = 'width:' + colWidth + ';';

        var bodyHtml = '';
        for (var i = 0; i < maxRows; i++) {
            bodyHtml += '<tr>';
            bodyHtml += '<td style="color:#888;font-size:11px;">' + (i === 0 ? '持仓' : '') + '</td>';
            groups.forEach(function(g) {
                var p = i < g.products.length ? g.products[i] : null;
                bodyHtml += '<td ' + tdStyleFull + '>' + _renderProduct(p) + '</td>';
            });
            bodyHtml += '</tr>';
        }

        bodyHtml += '<tr style="border-top:2px solid #e5e7eb;"><td colspan="' + (groups.length + 1) + '" style="font-weight:600;color:#28a745;padding-top:8px;">📥 新进（相对于上一时点）</td></tr>';
        var maxIn = Math.max.apply(null, groups.map(function(g) { return g.products_in.length; }));
        for (var j = 0; j < Math.max(maxIn, 1); j++) {
            bodyHtml += '<tr>';
            bodyHtml += '<td style="color:#888;font-size:11px;"></td>';
            groups.forEach(function(g) {
                var p = j < g.products_in.length ? g.products_in[j] : null;
                bodyHtml += '<td style="color:#28a745;' + tdStyleWidth + '">' + _renderProduct(p) + '</td>';
            });
            bodyHtml += '</tr>';
        }

        bodyHtml += '<tr style="border-top:2px solid #e5e7eb;"><td colspan="' + (groups.length + 1) + '" style="font-weight:600;color:#d40000;padding-top:8px;">📤 退出（相对于上一时点）</td></tr>';
        var maxOut = Math.max.apply(null, groups.map(function(g) { return g.products_out.length; }));
        for (var k = 0; k < Math.max(maxOut, 1); k++) {
            bodyHtml += '<tr>';
            bodyHtml += '<td style="color:#888;font-size:11px;"></td>';
            groups.forEach(function(g) {
                var p = k < g.products_out.length ? g.products_out[k] : null;
                bodyHtml += '<td style="color:#d40000;' + tdStyleWidth + '">' + _renderProduct(p) + '</td>';
            });
            bodyHtml += '</tr>';
        }

        document.getElementById('snapshot_body').innerHTML = bodyHtml;

        var totalChanged = 0, totalCount = 0;
        groups.forEach(function(g) {
            totalChanged += g.products_in.length + g.products_out.length;
            totalCount += g.count;
        });
        var avgTurnover = totalCount > 0 ? (totalChanged / (2.0 * totalCount) * 100).toFixed(1) : '0.0';

        var statsHtml = '<b>总体流动统计：</b>';
        statsHtml += '全组换手率 ≈ ' + avgTurnover + '% &nbsp;|&nbsp;';
        statsHtml += '总进出品种数 = ' + totalChanged;
        if (!data.has_prev) {
            statsHtml += ' &nbsp;<span style="color:#888;">（无上一时点数据，无法计算进出）</span>';
        }
        document.getElementById('snapshot_flow_stats').innerHTML = statsHtml;
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
