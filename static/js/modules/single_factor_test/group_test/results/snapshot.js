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

            // ── 构建 group index → meta 的映射 (refs #100) ──
            var groupMetaMap = _buildGroupMetaMap(data);

            try {
                renderGroupSnapshot(data, data.timestamp_ms, groupMetaMap);
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
     * 构建 group_index → group meta 的映射 (refs #100)。
     * 返回：{ batchMap: {idx: addBatch}, aliasMap: {idx: shortAlias}, groupMeta: {idx: {addBatch, shortAlias, parentId, isDerived}} }
     */
    function _buildGroupMetaMap(snapshotData) {
        var groupNames = snapshotData.group_names || {};
        var frontendGroups = GT.groupSettings && GT.groupSettings.groups ? GT.groupSettings.groups.getAll() : [];

        // frontend shortAlias → group item
        var aliasToItem = {};
        frontendGroups.forEach(function(g) {
            if (g.shortAlias) aliasToItem[g.shortAlias] = g;
        });

        var batchMap = {};
        var aliasMap = {};
        var groupMeta = {};

        for (var idxStr in groupNames) {
            if (!groupNames.hasOwnProperty(idxStr)) continue;
            var idx = parseInt(idxStr, 10);
            var alias = groupNames[idxStr];
            var item = aliasToItem[alias];
            aliasMap[idx] = alias;

            if (item) {
                batchMap[idx] = item.addBatch;
                groupMeta[idx] = {
                    addBatch: item.addBatch,
                    shortAlias: item.shortAlias || alias,
                    parentId: item.parentId || null,
                    baseGroupId: item.baseGroupId || null,
                    isDerived: !!item.isDerived,
                    id: item.id || null
                };
            } else {
                groupMeta[idx] = {
                    addBatch: undefined,
                    shortAlias: alias,
                    parentId: null,
                    baseGroupId: null,
                    isDerived: false,
                    id: null
                };
            }
        }

        console.log('[snapshot-debug] _buildGroupMetaMap:', {
            groupNames: groupNames,
            n_base: snapshotData.n_base,
            n_derived: snapshotData.n_derived,
            derived_info: snapshotData.derived_info,
            frontendAliases: Object.keys(aliasToItem),
            groupMeta: groupMeta,
            batchMap: batchMap
        });

        return { batchMap: batchMap, aliasMap: aliasMap, groupMeta: groupMeta };
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

    /**
     * 收集 groupList 中所有 distinct 产品名称，按出现顺序。
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

    // ──────────── 按 addBatch + 派生树 渲染 (refs #100) ────────────

    /**
     * 构建派生组森林。
     * derivedIndices 是 base 组中 derived 组的索引。
     * groupMeta[idx].parentId 是前端 group id (UUID)，.id 需要从 groupMeta 中获取。
     * 返回：{ trees: [{root: idx, indices: [idx,...]}], nodeToRoot: {idx: rootIdx} }
     */
    function _buildDerivedForest(derivedIndices, groupMeta) {
        // 构建 idx → {id, parentId, baseGroupId}
        var idxToId = {};
        var idxToParentId = {};
        var idxToBaseGroupId = {};
        derivedIndices.forEach(function(idx) {
            var meta = groupMeta[idx];
            if (meta) {
                idxToId[idx] = meta.id || null;
                idxToParentId[idx] = meta.parentId || null;
                idxToBaseGroupId[idx] = meta.baseGroupId || null;
            }
        });

        // 收集所有出现的 id
        var idSet = {};
        derivedIndices.forEach(function(idx) {
            var id = idxToId[idx];
            if (id) idSet[id] = idx; // id → idx
        });

        // parentId → children idx
        var children = {};
        derivedIndices.forEach(function(idx) {
            var parentId = idxToParentId[idx];
            if (parentId) {
                if (!children[parentId]) children[parentId] = [];
                children[parentId].push(idx);
            }
        });

        // 找 roots：parentId 不在 idSet 中（即 parent 不在 derivedIndices 中）
        var roots = [];
        derivedIndices.forEach(function(idx) {
            var parentId = idxToParentId[idx];
            if (!parentId || !idSet.hasOwnProperty(parentId)) {
                roots.push(idx);
            }
        });

        // 构建 baseGroupId → 基础组 idx 的映射
        var baseGroupIdToIdx = {};
        for (var key in groupMeta) {
            if (!groupMeta.hasOwnProperty(key)) continue;
            var kmeta = groupMeta[key];
            if (!kmeta.isDerived && kmeta.id) {
                baseGroupIdToIdx[kmeta.id] = parseInt(key, 10);
            }
        }

        // BFS 收集每棵树，计算 anchorIndex
        var nodeToRoot = {};
        var trees = [];
        roots.forEach(function(root) {
            var tree = [];
            var queue = [root];
            while (queue.length > 0) {
                var node = queue.shift();
                tree.push(node);
                nodeToRoot[node] = root;
                var kids = children[idxToId[node]] || [];
                kids.forEach(function(k) { queue.push(k); });
            }
            // anchorIndex: 该树挂载到的基础组 index
            var anchorIndex = null;
            var rootBaseGroupId = idxToBaseGroupId[root];
            if (rootBaseGroupId && baseGroupIdToIdx.hasOwnProperty(rootBaseGroupId)) {
                anchorIndex = baseGroupIdToIdx[rootBaseGroupId];
            }
            trees.push({ root: root, indices: tree, anchorIndex: anchorIndex });
        });

        return { trees: trees, nodeToRoot: nodeToRoot };
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
            html += '<th>' + _escape(cg.label)
                + ' <span style="font-weight:normal;color:#888;font-size:11px;">(' + cg.group.count + ')</span></th>';
        });
        html += '</tr></thead><tbody>';

        allProducts.forEach(function(prodName) {
            html += '<tr>';
            html += '<td class="snapshot-prod-name-cell">' + _escape(prodName) + '</td>';
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
                    cellContent = prodName;
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
     * 构建 section label：从组列表中提取共同前缀。
     */
    function _sectionLabel(colGroups) {
        var aliases = colGroups.map(function(cg) { return cg.label; });
        if (aliases.length === 0) return 'Batch (未知)';

        var prefix = aliases[0];
        for (var i = 1; i < aliases.length; i++) {
            var a = aliases[i];
            var j = 0;
            while (j < prefix.length && j < a.length && prefix[j] === a[j]) j++;
            prefix = prefix.substring(0, j);
        }
        prefix = prefix.replace(/[\d_\-]+$/, '');
        if (!prefix) prefix = 'Batch';

        var n = aliases.length;
        if (n === 1) return prefix + ' (' + aliases[0] + ')';
        return prefix + ' (' + aliases[0] + '...' + aliases[n-1] + ', ' + n + '组)';
    }

    /**
     * 渲染仓位矩阵 tab（addBatch 矩阵 + 派生树矩阵）。
     *
     * 规则：
     *  - 相同 addBatch 且非派生的普通组 → 一个矩阵
     *  - 相同的 addBatch，如果有派生树，每个派生树一个额外矩阵，紧接在对应根组的 addBatch 矩阵下方
     *  - LS (long_short) 组仍放在 LS tab
     */
    function _renderBasicTab(groups, nBase, groupMeta) {
        // ── 分类：普通组 vs 派生组（排除 LS 的派生组） ──
        var normalIndices = [];   // 非派生、非 LS
        var derivedIndices = [];  // 派生（非 LS）

        for (var i = 0; i < groups.length; i++) {
            var meta = groupMeta[i];
            if (!meta) {
                normalIndices.push(i);
                continue;
            }
            if (meta.isDerived) {
                derivedIndices.push(i);
            } else {
                normalIndices.push(i);
            }
        }

        // ── 派生森林 ──
        var forest = _buildDerivedForest(derivedIndices, groupMeta);

        // ── 普通组按 addBatch 分组 ──
        var batchBuckets = {};    // addBatch → [idx]
        var batchOrder = [];
        normalIndices.forEach(function(idx) {
            var meta = groupMeta[idx];
            var b = (meta && meta.addBatch !== undefined) ? meta.addBatch : null;
            if (!batchBuckets.hasOwnProperty(b)) {
                batchBuckets[b] = [];
                batchOrder.push(b);
            }
            batchBuckets[b].push(idx);
        });

        // 构建 idx → colGroup
        function idxToCol(idx) {
            return {
                group: groups[idx],
                label: (groupMeta[idx] && groupMeta[idx].shortAlias) || groups[idx].name
            };
        }

        // ── 按 addBatch 顺序渲染 ──
        var html = '';
        batchOrder.forEach(function(b) {
            var batchIndices = batchBuckets[b];

            // 1. 该 addBatch 的普通组矩阵
            var colGroups = batchIndices.map(idxToCol);
            var allProds = _batchProducts(colGroups.map(function(cg) { return cg.group; }));
            var label = _sectionLabel(colGroups);
            html += _renderMatrixTable(colGroups, allProds, label);

            // 2. 该 addBatch 的派生树矩阵（挂在根组对应的基础组所在的 addBatch 下）
            var seenAnchor = {};
            batchIndices.forEach(function(idx) {
                forest.trees.forEach(function(tree) {
                    // anchorIndex 是基础组的 idx
                    if (tree.anchorIndex === idx && !seenAnchor[idx]) {
                        seenAnchor[idx] = true;
                        // 矩阵列：基础组 + 所有派生组
                        var allColIndices = [idx].concat(tree.indices);
                        var treeCols = allColIndices.map(idxToCol);
                        var treeProds = _batchProducts(treeCols.map(function(cg) { return cg.group; }));
                        var treeLabel = '↳ ' + _sectionLabel(treeCols) + ' (派生)';
                        html += _renderMatrixTable(treeCols, treeProds, treeLabel);
                    }
                });
            });
        });

        // 3. 没有挂在任何 batch 下的派生树（anchorIndex 不在任何 batch 中）
        var allBatchIndices = {};
        batchOrder.forEach(function(b) {
            (batchBuckets[b] || []).forEach(function(idx) { allBatchIndices[idx] = true; });
        });
        var orphanTrees = [];
        forest.trees.forEach(function(tree) {
            if (tree.anchorIndex == null || !allBatchIndices[tree.anchorIndex]) {
                orphanTrees.push(tree);
            }
        });
        if (orphanTrees.length > 0) {
            orphanTrees.forEach(function(tree) {
                var allColIndices = tree.anchorIndex != null ? [tree.anchorIndex].concat(tree.indices) : tree.indices;
                var treeCols = allColIndices.map(idxToCol);
                var treeProds = _batchProducts(treeCols.map(function(cg) { return cg.group; }));
                var treeLabel = _sectionLabel(treeCols) + ' (派生)';
                html += _renderMatrixTable(treeCols, treeProds, treeLabel);
            });
        }

        if (!html) html = '<div class="snapshot-empty-tab">暂无分组数据</div>';
        return html;
    }

    // ──────────── LS (多空) 渲染 ────────────

    /**
     * 渲染 LS tab 内容。
     */
    function _renderLSTab(groups, derivedInfo) {
        if (!derivedInfo || derivedInfo.length === 0) {
            return '<div class="snapshot-empty-tab">暂无 LS (多空) 组合数据</div>';
        }

        // 过滤 derived info 中后端的 LS 组（它们没在 base groups 里）
        // LS 的组在 groups[nBase:] 之后
        var nBase = groups.length - (derivedInfo ? derivedInfo.length : 0);
        if (nBase < 0) nBase = 0;

        var html = '';
        derivedInfo.forEach(function(info) {
            if (info.type !== 'long_short') return;

            var longIdx = info.long_group_idx;
            var shortIdx = info.short_group_idx;
            // LS group 的索引是后端内部的 group_idx，需要映射到 groups 数组
            var longGroup = (longIdx != null && longIdx < groups.length) ? groups[longIdx] : null;
            var shortGroup = (shortIdx != null && shortIdx < groups.length) ? groups[shortIdx] : null;

            if (!longGroup && !shortGroup) return;

            var label = 'LS: ' + (info.long_group_name || ('Group ' + (longIdx + 1)))
                + ' / ' + (info.short_group_name || ('Group ' + (shortIdx + 1)));

            var colGroups = [];
            if (longGroup) colGroups.push({ group: longGroup, label: (info.long_group_name || ('Group ' + (longIdx + 1))) + ' (L)' });
            if (shortGroup) colGroups.push({ group: shortGroup, label: (info.short_group_name || ('Group ' + (shortIdx + 1))) + ' (S)' });

            var allProds = _batchProducts(colGroups.map(function(cg) { return cg.group; }));

            html += '<div class="snapshot-batch-section snapshot-ls-section">';
            html += '<div class="snapshot-batch-header snapshot-ls-header">' + _escape(label) + '</div>';
            html += '<table class="snapshot-matrix-table"><thead><tr>';
            html += '<th style="min-width:80px;">产品</th>';
            colGroups.forEach(function(cg) {
                html += '<th>' + _escape(cg.label)
                    + ' <span style="font-weight:normal;color:#888;font-size:11px;">(' + cg.group.count + ')</span></th>';
            });
            html += '</tr></thead><tbody>';

            allProds.forEach(function(prodName) {
                html += '<tr>';
                html += '<td class="snapshot-prod-name-cell">' + _escape(prodName) + '</td>';
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
                        cellContent = prodName;
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
        });

        return html;
    }

    /**
     * 渲染分组持仓快照（addBatch 行布局 + LS tab）(refs #100)。
     *
     * Tab "仓位矩阵": 相同 addBatch 的普通组 → 矩阵；派生树 → 额外矩阵挂在根组下方。
     * Tab "多空(LS)": 每个 LS pair → 矩阵。
     */
    function renderGroupSnapshot(data, timestampMs, groupMetaMap) {
        if (!data || !data.groups) return;

        var timeStr = _fmtTs(timestampMs);
        document.getElementById('snapshot_title').innerHTML = '📋 分组持仓快照 — ' + timeStr;

        var groups = data.groups || [];
        var bodyEl = document.getElementById('snapshot_body');
        var statsEl = document.getElementById('snapshot_flow_stats');
        var tabsEl = document.getElementById('snapshot-tabs');
        if (!bodyEl) return;

        groupMetaMap = groupMetaMap || {};
        var groupMeta = groupMetaMap.groupMeta || {};
        var groupNames = data.group_names || {};
        var derivedInfo = data.derived_info || [];
        var nBase = data.n_base || groups.length;

        // ── 渲染 Tab: 仓位矩阵 ──
        var basicHtml = _renderBasicTab(groups, nBase, groupMeta);

        // ── 渲染 Tab: LS (多空) ──
        var lsHtml = _renderLSTab(groups, derivedInfo);

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
