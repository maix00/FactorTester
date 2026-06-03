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

            // ── 构建 group index → addBatch 的映射 (refs #100) ──
            var addBatchMap = _buildAddBatchMap(data);

            try {
                renderGroupSnapshot(data, data.timestamp_ms, addBatchMap);
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

    /** 绑定快照抽屉事件（关闭按钮 + 遮罩点击 + 前/后导航 + tab 切换） */
    function bindSnapshotDrawerEvents() {
        console.log('[snapshot-debug] bindSnapshotDrawerEvents called');
        var overlay = document.getElementById('group-snapshot-drawer');
        var closeBtn = document.getElementById('group-snapshot-drawer-close');
        var prevBtn = document.getElementById('snapshot-prev-btn');
        var nextBtn = document.getElementById('snapshot-next-btn');
        var basicTabBtn = document.getElementById('snapshot-tab-basic');
        var lsTabBtn = document.getElementById('snapshot-tab-ls');
        console.log('[snapshot-debug] elements: overlay=', !!overlay, 'closeBtn=', !!closeBtn, 'prevBtn=', !!prevBtn, 'nextBtn=', !!nextBtn);
        if (closeBtn) closeBtn.addEventListener('click', closeSnapshotDrawer);
        if (prevBtn) prevBtn.addEventListener('click', function() { navigateSnapshot('prev'); });
        if (nextBtn) nextBtn.addEventListener('click', function() { navigateSnapshot('next'); });
        if (overlay) overlay.addEventListener('click', function(e) {
            if (e.target === overlay) closeSnapshotDrawer();
        });

        // ── Tab 切换 (refs #100) ──
        function switchTab(tab) {
            var bodyEl = document.getElementById('snapshot_body');
            if (!bodyEl) return;
            if (tab === 'ls') {
                bodyEl.innerHTML = bodyEl.getAttribute('data-tab-ls') || '<div class="snapshot-empty-tab">暂无 LS 数据</div>';
                if (basicTabBtn) { basicTabBtn.classList.remove('active'); basicTabBtn.classList.add('inactive'); }
                if (lsTabBtn) { lsTabBtn.classList.add('active'); lsTabBtn.classList.remove('inactive'); }
            } else {
                bodyEl.innerHTML = bodyEl.getAttribute('data-tab-basic') || '<div class="snapshot-empty-tab">暂无数据</div>';
                if (basicTabBtn) { basicTabBtn.classList.add('active'); basicTabBtn.classList.remove('inactive'); }
                if (lsTabBtn) { lsTabBtn.classList.remove('active'); lsTabBtn.classList.add('inactive'); }
            }
        }
        if (basicTabBtn) basicTabBtn.addEventListener('click', function() { switchTab('basic'); });
        if (lsTabBtn) lsTabBtn.addEventListener('click', function() { switchTab('ls'); });
    }

    // ──────────── 辅助函数 ────────────

    /**
     * 构建 group_index → addBatch 的映射 (refs #100)。
     * 后端返回 group_names: {group_index: shortAlias}，前端有 getAll() 提供 shortAlias→addBatch。
     */
    function _buildAddBatchMap(snapshotData) {
        var groupNames = snapshotData.group_names || {};
        var frontendGroups = GT.groupSettings && GT.groupSettings.groups ? GT.groupSettings.groups.getAll() : [];

        // frontend shortAlias → addBatch
        var aliasToBatch = {};
        frontendGroups.forEach(function(g) {
            if (g.shortAlias) aliasToBatch[g.shortAlias] = g.addBatch;
        });

        // group_index (0-based) → addBatch
        var result = {};
        for (var idxStr in groupNames) {
            if (!groupNames.hasOwnProperty(idxStr)) continue;
            var alias = groupNames[idxStr];
            var batch = aliasToBatch[alias];
            if (batch !== undefined) {
                result[parseInt(idxStr, 10)] = batch;
            }
        }
        return result;
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

    // ──────────── 按 addBatch 行渲染 (refs #100) ────────────

    /**
     * 将 groups 按 addBatch 分组：{batch: {groups: [...], indices: [...]}}
     * 没有 addBatch 的 group 归入 null batch。
     */
    function _groupByBatch(groups, addBatchMap) {
        var buckets = {};
        var order = [];
        groups.forEach(function(g, idx) {
            var batch = addBatchMap[idx];
            if (batch === undefined) batch = null;
            if (!buckets.hasOwnProperty(batch)) {
                buckets[batch] = { groups: [], indices: [] };
                order.push(batch);
            }
            buckets[batch].groups.push(g);
            buckets[batch].indices.push(idx);
        });
        return { buckets: buckets, order: order };
    }

    /**
     * 收集 batch 内所有 distinct 产品名称，按出现顺序。
     */
    function _batchProducts(groupList) {
        var seen = {};
        var prods = [];
        groupList.forEach(function(g) {
            (g.products || []).forEach(function(p) {
                var key = (typeof p === 'string') ? p : p.name;
                if (!seen[key]) {
                    seen[key] = true;
                    prods.push(key);
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
        var amtHtml = '';
        if (p.amount !== null && p.amount !== undefined) {
            var amtStr = p.amount >= 1 ? p.amount.toFixed(2) : p.amount.toFixed(6);
            amtHtml = ' <span class="snapshot-product-amount" title="持仓金额">' + amtStr + '</span>';
        }
        return '<span class="snapshot-product-name" title="' + name + '">' + name + desc + feeHtml + '</span>' + amtHtml;
    }

    /**
     * 渲染一个 batch（一个 table）。
     * batchLabel: 显示标签如 "Batch A1-A5"
     */
    function _renderBatchTable(batchGroups, allProducts, batchLabel) {
        var html = '';
        html += '<div class="snapshot-batch-section">';
        html += '<div class="snapshot-batch-header">' + _escape(batchLabel) + '</div>';

        // 表头
        html += '<table class="snapshot-matrix-table"><thead><tr>';
        html += '<th style="min-width:80px;">产品</th>';
        batchGroups.forEach(function(g) {
            html += '<th>' + _escape(g.name)
                + ' <span style="font-weight:normal;color:#888;font-size:11px;">(' + g.count + ')</span></th>';
        });
        html += '</tr></thead>';

        // 表体
        html += '<tbody>';
        allProducts.forEach(function(prodName) {
            html += '<tr>';
            html += '<td class="snapshot-prod-name-cell">' + _escape(prodName) + '</td>';
            batchGroups.forEach(function(g) {
                var status = _productStatusInGroup(prodName, g);
                var cellContent;
                var cellClass = 'snapshot-cell-';

                if (status === 'entering') {
                    cellContent = _renderProduct(_findProductObj(prodName, g));
                    cellClass += 'entering';
                } else if (status === 'pending_exit') {
                    cellContent = _renderProduct(_findProductObj(prodName, g));
                    cellClass += 'pending-exit';
                } else if (status === 'exiting') {
                    cellContent = prodName;
                    cellClass += 'exiting';
                } else if (status === 'holding') {
                    cellContent = _renderProduct(_findProductObj(prodName, g));
                    cellClass += 'holding';
                } else {
                    cellContent = '—';
                    cellClass += 'absent';
                }
                html += '<td class="' + cellClass + '">' + cellContent + '</td>';
            });
            html += '</tr>';
        });
        html += '</tbody></table>';
        html += '</div>';
        return html;
    }

    /**
     * 构建 batch label。
     * 用此 batch 中各组的 shortAlias 提取共同前缀。
     * groupNames: {group_index: shortAlias} from backend.
     * batchGroupIndices: 此 batch 中各 group 在 groups 数组中的原始索引。
     */
    function _batchLabel(batchGroupIndices, groupNames) {
        var aliases = [];
        batchGroupIndices.forEach(function(idx) {
            if (groupNames.hasOwnProperty(idx)) {
                aliases.push(groupNames[idx]);
            }
        });
        if (aliases.length === 0) return 'Batch (未知)';

        // 找共同前缀
        var prefix = aliases[0];
        for (var i = 1; i < aliases.length; i++) {
            var a = aliases[i];
            var j = 0;
            while (j < prefix.length && j < a.length && prefix[j] === a[j]) j++;
            prefix = prefix.substring(0, j);
        }
        // 去掉末尾数字残留
        prefix = prefix.replace(/[\d_\-]+$/, '');
        if (!prefix) prefix = 'Batch';

        // 加入第一个和最后一个 alias
        var n = aliases.length;
        if (n === 1) return prefix + ' (' + aliases[0] + ')';
        return prefix + ' (' + aliases[0] + '...' + aliases[n-1] + ', ' + n + '组)';
    }

    // ──────────── LS (多空) 渲染 ────────────

    /**
     * 渲染 LS tab 内容。
     * derived_info: [{type: 'long_short', long_group_name, short_group_name, group_idx, ...}, ...]
     * 每个 LS pair 渲染为一组：多头组 vs 空头组的并集产品矩阵。
     */
    function _renderLSTab(groups, addBatchMap, derivedInfo, groupNames) {
        if (!derivedInfo || derivedInfo.length === 0) {
            return '<div class="snapshot-empty-tab">暂无 LS (多空) 组合数据</div>';
        }

        var html = '';
        derivedInfo.forEach(function(info) {
            if (info.type !== 'long_short') return;

            var longIdx = info.long_group_idx;
            var shortIdx = info.short_group_idx;
            var longGroup = groups[longIdx];
            var shortGroup = groups[shortIdx];

            if (!longGroup && !shortGroup) return;

            // 构建 LS 对的标签
            var label = 'LS: ' + (info.long_group_name || ('Group ' + (longIdx + 1)))
                + ' / ' + (info.short_group_name || ('Group ' + (shortIdx + 1)));

            var pairGroups = [];
            if (longGroup) pairGroups.push({ g: longGroup, role: '多头 (L)' });
            if (shortGroup) pairGroups.push({ g: shortGroup, role: '空头 (S)' });

            // 收集并集产品
            var seen = {};
            var allProds = [];
            pairGroups.forEach(function(pg) {
                (pg.g.products || []).forEach(function(p) {
                    var key = (typeof p === 'string') ? p : p.name;
                    if (!seen[key]) {
                        seen[key] = true;
                        allProds.push(key);
                    }
                });
            });

            html += '<div class="snapshot-batch-section snapshot-ls-section">';
            html += '<div class="snapshot-batch-header snapshot-ls-header">' + _escape(label) + '</div>';
            html += '<table class="snapshot-matrix-table"><thead><tr>';
            html += '<th style="min-width:80px;">产品</th>';
            pairGroups.forEach(function(pg) {
                html += '<th>' + _escape(pg.g.name) + ' <span style="font-weight:normal;color:#888;font-size:11px;">(' + pg.g.count + ')</span> <span style="color:#666;font-size:10px;">' + pg.role + '</span></th>';
            });
            html += '</tr></thead><tbody>';

            allProds.forEach(function(prodName) {
                html += '<tr>';
                html += '<td class="snapshot-prod-name-cell">' + _escape(prodName) + '</td>';
                pairGroups.forEach(function(pg) {
                    var status = _productStatusInGroup(prodName, pg.g);
                    var cellContent;
                    var cellClass = 'snapshot-cell-';

                    if (status === 'entering') {
                        cellContent = _renderProduct(_findProductObj(prodName, pg.g));
                        cellClass += 'entering';
                    } else if (status === 'pending_exit') {
                        cellContent = _renderProduct(_findProductObj(prodName, pg.g));
                        cellClass += 'pending-exit';
                    } else if (status === 'exiting') {
                        cellContent = prodName;
                        cellClass += 'exiting';
                    } else if (status === 'holding') {
                        cellContent = _renderProduct(_findProductObj(prodName, pg.g));
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
        });

        return html;
    }

    /**
     * 渲染分组持仓快照（addBatch 行布局 + LS tab）(refs #100)。
     *
     * Tab "仓位矩阵": 每个 unique addBatch → 一行（table），列 = 该 batch 下的各组。
     * Tab "多空(LS)": 每个 LS pair → 一行（table），列 = 多头组 + 空头组。
     */
    function renderGroupSnapshot(data, timestampMs, addBatchMap) {
        if (!data || !data.groups) return;

        var timeStr = _fmtTs(timestampMs);
        document.getElementById('snapshot_title').innerHTML = '📋 分组持仓快照 — ' + timeStr;

        var groups = data.groups || [];
        var bodyEl = document.getElementById('snapshot_body');
        var statsEl = document.getElementById('snapshot_flow_stats');
        var tabsEl = document.getElementById('snapshot-tabs');
        if (!bodyEl) return;

        addBatchMap = addBatchMap || {};
        var groupNames = data.group_names || {};
        var derivedInfo = data.derived_info || [];
        var nBase = data.n_base || groups.length;
        var nDerived = data.n_derived || 0;

        // ── 分离 base 组和 derived (LS) 组 ──
        var baseGroups = groups.slice(0, nBase);
        var derivedGroups = groups.slice(nBase);

        // ── 按 addBatch 分组 base 组 ──
        var batch = _groupByBatch(baseGroups, addBatchMap);

        // ── 渲染 Tab: 仓位矩阵 (addBatch 行) ──
        var basicHtml = '';
        if (batch.order.length === 0) {
            basicHtml = '<div class="snapshot-empty-tab">暂无分组数据</div>';
        } else {
            batch.order.forEach(function(b) {
                var batchEntry = batch.buckets[b];
                var batchGroups = batchEntry.groups;
                var allProds = _batchProducts(batchGroups);
                var label = (b !== null) ? _batchLabel(batchEntry.indices, groupNames) : '未归类';
                basicHtml += _renderBatchTable(batchGroups, allProds, label);
            });
        }

        // ── 渲染 Tab: LS (多空) ──
        // 重建 addBatchMap for derived groups (使用 group index + nBase 偏移)
        var derivedAddBatchMap = {};
        derivedInfo.forEach(function(info, i) {
            // 在 groups 数组中的索引 = nBase + i
            derivedAddBatchMap[nBase + i] = i;
        });
        var lsHtml = _renderLSTab(groups, derivedAddBatchMap, derivedInfo, groupNames);

        // ── 存储 tab 内容，默认显示基本 tab ──
        bodyEl.setAttribute('data-tab-basic', basicHtml);
        bodyEl.setAttribute('data-tab-ls', lsHtml);
        bodyEl.innerHTML = basicHtml;

        // ── Tab 可见性 ──
        if (tabsEl) {
            var hasLS = derivedInfo.some(function(info) { return info.type === 'long_short'; });
            tabsEl.style.display = 'flex';
            var basicBtn = document.getElementById('snapshot-tab-basic');
            var lsBtn = document.getElementById('snapshot-tab-ls');
            if (basicBtn) {
                basicBtn.classList.add('active');
                basicBtn.classList.remove('inactive');
            }
            if (lsBtn) {
                lsBtn.style.display = hasLS ? '' : 'none';
                lsBtn.classList.remove('active');
                lsBtn.classList.add('inactive');
            }
        }

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
