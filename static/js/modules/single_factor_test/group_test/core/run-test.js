/**
 * core/run-test.js — 分组测试执行器
 *
 * 负责：
 *   - 运行分组测试（单次/批量/全因子）
 *   - 加载默认分组
 *   - 派生组生成/删除
 *   - 工具函数：postGroupTest, postBatchGroupTest, clearResults
 *
 * 挂载到 GT.core.runTest。
 */
(function(){
    var GT = window.GroupTest;
    if (!GT) { console.warn('[runner] GroupTest bootstrap missing'); return; }

    GT.core = GT.core || {};
    if (GT.core.runTest) { console.warn('[run-test] already loaded'); return; }

    var runTest = {};

    // ── 本地桥接引用 ──
    var resolveGroupRunTimeRange = GT.core.dates ? GT.core.dates.resolveGroupRunTimeRange : function() { return {startDate:null,endDate:null}; };
    var persistGroupTimeRangeToDatamodel = GT.core.dates ? GT.core.dates.persistGroupTimeRangeToDatamodel : function(){};

    function cache() {
        return GT.groupSettings && GT.groupSettings.cache ? GT.groupSettings.cache : null;
    }

    // ════════════════════════════════════════════════════════════════
    //  工具函数
    // ════════════════════════════════════════════════════════════════

    /**
     * 清空测试结果
     */
    runTest.clearResults = function(options) {
        options = options || {};
        var chartContainer = document.getElementById('group_chart_container');
        var metricsContainer = document.getElementById('group_metrics_container');
        if (chartContainer) chartContainer.style.display = 'none';
        if (metricsContainer) metricsContainer.style.display = 'none';
        if (GT.results && GT.results.snapshot && typeof GT.results.snapshot.closeSnapshotDrawer === 'function') {
            GT.results.snapshot.closeSnapshotDrawer();
        }
        if (options.clearStatus) {
            var status = document.getElementById('group_test_status');
            if (status) status.innerHTML = '';
        }
    };

// (updateStrategyPanel → results/strategy_panel.js, updateRebalanceModeDescription → panels/actions.js)

    // ════════════════════════════════════════════════════════════════
    //  API 调用
    // ════════════════════════════════════════════════════════════════

    /**
     * 单次分组测试 POST
     */
    runTest.postGroupTest = function(payload) {
        return fetch('/run_group_test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(function(res) { return res.json(); });
    };

    /**
     * 批量分组测试 POST（单次请求，后端并行计算）
     */
    runTest.postBatchGroupTest = function(payload) {
        return fetch('/run_group_test_batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(function(res) { return res.json(); });
    };

    // ════════════════════════════════════════════════════════════════
    //  加载默认分组
    // ════════════════════════════════════════════════════════════════

    runTest.loadDefaultGroups = async function() {
        var statusSpan = document.getElementById('group_test_status');
        var runBtn = document.getElementById('run_group_test_btn');
        var defaultBtn = document.getElementById('load_default_groups_btn');

        var submissions = window.submissions || [];
        var factorList = window.factorList || [];

        if (!submissions.length) {
            alert('暂无测试器，请先在产品类别筛选模块提交产品');
            return;
        }
        if (!factorList.length) {
            alert('暂无可用的因子列表，请先在 IC 测试模块运行 IC 测试');
            return;
        }

        if (!GT.groupSettings.groups || !GT.groupSettings.lsConfigs) {
            alert('数据模型未就绪，请刷新页面');
            return;
        }

        var groups = GT.groupSettings.groups;
        var lsConfigs = GT.groupSettings.lsConfigs;

        var existingBase = (groups.getAll() || []).filter(function(g) { return !g.isDerived; });
        var existingLS = lsConfigs.getAll() || [];

        if (existingBase.length > 0 || existingLS.length > 0) {
            var confirmMsg = '当前已有 ' + existingBase.length + ' 个基础组和 ' + existingLS.length + ' 个 LS 组。\n';
            confirmMsg += '加载默认分组将清空所有现有分组，确定继续？';
            if (!confirm(confirmMsg)) return;
        }

        (groups.getAll() || []).forEach(function(g) { groups.remove(g.id); });
        (lsConfigs.getAll() || []).forEach(function(ls) { lsConfigs.remove(ls.id); });

        if (defaultBtn) defaultBtn.disabled = true;
        if (runBtn) runBtn.disabled = true;
        if (statusSpan) {
            statusSpan.innerHTML = '正在加载默认分组...';
            statusSpan.style.color = '#0078d4';
        }

        var GROUPS_PER_FACTOR = 5;
        var totalCreated = 0;
        var batchLetterMap = {};
        var nextLetterCode = 65;

        try {
            for (var si = 0; si < submissions.length; si++) {
                var sub = submissions[si];
                var testerId = String(sub.id);
                for (var fi = 0; fi < factorList.length; fi++) {
                    var factor = factorList[fi];
                    var factorAlias = factor.alias || factor.name || '';

                    var bk = GT.groupSettings.groups.batchKey(testerId, factorAlias, GROUPS_PER_FACTOR);
                    var letter = batchLetterMap[bk];
                    if (!letter) {
                        letter = String.fromCharCode(nextLetterCode);
                        nextLetterCode++;
                        batchLetterMap[bk] = letter;
                    }

                    var createdIds = [];
                    for (var gi = 1; gi <= GROUPS_PER_FACTOR; gi++) {
                        try {
                            var id = groups.add({
                                name: factorAlias + ' · G' + gi + ' (' + (sub.product_group || sub.label || testerId) + ')',
                                testerId: testerId,
                                factorAlias: factorAlias,
                                groupCount: GROUPS_PER_FACTOR,
                                groupIndex: gi,
                                isAllGroups: false,
                                shortAlias: letter + gi,
                                feeMode: 'none',
                                useCloseToday: false,
                                rebalanceMode: 'each_period'
                            });
                            createdIds.push({ id: id, index: gi });
                        } catch (e) {
                            console.error('创建分组失败 (' + factorAlias + ' G' + gi + '):', e);
                        }
                    }

                    if (createdIds.length >= 5) {
                        var longItem = createdIds[0];
                        var shortItem = createdIds[4];
                        try {
                            lsConfigs.add({
                                name: factorAlias + ' · 多空',
                                longGroupId: longItem.id,
                                shortGroupId: shortItem.id
                            });
                        } catch (e) {
                            console.error('创建 LS 组失败 (' + factorAlias + '):', e);
                        }
                    }

                    totalCreated++;
                    if (statusSpan) {
                        statusSpan.innerHTML = '加载中... ' + totalCreated + ' 个因子分组';
                    }
                }
            }

            if (statusSpan) {
                var totalBase = (groups.getAll() || []).filter(function(g) { return !g.isDerived; }).length;
                var totalLS = (lsConfigs.getAll() || []).length;
                statusSpan.innerHTML = '✓ 已加载 ' + totalBase + ' 个基础组 + ' + totalLS + ' 个 LS 组';
                statusSpan.style.color = '#28a745';
            }

            if (GT.tabs && GT.tabs.mountTab) {
                GT.tabs.mountTab('list');
            }
        } catch (e) {
            console.error('加载默认分组失败:', e);
            if (statusSpan) {
                statusSpan.innerHTML = '✗ 加载失败: ' + (e.message || '未知错误');
                statusSpan.style.color = '#d40000';
            }
        } finally {
            if (defaultBtn) defaultBtn.disabled = false;
            if (runBtn) runBtn.disabled = false;
        }
    };

    // ════════════════════════════════════════════════════════════════
    //  运行分组测试（批量）
    // ════════════════════════════════════════════════════════════════

    runTest.runGroupTest = async function() {
        var statusSpan = document.getElementById('group_test_status');
        var runBtn = document.getElementById('run_group_test_btn');
        var defaultBtn = document.getElementById('load_default_groups_btn');

        var REG = window.GT_CONFIG_REGISTRY;
        if (REG && typeof REG.hasDirty === 'function' && REG.hasDirty() && typeof REG.commitDirty === 'function') {
            REG.commitDirty();
        }

        // ── 0. 没有分组则自动加载默认分组 ──
        var allBase = (GT.groupSettings.groups && GT.groupSettings.groups.getAll()) || [];
        var nonDerived = allBase.filter(function(g) { return !g.isDerived; });
        if (nonDerived.length === 0) {
            if (statusSpan) {
                statusSpan.innerHTML = '⏳ 无现有分组，正在加载默认分组...';
                statusSpan.style.color = '#0078d4';
            }
            await runTest.loadDefaultGroups();
            allBase = (GT.groupSettings.groups && GT.groupSettings.groups.getAll()) || [];
            nonDerived = allBase.filter(function(g) { return !g.isDerived; });
            if (nonDerived.length === 0) {
                if (statusSpan) {
                    statusSpan.innerHTML = '✗ 无法加载默认分组';
                    statusSpan.style.color = '#d40000';
                }
                return;
            }
        }

        // ── 1. 按 batchKey 分组 ──
        var batchKeyFn = GT.groupSettings.groups.batchKey;
        var batchMap = {};
        for (var i = 0; i < nonDerived.length; i++) {
            var g = nonDerived[i];
            var bk = batchKeyFn(g.testerId, g.factorAlias, g.groupCount);
            if (!batchMap[bk]) {
                batchMap[bk] = {
                    key: bk,
                    testerId: g.testerId,
                    factorAlias: g.factorAlias,
                    groupCount: g.groupCount,
                    groups: []
                };
            }
            batchMap[bk].groups.push(g);
        }
        var batches = [];
        var bkKeys = Object.keys(batchMap);
        bkKeys.sort(function(a, b) {
            var sa = (batchMap[a].groups[0].shortAlias || '');
            var sb = (batchMap[b].groups[0].shortAlias || '');
            if (sa < sb) return -1;
            if (sa > sb) return 1;
            return 0;
        });
        for (var k = 0; k < bkKeys.length; k++) { batches.push(batchMap[bkKeys[k]]); }

        // ── 2. 收集 LS configs ──
        var allLS = (GT.groupSettings.lsConfigs && GT.groupSettings.lsConfigs.getAll()) || [];
        for (var bi = 0; bi < batches.length; bi++) {
            var b = batches[bi];
            b.groupIdToIndex = {};
            var groupsByIndex = {};
            for (var gi = 0; gi < b.groups.length; gi++) {
                var originalIndex = Number(b.groups[gi].groupIndex || (gi + 1));
                if (!groupsByIndex[originalIndex]) groupsByIndex[originalIndex] = [];
                groupsByIndex[originalIndex].push(b.groups[gi]);
            }
            var expandedIndex = 1;
            for (var baseIdx = 1; baseIdx <= Number(b.groupCount || b.groups.length || 0); baseIdx++) {
                var variantsAtIndex = groupsByIndex[baseIdx] || [];
                for (var vi = 0; vi < variantsAtIndex.length; vi++) {
                    b.groupIdToIndex[variantsAtIndex[vi].id] = expandedIndex;
                    expandedIndex += 1;
                }
            }
            b.derivedPayload = (GT.core.collect && typeof GT.core.collect.collectDerivedPayloadForBatch === 'function')
                ? GT.core.collect.collectDerivedPayloadForBatch(b)
                : [];
            for (var di = 0; di < b.derivedPayload.length; di++) {
                if (b.derivedPayload[di].id) {
                    b.groupIdToIndex[b.derivedPayload[di].id] = expandedIndex;
                    expandedIndex += 1;
                }
            }
            b.lsPayloads = [];
        }
        var crossBatchLS = [];

        for (var li = 0; li < allLS.length; li++) {
            var ls = allLS[li];
            var longBatch = null, shortBatch = null;
            for (var bj = 0; bj < batches.length; bj++) {
                if (batches[bj].groupIdToIndex[ls.longGroupId] !== undefined) longBatch = batches[bj];
                if (batches[bj].groupIdToIndex[ls.shortGroupId] !== undefined) shortBatch = batches[bj];
            }
            if (!longBatch || !shortBatch) {
                console.warn('[runGroupTest] LS config ' + ls.id + ' references unknown group(s): long=' + ls.longGroupId + ' short=' + ls.shortGroupId);
                continue;
            }
            if (longBatch === shortBatch) {
                var longIdx = longBatch.groupIdToIndex[ls.longGroupId];
                var shortIdx = shortBatch.groupIdToIndex[ls.shortGroupId];
                var sameBatchName = GT.panels.actions ? GT.panels.actions.lsDisplayName(ls) : (ls.name || 'Long-Short');
                longBatch.lsPayloads.push({
                    name: sameBatchName,
                    key: sameBatchName,
                    long: [{ group: longIdx - 1, weight: 1.0 }],
                    short: [{ group: shortIdx - 1, weight: 1.0 }]
                });
            } else {
                crossBatchLS.push(ls);
            }
        }

        // ── 3. 构建批量 payload ──
        if (runBtn) runBtn.disabled = true;

        var totalBatches = batches.length + (crossBatchLS.length > 0 ? 1 : 0);

        var firstGroup = batches[0] && batches[0].groups[0];
        var firstTesterId = batches[0] && batches[0].testerId;
        var rebalance_mode = firstGroup ? (firstGroup.rebalanceMode || 'buy_and_hold') : 'buy_and_hold';
        var fallbackTesterId = firstTesterId || (firstGroup ? firstGroup.testerId : null);
        var resolvedRange = GT.core.dates && GT.core.dates.resolveGroupRunTimeRangeWithFallback
            ? GT.core.dates.resolveGroupRunTimeRangeWithFallback(
                firstGroup ? (firstGroup.startDate || null) : null,
                firstGroup ? (firstGroup.endDate || null) : null,
                fallbackTesterId
              )
            : resolveGroupRunTimeRange(
                firstGroup ? (firstGroup.startDate || null) : null,
                firstGroup ? (firstGroup.endDate || null) : null
              );
        var start_date = resolvedRange.startDate;
        var end_date = resolvedRange.endDate;
        persistGroupTimeRangeToDatamodel(resolvedRange.explicitStartDate, resolvedRange.explicitEndDate);

        if (!start_date || !end_date) {
            if (statusSpan) { statusSpan.innerHTML = '✗ 请设置时间范围'; statusSpan.style.color = '#d40000'; }
            if (runBtn) runBtn.disabled = false;
            return;
        }
        if (start_date > end_date) {
            if (statusSpan) { statusSpan.innerHTML = '✗ 起始日期不能晚于终止日期'; statusSpan.style.color = '#d40000'; }
            if (runBtn) runBtn.disabled = false;
            return;
        }

        // ── 费率聚合 ──
        var fee = 0;
        var fee_map = {};
        var hasPerProduct = false;
        if (GT.groupSettings.groups) {
            var allFeeGroups = GT.groupSettings.groups.getAll() || [];
            for (var fgi = 0; fgi < allFeeGroups.length; fgi++) {
                var fg = allFeeGroups[fgi];
                if (fg.isDerived) continue;
                if (fg.feeMode === 'per_product') hasPerProduct = true;
                if (fg.feeMode === 'uniform' && fee === 0) {
                    fee = fg.feeRate != null ? fg.feeRate : 0.0025;
                }
            }
        }
        if (hasPerProduct && GT.fee) {
            try {
                fee_map = await GT.fee.ensureFeeData();
            } catch (err) {
                console.error('[runBatch] ensureFeeData failed:', err);
            }
        }
        var use_closetoday = GT.fee ? GT.fee.useCloseToday() : false;
        if (statusSpan) {
            statusSpan.innerHTML = '分组测试运行中...（共 ' + totalBatches + ' 批次）';
            statusSpan.style.color = '#0078d4';
        }

        // ── 构建 batch payloads ──
        var batchPayloads = [];
        for (var bi = 0; bi < batches.length; bi++) {
            var batch = batches[bi];
            var groupNames = {};
            for (var gi = 0; gi < batch.groups.length; gi++) {
                var g = batch.groups[gi];
                var groupIdx = (g.groupIndex || (gi + 1)) - 1;
                var variant = GT.panels.actions ? GT.panels.actions.serializeGroupVariant(g, 'Group ' + (groupIdx + 1))
                    : (GT.groupSettings.groups.serializeVariant ? GT.groupSettings.groups.serializeVariant(g, 'Group ' + (groupIdx + 1)) : null);
                if (!variant) continue;
                if (!groupNames[groupIdx]) groupNames[groupIdx] = [];
                groupNames[groupIdx].push(variant);
            }
            var derivedPayload = batch.derivedPayload || [];
            batchPayloads.push({
                submission_id: batch.testerId,
                factor_alias: batch.factorAlias,
                n_groups: batch.groupCount,
                group_names: Object.keys(groupNames).length > 0 ? groupNames : null,
                ls_configs: batch.lsPayloads.length > 0 ? batch.lsPayloads : null,
                derived_groups: derivedPayload.length > 0 ? derivedPayload : null
            });
        }

        // ── 跨 batch LS ──
        var crossBatchLSPayloads = [];
        for (var ci = 0; ci < crossBatchLS.length; ci++) {
            var cbLS = crossBatchLS[ci];
            var cblLongBatch = null, cblShortBatch = null;
            for (var bj = 0; bj < batches.length; bj++) {
                if (batches[bj].groupIdToIndex[cbLS.longGroupId] !== undefined) cblLongBatch = batches[bj];
                if (batches[bj].groupIdToIndex[cbLS.shortGroupId] !== undefined) cblShortBatch = batches[bj];
            }
            if (!cblLongBatch || !cblShortBatch) continue;

            var cblLongIdx = cblLongBatch.groupIdToIndex[cbLS.longGroupId] - 1;
            var cblShortIdx = cblShortBatch.groupIdToIndex[cbLS.shortGroupId] - 1;
            var crossBatchName = GT.panels.actions ? GT.panels.actions.lsDisplayName(cbLS) : (cbLS.name || 'Long-Short');

            crossBatchLSPayloads.push({
                name: crossBatchName,
                key: crossBatchName,
                long: {
                    submission_id: cblLongBatch.testerId,
                    factor_alias: cblLongBatch.factorAlias,
                    group: cblLongIdx
                },
                short: {
                    submission_id: cblShortBatch.testerId,
                    factor_alias: cblShortBatch.factorAlias,
                    group: cblShortIdx
                }
            });
        }

        var bulkPayload = {
            batches: batchPayloads,
            cross_batch_ls: crossBatchLSPayloads.length > 0 ? crossBatchLSPayloads : null,
            fee: fee,
            fee_map: fee_map,
            group_fee_maps: null,
            use_closetoday: use_closetoday,
            start_date: start_date,
            end_date: end_date,
            rebalance_mode: rebalance_mode
        };

        try {
            // ── 进度条 ──
            var progressBarId = 'gt-batch-progress';
            var progressBar = document.getElementById(progressBarId);
            if (!progressBar) {
                progressBar = document.createElement('div');
                progressBar.id = progressBarId;
                progressBar.className = 'gt-progress-container';
                progressBar.innerHTML = '<div class="gt-progress-bar"><div class="gt-progress-indeterminate"></div></div>' +
                                        '<span class="gt-progress-text">计算中...</span>';
                var chartContainer = document.getElementById('group_chart_container');
                var insertParent = chartContainer ? chartContainer.parentNode : (runBtn ? runBtn.parentNode : document.body);
                var insertBefore = chartContainer || (runBtn ? runBtn.nextSibling : null);
                insertParent.insertBefore(progressBar, insertBefore);
            }

            var data = await runTest.postBatchGroupTest(bulkPayload);
            if (!data.success) {
                var errorText = data.needs_ic_test && !!document.getElementById('ic_test_module')
                    ? '当前测试器还没有 IC 测试结果。请先在 IC 测试模块运行一次 IC 测试。'
                    : data.error;
                if (statusSpan) {
                    statusSpan.innerHTML = '✗ 分组测试失败: ' + errorText;
                    statusSpan.style.color = '#d40000';
                }
                if (data.batch_errors) {
                    console.error('[runGroupTest] batch errors:', data.batch_errors);
                }
                return;
            }

            // 标记所有 batch 为 done
            for (var bi = 0; bi < batches.length; bi++) {
                var btch = batches[bi];
                if (GT.panels && GT.panels.ui) GT.panels.ui.markGroupFactorStatus(btch.testerId, btch.factorAlias, 'done');
            }

            // 渲染结果
            if (GT.results && GT.results.renderer && GT.results.renderer.applyGroupTestResult) {
                GT.results.renderer.applyGroupTestResult(data);
            }

            if (statusSpan) {
                var doneMsg = '✓ ' + data.batch_count + ' 批次完成';
                if (data.cross_batch_ls_count) {
                    doneMsg += '（含 ' + data.cross_batch_ls_count + ' 跨 Batch LS）';
                }
                statusSpan.innerHTML = doneMsg;
                statusSpan.style.color = '#28a745';
            }
        } catch (e) {
            console.error('[runGroupTest] error:', e);
            if (statusSpan) {
                statusSpan.innerHTML = '✗ ' + (e.message || '未知错误');
                statusSpan.style.color = '#d40000';
            }
        } finally {
            var _pb = document.getElementById('gt-batch-progress');
            if (_pb) _pb.remove();
            if (runBtn) {
                runBtn.disabled = false;
                runBtn.style.display = '';
            }
        }
    };


    // ════════════════════════════════════════════════════════════════
    //  派生组：生成 / 删除 / 刷新
    // ════════════════════════════════════════════════════════════════

    /** 为单个派生组发请求，不画图 */
    runTest._generateDerivedGroupOnce = async function(def, fee, fee_map, submissionId) {
        if (!def || !submissionId) return null;
        if (def.baseGroup == null) return null;
        try {
            var resp = await GT.api.createDerivedGroup({
                submission_id: submissionId,
                group_index: def.baseGroup,
                product_names: def.productNames,
                name: def.name,
                use_closetoday: def.useCloseToday !== undefined ? !!def.useCloseToday : false,
                fee: fee || 0,
                fee_map: fee_map || {}
            });
            if (!resp || !resp.success) return { success: false, def: def, error: (resp && resp.error) || '未知错误' };
            return { success: true, def: def, group: resp.group || {}, metric: resp.metric || {} };
        } catch (err) {
            return { success: false, def: def, error: err.message || '网络错误' };
        }
    };

    /** 将 _generateDerivedGroupOnce 的结果应用到内存数据 */
    runTest._applyDerivedGroupResult = function(result) {
        var def = result.def;
        if (GT.panels.actions && GT.panels.actions.removeGeneratedDerivedArtifacts) {
            GT.panels.actions.removeGeneratedDerivedArtifacts(def.id);
        }
        def.key = GT.panels.actions ? GT.panels.actions.makeUniqueGroupKey(def.name, def.id) : (def.name || def.id || '派生组');
        def.generated = true;
        var group = result.group;
        group.name = def.name;
        group.is_derived = true;
        group.derived = Object.assign({}, group.derived || {}, { id: def.id, key: def.key });
        var c = cache();
        var grossData = c ? c.getLastGrossData() : null;
        if (grossData) {
            grossData.push(group);
            c.setLastGrossData(grossData);
        }
        var metrics = c ? c.getLastMetrics() : null;
        if (metrics) {
            metrics[def.key] = result.metric;
            c.setLastMetrics(metrics);
        }
    };

    /** 统一刷新：图表 + 指标表 + 派生组面板 */
    runTest._refreshGroupView = function(baseGroupIndex) {
        if (GT.results && GT.results.renderer) {
            var c = cache();
            GT.results.renderer.drawGroupChart(c ? c.getLastGrossData() : null);
            GT.results.renderer.renderMetricsTable(c ? c.getLastMetrics() : null);
        }
        if (GT.panels.actions && GT.panels.actions.renderDerivedGroupsPanel) {
            GT.panels.actions.renderDerivedGroupsPanel(baseGroupIndex);
        }
    };

    /** 单个派生组生成：发 1 次请求，更新数据，刷新 1 次 */
    runTest.generateDerivedGroup = async function(id) {
        var node = GT.groupSettings.groups ? GT.groupSettings.groups.get(id) : null;
        if (!node || !node.isDerived) return;
        var products = GT.panels.actions ? GT.panels.actions.effectiveDerivedProductNames(node) : [];
        if (!products.length) {
            alert('该派生组没有选中任何品种。');
            return;
        }
        var c = cache();
        var grossData = c ? c.getLastGrossData() : null;
        var metrics = c ? c.getLastMetrics() : null;
        if (!grossData || !metrics) {
            alert('请先运行分组测试，再生成派生组曲线。');
            return;
        }

        var baseNode = GT.groupSettings.groups.get(node.baseGroupId);
        var baseGroupIndex = c ? c.getCurrentGroupDetailIndex() : null;
        if (baseGroupIndex == null && baseNode) {
            baseGroupIndex = (baseNode.groupIndex || 1) - 1;
        }

        var fee = 0;
        var fee_map = {};
        if (baseNode) {
            if (baseNode.feeMode === 'uniform') {
                fee = baseNode.feeRate != null ? baseNode.feeRate : 0.0025;
            } else if (baseNode.feeMode === 'per_product') {
                try {
                    fee_map = await GT.fee.ensureFeeData();
                } catch (err) {
                    console.error('[generateDerivedGroup] ensureFeeData failed:', err);
                }
            }
        }

        var def = {
            id: node.id,
            name: GT.panels.actions ? GT.panels.actions.groupDisplayKey(node) : (node.shortAlias || node.name || node.id),
            key: GT.panels.actions ? GT.panels.actions.groupDisplayKey(node) : (node.shortAlias || node.name || node.id),
            baseGroup: baseGroupIndex,
            productNames: products,
            productMask: node.productMask || {}
        };

        var result = await runTest._generateDerivedGroupOnce(def, fee, fee_map, baseNode ? baseNode.testerId : null);
        if (!result || !result.success) {
            alert('生成派生组失败: ' + ((result && result.error) || '未知错误'));
            return;
        }
        runTest._applyDerivedGroupResult(result);
        runTest._refreshGroupView(baseGroupIndex);
    };

    /** 删除派生组 */
    runTest.deleteDerivedGroup = function(id) {
        var node = GT.groupSettings.groups ? GT.groupSettings.groups.get(id) : null;
        var c = cache();
        var baseGroupIndex = c ? c.getCurrentGroupDetailIndex() : null;
        if (baseGroupIndex == null && node && node.baseGroupId) {
            var baseNode = GT.groupSettings.groups.get(node.baseGroupId);
            if (baseNode) baseGroupIndex = (baseNode.groupIndex || 1) - 1;
        }

        if (GT.panels.actions && GT.panels.actions.removeGeneratedDerivedArtifacts) {
            GT.panels.actions.removeGeneratedDerivedArtifacts(id);
        }
        try {
            if (GT.groupSettings.groups) GT.groupSettings.groups.remove(id);
            if (GT.events && GT.events.emit) GT.events.emit('groupsChanged');
        } catch (e) {
            console.warn('[deleteDerivedGroup] group remove failed:', e);
        }

        var grossData = c ? c.getLastGrossData() : null;
        var metrics = c ? c.getLastMetrics() : null;
        if (grossData && GT.results && GT.results.renderer) {
            GT.results.renderer.drawGroupChart(grossData);
        }
        if (metrics && GT.results && GT.results.renderer) {
            GT.results.renderer.renderMetricsTable(metrics);
        }
        if (GT.panels.actions && GT.panels.actions.renderDerivedGroupsPanel) {
            GT.panels.actions.renderDerivedGroupsPanel(baseGroupIndex != null ? baseGroupIndex : 0);
        }
    };

    GT.core.runTest = runTest;
})();
