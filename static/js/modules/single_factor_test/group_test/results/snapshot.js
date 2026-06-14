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
        console.log('[snapshot-debug] fetchGroupSnapshot called: timestampMs=', timestampMs, 'submissionId=', submissionId);
        if (!submissionId) {
            console.warn('[snapshot-debug] No active submissionId — drawer will not open. Please select a submission first.');
            alert('请先在提交列表中选中一条提交记录，再点击图表查看持仓快照。');
            return;
        }

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
        console.log('[snapshot-debug] openSnapshotDrawer called: overlay=', !!overlay, 'hasOpenClass=', overlay ? overlay.classList.contains('open') : null);
        if (overlay) overlay.classList.add('open');
        if (overlay) console.log('[snapshot-debug] after add: hasOpenClass=', overlay.classList.contains('open'));
    }

    function closeSnapshotDrawer() {
        var overlay = document.getElementById('group-snapshot-drawer');
        if (overlay) overlay.classList.remove('open');
    }

    /** 绑定快照抽屉事件（关闭按钮 + 遮罩点击 + 前/后导航） */
    function bindSnapshotDrawerEvents() {
        console.log('[snapshot-debug] bindSnapshotDrawerEvents called');
        var overlay = document.getElementById('group-snapshot-drawer');
        var closeBtn = document.getElementById('group-snapshot-drawer-close');
        var prevBtn = document.getElementById('snapshot-prev-btn');
        var nextBtn = document.getElementById('snapshot-next-btn');
        console.log('[snapshot-debug] elements: overlay=', !!overlay, 'closeBtn=', !!closeBtn, 'prevBtn=', !!prevBtn, 'nextBtn=', !!nextBtn);
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

    /** 收集所有组的全部产品（去重），返回 [{name, desc, ...}] */
    function _batchProducts(groupList) {
        var seen = {};
        var prods = [];
        groupList.forEach(function(g) {
            (g.products || []).forEach(function(p) {
                var key = (typeof p === 'string') ? p : p.name;
                if (!seen[key]) {
                    seen[key] = true;
                    prods.push((typeof p === 'string') ? {name: p, desc: p} : p);
                }
            });
        });
        return prods;
    }

    /**
     * 判断产品在组中的状态
     * @returns {string} 'holding' | 'entering' | 'exiting' | 'pending_exit' | null
     */
    function _productStatusInGroup(productName, group) {
        var inList = (group.products_in || []).map(function(p) { return (typeof p === 'string') ? p : p.name; });
        var outList = (group.products_out || []).map(function(p) { return (typeof p === 'string') ? p : p.name; });
        var holdingList = (group.products || []).map(function(p) { return (typeof p === 'string') ? p : p.name; });

        if (inList.indexOf(productName) !== -1) return 'entering';

        var prodObj = _findProductObj(productName, group);
        if (typeof prodObj === 'object' && prodObj && prodObj.pending_exit) {
            return 'pending_exit';
        }

        if (outList.indexOf(productName) !== -1) return 'exiting';
        if (holdingList.indexOf(productName) !== -1) return 'holding';
        return null;
    }

    /**
     * 查找产品对象（可能为 string 或 {name,desc,fee,amount}）
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
        var amtHtml = '';
        if (p.amount !== null && p.amount !== undefined) {
            var amtStr = p.amount >= 1 ? p.amount.toFixed(2) : p.amount.toFixed(6);
            amtHtml = ' <span class="snapshot-product-amount" title="持仓金额">' + amtStr + '</span>';
        }
        return '<span class="snapshot-product-name" title="' + name + '">' + name + desc + feeHtml + '</span>' + amtHtml;
    }

    /**
     * 渲染一个矩阵 table。
     * colGroups: [{group, label}] — label 用于表头显示（shortAlias）。
     */
    function _renderMatrixTable(colGroups, allProducts, sectionLabel) {
        var html = '';
        html += '<div class="snapshot-batch-section">';
        html += '<div class="snapshot-batch-header">' + _escape(sectionLabel) + '</div>';
        html += '<table class="snapshot-matrix-table"><thead><tr>';
        html += '<th style="min-width:80px;">产品</th>';
        colGroups.forEach(function(cg) {
            var labelHtml = cg.labelHtml || _escape(cg.label);
            html += '<th>' + labelHtml
                + ' <span style="font-weight:normal;color:#888;font-size:11px;">(' + cg.group.count + ')</span></th>';
        });
        html += '</tr></thead><tbody>';

        allProducts.forEach(function(prodObj) {
            var prodName = (typeof prodObj === 'string') ? prodObj : prodObj.name;
            html += '<tr>';
            html += '<td class="snapshot-prod-name-cell">' + _renderProduct(prodObj) + '</td>';
            colGroups.forEach(function(cg) {
                var status = _productStatusInGroup(prodName, cg.group);
                var cellContent;
                var cellClass = 'snapshot-cell-';

                if (status === 'entering') {
                    cellContent = _renderProduct(_findProductObj(prodName, cg.group));
                    cellClass += 'entering';
                } else if (status === 'pending_exit') {
                    cellContent = _renderProduct(_findProductObj(prodName, cg.group));
                    cellClass += 'pending-exit';
                } else if (status === 'exiting') {
                    cellContent = _renderProduct(prodObj);
                    cellClass += 'exiting';
                } else if (status === 'holding') {
                    cellContent = _renderProduct(_findProductObj(prodName, cg.group));
                    cellClass += 'holding';
                } else {
                    cellContent = '—';
                    cellClass += 'absent';
                }
                html += '<td class="' + cellClass + '">' + cellContent + '</td>';
            });
            html += '</tr>';
        });

        html += '</tbody></table></div>';
        return html;
    }

    /**
     * 渲染分组持仓快照。当前只保留一个矩阵链路：
     * 当前按列表展开态决定展示哪些列，前端直接按列生成单一矩阵。
     */
    function renderGroupSnapshot(data, timestampMs) {
        if (!data || !data.groups) return;

        var timeStr = _fmtTs(timestampMs);
        document.getElementById('snapshot_title').innerHTML = '📋 分组持仓快照 — ' + timeStr;

        var groups = Array.isArray(data.groups) ? data.groups : [];
        var bodyEl = document.getElementById('snapshot_body');
        var statsEl = document.getElementById('snapshot_flow_stats');
        if (!bodyEl) return;
        if (groups.length === 0) {
            bodyEl.innerHTML = '<div class="snapshot-empty-tab">暂无分组数据</div>';
            if (statsEl) statsEl.innerHTML = '';
            return;
        }

        var layout = null;
        var listIndex = GT.panels && GT.panels.list && GT.panels.list.index;
        if (listIndex && typeof listIndex.getSnapshotMatrixColumns === 'function') {
            try {
                layout = listIndex.getSnapshotMatrixColumns() || [];
            } catch (e) {
                console.warn('[snapshot] getSnapshotMatrixColumns failed, fallback to raw groups:', e);
            }
        }
        if (layout == null) {
            layout = groups.map(function(group, index) {
                return {
                    sourceIndex: index,
                    group: group,
                    depth: 0,
                    hasChildren: false,
                    expanded: true,
                    label: group.shortAlias || group.name || group.key || ('Group ' + (index + 1)),
                };
            });
        }

        if (!layout.length) {
            bodyEl.innerHTML = '<div class="snapshot-empty-tab">暂无分组数据</div>';
            if (statsEl) statsEl.innerHTML = '';
            return;
        }

        var colGroups = layout.map(function(entry, index) {
            var sourceIndex = (entry.sourceIndex != null) ? entry.sourceIndex : index;
            var group = groups[sourceIndex] || entry.group || groups[index];
            var label = entry.label || (group && (group.shortAlias || group.name || group.key)) || ('Group ' + (index + 1));
            var prefix = '';
            for (var i = 0; i < (entry.depth || 0); i++) prefix += '&nbsp;&nbsp;';
            var icon = entry.hasChildren ? (entry.expanded ? '▾' : '▸') + ' ' : '';
            return {
                group: group,
                label: label,
                labelHtml: '<span style="white-space:nowrap;">' + prefix + icon + _escape(label) + '</span>',
            };
        }).filter(function(cg) { return !!cg.group; });
        var allProducts = _batchProducts(colGroups.map(function(cg) { return cg.group; }));
        var matrixHtml = _renderMatrixTable(colGroups, allProducts, '仓位矩阵');
        bodyEl.innerHTML = matrixHtml;

        // ── 总体统计 ──
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
