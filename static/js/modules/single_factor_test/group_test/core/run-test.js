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

    function cache() {
        return GT.groupSettings && GT.groupSettings.cache ? GT.groupSettings.cache : null;
    }

    function prepareLocalRun() {
        return GT.localSettings && typeof GT.localSettings.prepareRun === 'function'
            ? GT.localSettings.prepareRun()
            : { payload: {}, errors: ['本地运行设置未就绪'], structureKeyParts: [] };
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
     * 批量分组测试 POST（SSE 流式）
     */
    runTest.postBatchGroupTest = function(payload, onEvent) {
        return fetch('/run_group_test_stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(async function(res) {
            if (!res.ok) {
                throw new Error('HTTP ' + res.status);
            }
            var reader = res.body.getReader();
            var decoder = new TextDecoder();
            var buffer = '';
            var lastEvent = '';
            var resultData = null;

            while (true) {
                var readResult = await reader.read();
                if (readResult.done) break;
                buffer += decoder.decode(readResult.value, { stream: true });
                var lines = buffer.split('\n');
                buffer = lines.pop();

                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i];
                    if (line.startsWith('event: ')) {
                        lastEvent = line.slice(7).trim();
                    } else if (line.startsWith('data: ')) {
                        try {
                            var payload = JSON.parse(line.slice(6));
                            if (onEvent) {
                                onEvent(lastEvent, payload);
                            }
                            if (lastEvent === 'result') {
                                resultData = payload;
                            } else if (lastEvent === 'error') {
                                resultData = payload;
                            }
                        } catch (e) {
                            // skip malformed JSON
                        }
                    }
                }
            }
            return resultData || { success: false, error: '无响应数据' };
        });
    };

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

        var existingBase = (groups.getAll() || []).filter(function(g) { return !g.parentId; });
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

                    // groupAddBatch: ensure batch exists for this tester+factor combo (refs #100)
                    var batchObj = GT.groupSettings.batch.ensure(testerId, factorAlias, GROUPS_PER_FACTOR);

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
                var totalBase = (groups.getAll() || []).filter(function(g) { return !g.parentId; }).length;
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
        var nonDerived = allBase.filter(function(g) { return !g.parentId; });
        if (nonDerived.length === 0) {
            if (statusSpan) {
                statusSpan.innerHTML = '⏳ 无现有分组，正在加载默认分组...';
                statusSpan.style.color = '#0078d4';
            }
            await runTest.loadDefaultGroups();
            allBase = (GT.groupSettings.groups && GT.groupSettings.groups.getAll()) || [];
            nonDerived = allBase.filter(function(g) { return !g.parentId; });
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
            // 子组（有 parentId）：分配 expandedIndex，不改动字段名
            var allGroups = (GT.groupSettings.groups && GT.groupSettings.groups.getAll) ? GT.groupSettings.groups.getAll() : [];
            for (var ai = 0; ai < allGroups.length; ai++) {
                var ag = allGroups[ai];
                if (!ag || !ag.parentId) continue;
                b.groupIdToIndex[ag.id] = expandedIndex;
                expandedIndex += 1;
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
        var rebalance_mode = firstGroup ? (firstGroup.rebalanceMode || GT.groupSettings.getFieldDefault('rebalanceMode')) : GT.groupSettings.getFieldDefault('rebalanceMode');
        var localRun = prepareLocalRun();
        if (localRun.errors && localRun.errors.length) {
            if (statusSpan) { statusSpan.innerHTML = '✗ ' + localRun.errors[0]; statusSpan.style.color = '#d40000'; }
            if (runBtn) runBtn.disabled = false;
            return;
        }

        // ── 费率聚合 ──
        var fee = 0;
        var fee_modifications = [];
        var hasPerProduct = false;
        if (GT.groupSettings.groups) {
            var allFeeGroups = GT.groupSettings.groups.getAll() || [];
            for (var fgi = 0; fgi < allFeeGroups.length; fgi++) {
                var fg = allFeeGroups[fgi];
                if (fg.parentId) continue;
                if (fg.feeMode === 'per_product') hasPerProduct = true;
                if (fg.feeMode === 'uniform' && fee === 0) {
                    fee = fg.feeRate != null ? fg.feeRate : 0.0025;
                }
            }
        }
        if (hasPerProduct && GT.fee) {
            try {
                // 仍然需要确保费率数据加载（_resolve_group_trade_specs 会从产品数据库取值）
                await GT.fee.ensureFeeData();
                fee_modifications = GT.fee.getModifications ? GT.fee.getModifications() : [];
            } catch (err) {
                console.error('[runBatch] ensureFeeData failed:', err);
            }
        }
        var use_closetoday = GT.fee ? GT.fee.useCloseToday() : false;
        if (statusSpan) {
            statusSpan.innerHTML = '分组测试运行中...（共 ' + totalBatches + ' 批次）';
            statusSpan.style.color = '#0078d4';
        }

        // ── 构建 batch payloads：直接传 groupSettings 的原样数据 ──
        var allStoredGroups = (GT.groupSettings.groups && GT.groupSettings.groups.getAll) ? GT.groupSettings.groups.getAll() : [];
        var batchPayloads = [];
        for (var bi = 0; bi < batches.length; bi++) {
            var batch = batches[bi];
            // 收集本 batch 涉及的所有 group id
            var batchGroupIds = {};
            for (var gi = 0; gi < batch.groups.length; gi++) {
                if (batch.groups[gi] && batch.groups[gi].id) batchGroupIds[batch.groups[gi].id] = true;
            }
            // 筛选组：通过 parentId 找到指向本 batch 中某个 group 的筛选组
            for (var si = 0; si < allStoredGroups.length; si++) {
                var sg = allStoredGroups[si];
                if (sg && sg.parentId && batchGroupIds[sg.parentId]) {
                    batchGroupIds[sg.id] = true;
                }
            }
            // 从存储中取出本 batch 涉及的所有 group（保持添加顺序）
            var groupList = [];
            for (var ai = 0; ai < allStoredGroups.length; ai++) {
                if (batchGroupIds[allStoredGroups[ai].id]) groupList.push(allStoredGroups[ai]);
            }
            batchPayloads.push({
                submission_id: batch.testerId,
                factor_alias: batch.factorAlias,
                n_groups: batch.groupCount,
                groups: groupList.length > 0 ? groupList : null,
                ls_configs: batch.lsPayloads.length > 0 ? batch.lsPayloads : null
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
                    n_groups: cblLongBatch.groupCount,
                    group: cblLongIdx
                },
                short: {
                    submission_id: cblShortBatch.testerId,
                    factor_alias: cblShortBatch.factorAlias,
                    n_groups: cblShortBatch.groupCount,
                    group: cblShortIdx
                }
            });
        }

        var bulkPayload = {
            batches: batchPayloads,
            cross_batch_ls: crossBatchLSPayloads.length > 0 ? crossBatchLSPayloads : null,
            fee: fee,
            fee_modifications: fee_modifications,
            use_closetoday: use_closetoday,
            rebalance_mode: rebalance_mode
        };
        Object.assign(bulkPayload, localRun.payload || {});

        try {
            // ── 确定性进度条 ──
            var progressBarId = 'gt-batch-progress';
            var progressBar = document.getElementById(progressBarId);
            if (!progressBar) {
                progressBar = document.createElement('div');
                progressBar.id = progressBarId;
                progressBar.className = 'gt-progress-container';
                progressBar.innerHTML =
                    '<div class="gt-progress-bar" style="background:#e0e0e0;border-radius:6px;height:12px;overflow:hidden;margin-bottom:4px;">' +
                    '<div id="' + progressBarId + '-fill" class="gt-progress-fill" style="width:0%;height:100%;background:linear-gradient(90deg,#4caf50,#81c784);transition:width 0.3s;border-radius:6px;"></div>' +
                    '</div>' +
                    '<span id="' + progressBarId + '-text" class="gt-progress-text" style="font-size:13px;color:#666;">准备中...</span>';
                var chartContainer = document.getElementById('group_chart_container');
                var insertParent = chartContainer ? chartContainer.parentNode : (runBtn ? runBtn.parentNode : document.body);
                var insertBefore = chartContainer || (runBtn ? runBtn.nextSibling : null);
                insertParent.insertBefore(progressBar, insertBefore);
            }

            var data = await runTest.postBatchGroupTest(bulkPayload, function(event, payload) {
                var fill = document.getElementById(progressBarId + '-fill');
                var text = document.getElementById(progressBarId + '-text');
                if (event === 'start') {
                    if (fill) fill.style.width = '0%';
                    if (text) text.textContent = '0/' + (payload.total || 1) + ' 批次';
                } else if (event === 'progress') {
                    var pct = payload.total > 0 ? (payload.completed / payload.total * 100) : 0;
                    if (fill) fill.style.width = pct + '%';
                    if (text) {
                        var phaseLabel = '';
                        if (payload.phase === 'batch') {
                            phaseLabel = '批次 ';
                        } else if (payload.phase === 'membership') {
                            phaseLabel = '隶属度 ';
                        } else if (payload.phase === 'trade_data') {
                            phaseLabel = '交易数据 ';
                        } else if (payload.phase === 'simulate') {
                            phaseLabel = '模拟 ';
                        }
                        text.textContent = phaseLabel + (payload.completed || 0) + '/' + (payload.total || 1);
                    }
                }
            });

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
                var doneMsg = '✓ ' + data.simulation_count + ' 组模拟完成';
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
    runTest._generateDerivedGroupOnce = async function(def, fee, fee_mods, submissionId) {
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
                fee_modifications: fee_mods || []
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
        group.parent_id = true;
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
        if (!node || !node.parentId) return;
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

        // Walk parentId to root
        var baseNode = node;
        while (baseNode && baseNode.parentId) {
            baseNode = GT.groupSettings.groups.get(baseNode.parentId);
            if (!baseNode) break;
        }
        var baseGroupIndex = c ? c.getCurrentGroupDetailIndex() : null;
        if (baseGroupIndex == null && baseNode) {
            baseGroupIndex = (baseNode.groupIndex || 1) - 1;
        }

        var fee = 0;
        var fee_mods = [];
        if (baseNode) {
            if (baseNode.feeMode === 'uniform') {
                fee = baseNode.feeRate != null ? baseNode.feeRate : 0.0025;
            } else if (baseNode.feeMode === 'per_product') {
                try {
                    await GT.fee.ensureFeeData();
                    fee_mods = GT.fee.getModifications ? GT.fee.getModifications() : [];
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

        var result = await runTest._generateDerivedGroupOnce(def, fee, fee_mods, baseNode ? baseNode.testerId : null);
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
        if (baseGroupIndex == null && node && node.parentId) {
            // Walk parentId to root
            var baseNode = node;
            while (baseNode && baseNode.parentId) {
                baseNode = GT.groupSettings.groups.get(baseNode.parentId);
                if (!baseNode) break;
            }
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
