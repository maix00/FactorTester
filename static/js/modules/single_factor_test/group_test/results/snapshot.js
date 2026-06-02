/**
 * Group snapshot drawer — "图上每个分组的每期每组产品信息"
 *
 * 点击图表上任一时间点时，展示该时刻所有分组（可见的图线上各组）
 * 的完整产品持仓。每张分组卡片独立展示，方便对比各组的品种组成。
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
        var sel = _selection();
        return sel && typeof sel.getFirstSubmissionId === 'function' ? sel.getFirstSubmissionId() : null;
    }

    function _escape(value) {
        return GT.escapeHTML ? GT.escapeHTML(value) : String(value == null ? '' : value);
    }

    // ---------- 获取并展示分组快照 ----------
    function fetchGroupSnapshot(timestampMs) {
        var submissionId = _activeSubmissionId();
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
                document.getElementById('snapshot_body').innerHTML = '<div style="padding:20px;color:#d40000;">' + data.error + '</div>';
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

    // ──────────── 渲染函数 ────────────

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

    /**
     * 构建产品→分组归属矩阵，返回 { allProducts, maxRows }。
     * allProducts 是按出现顺序去重的产品名列表。
     */
    function _buildProductMatrix(groups) {
        var seen = {};
        var allProducts = [];
        groups.forEach(function(g) {
            (g.products || []).forEach(function(p) {
                var key = (typeof p === 'string') ? p : p.name;
                if (!seen[key]) {
                    seen[key] = true;
                    allProducts.push(key);
                }
            });
        });
        return allProducts;
    }

    /**
     * 判断产品在组中的状态
     * @returns {string} 'holding' | 'entering' | 'exiting' | 'pending_exit' | null
     *
     * pending_exit: 产品在该组中但被标记为"预备卖出"（因流动性不足被迫持仓）。
     *               该标记由后端在产品对象上设置 pending_exit: true。
     */
    function _productStatusInGroup(productName, group) {
        var inList = (group.products_in || []).map(function(p) { return (typeof p === 'string') ? p : p.name; });
        var outList = (group.products_out || []).map(function(p) { return (typeof p === 'string') ? p : p.name; });
        var holdingList = (group.products || []).map(function(p) { return (typeof p === 'string') ? p : p.name; });

        if (inList.indexOf(productName) !== -1) return 'entering';

        // 检查是否预备卖出（后端将来在 products 中设 pending_exit: true）
        var prodObj = _findProductObj(productName, group);
        if (typeof prodObj === 'object' && prodObj && prodObj.pending_exit) {
            return 'pending_exit';
        }

        if (outList.indexOf(productName) !== -1) return 'exiting';
        if (holdingList.indexOf(productName) !== -1) return 'holding';
        return null;
    }

    /**
     * 查找产品对象（可能为 string 或 {name,desc,fee}）
     */
    function _findProductObj(productName, group) {
        var prods = group.products || [];
        for (var i = 0; i < prods.length; i++) {
            var name = (typeof prods[i] === 'string') ? prods[i] : prods[i].name;
            if (name === productName) return prods[i];
        }
        return productName;
    }

    /** 渲染单个产品标签（带费率、描述和持仓金额） */
    function _renderProduct(p) {
        if (!p) return '';
        if (typeof p === 'string') return _escape(p);
        var name = _escape(p.name);
        var desc = '';
        if (p.desc && p.desc !== p.name) {
            desc = ' <span class="snapshot-product-desc">' +
                _escape(p.desc) + '</span>';
        }
        var feeHtml = '';
        if (p.fee) {
            var fee = p.fee;
            var parts = [];
            if (fee.open_ratio !== undefined) parts.push('开' + (fee.open_ratio * 100).toFixed(3) + '%');
            if (fee.close_ratio !== undefined) parts.push('平' + (fee.close_ratio * 100).toFixed(3) + '%');
            if (parts.length) feeHtml = ' <span class="snapshot-product-fee">[' + parts.join(' ') + ']</span>';
        }
        // 持仓金额 (refs #100)
        var amtHtml = '';
        if (p.amount !== null && p.amount !== undefined) {
            var amtStr = p.amount >= 1 ? p.amount.toFixed(2) : p.amount.toFixed(6);
            amtHtml = ' <span class="snapshot-product-amount" title="持仓金额">' + amtStr + '</span>';
        }
        return '<span class="snapshot-product-name" title="' + name + '">' + name + desc + feeHtml + '</span>' + amtHtml;
    }

    /**
     * 渲染分组持仓快照（表格形式）。
     *
     * 行 = 所有去重产品，列 = 分组。
     * 每个单元格用颜色和符号标注状态：
     *   - 持仓：正常文字
     *   - 新进：绿色 + + 前缀
     *   - 退出：红色 + - 前缀
     *   - 预备卖出：橙色 + ◷ 前缀（因流动性不足被迫持仓，后端标记 pending_exit）
     *   - 无该产品：灰色 —
     *
     * 不再分独立的"持仓段/新进段/退出段"（#98 设计变更）。
     */
    function renderGroupSnapshot(data, timestampMs) {
        if (!data || !data.groups) return;

        var timeStr = _fmtTs(timestampMs);
        document.getElementById('snapshot_title').innerHTML = '📋 分组持仓快照 — ' + timeStr;

        var groups = data.groups || [];
        var bodyEl = document.getElementById('snapshot_body');
        var statsEl = document.getElementById('snapshot_flow_stats');
        if (!bodyEl) return;

        var allProducts = _buildProductMatrix(groups);

        // —— 表头 —
        var headHtml = '<thead><tr><th style="min-width:80px;">产品</th>';
        groups.forEach(function(g) {
            headHtml += '<th>' + _escape(g.name)
                + ' <span style="font-weight:normal;color:#888;font-size:11px;">(' + g.count + ')</span></th>';
        });
        headHtml += '</tr></thead>';

        // —— 表体 —
        var bodyHtml = '<tbody>';
        allProducts.forEach(function(prodName) {
            bodyHtml += '<tr>';
            bodyHtml += '<td class="snapshot-prod-name-cell">' + _escape(prodName) + '</td>';
            groups.forEach(function(g) {
                var status = _productStatusInGroup(prodName, g);
                var cellContent;
                var cellClass = 'snapshot-cell-';

                if (status === 'entering') {
                    var p = _findProductObj(prodName, g);
                    cellContent = _renderProduct(p);
                    cellClass += 'entering';
                } else if (status === 'pending_exit') {
                    var p = _findProductObj(prodName, g);
                    cellContent = _renderProduct(p);
                    cellClass += 'pending-exit';
                } else if (status === 'exiting') {
                    cellContent = prodName;
                    cellClass += 'exiting';
                } else if (status === 'holding') {
                    var p = _findProductObj(prodName, g);
                    cellContent = _renderProduct(p);
                    cellClass += 'holding';
                } else {
                    cellContent = '—';
                    cellClass += 'absent';
                }
                bodyHtml += '<td class="' + cellClass + '">' + cellContent + '</td>';
            });
            bodyHtml += '</tr>';
        });
        bodyHtml += '</tbody>';

        bodyEl.innerHTML = '<table class="snapshot-matrix-table">' + headHtml + bodyHtml + '</table>';

        // —— 总体统计 —
        var totalChanged = 0, totalProdCount = 0;
        groups.forEach(function(g) {
            totalChanged += (g.products_in || []).length + (g.products_out || []).length;
            totalProdCount += g.count;
        });
        var avgTurnover = totalProdCount > 0 ? (totalChanged / (2.0 * totalProdCount) * 100).toFixed(1) : '0.0';
        if (statsEl) {
            var statsHtml = '<b>📊 总体流动统计：</b> 换手率 ≈ ' + avgTurnover + '%';
            statsHtml += ' &nbsp;|&nbsp; 总进出 = ' + totalChanged + ' 品种';
            if (!data.has_prev) {
                statsHtml += ' &nbsp;<span style="color:#888;">（首期，无对比基准）</span>';
            }
            statsEl.innerHTML = statsHtml;
        }
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
