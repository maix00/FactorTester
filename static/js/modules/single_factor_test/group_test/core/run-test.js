/**
 * core/run-test.js — 分组测试执行器
 *
 * 负责：
 *   - 运行分组测试（单次/批量/全因子）
 *   - 加载默认分组
 *   - 派生组生成/删除
 *   - 工具函数：postBatchGroupTest, clearResults
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

    async function resolveSubmissionIdForGroup(submissionId) {
        var targetId = String(submissionId || '');
        if (!targetId) return targetId;
        try {
            var subs = Array.isArray(window.submissions) ? window.submissions : [];
            var pageUuid = encodeURIComponent(window._pageUuid || '');
            var resp = await fetch('/api/list_submissions?page_uuid=' + pageUuid);
            var data = await resp.json();
            if (!data.success || !Array.isArray(data.submissions) || data.submissions.length === 0) {
                return targetId;
            }

            for (var j = 0; j < data.submissions.length; j++) {
                if (String(data.submissions[j].id) === targetId) return String(data.submissions[j].id);
            }

            var localSub = null;
            for (var k = 0; k < subs.length; k++) {
                if (String(subs[k].id) === targetId) {
                    localSub = subs[k];
                    break;
                }
            }
            var rawLocalPaths = localSub && (localSub.paths || localSub.selected_paths);
            var localPaths = Array.isArray(rawLocalPaths) ? rawLocalPaths.map(String) : [];
            if (localPaths.length > 0) {
                var pathSet = {};
                localPaths.forEach(function(p) { pathSet[p] = true; });
                for (var m = 0; m < data.submissions.length; m++) {
                    var remotePaths = (data.submissions[m].selected_paths || []).map(String);
                    if (remotePaths.length !== localPaths.length) continue;
                    var same = true;
                    for (var rp = 0; rp < remotePaths.length; rp++) {
                        if (!pathSet[remotePaths[rp]]) {
                            same = false;
                            break;
                        }
                    }
                    if (same) {
                        console.log('[runGroupTest] resolved submission id:', targetId, '->', String(data.submissions[m].id));
                        return String(data.submissions[m].id);
                    }
                }
            }
            if (targetId.indexOf('tpl-') === 0 && data.submissions.length === 1) {
                console.log('[runGroupTest] resolved submission id:', targetId, '->', String(data.submissions[0].id));
                return String(data.submissions[0].id);
            }
        } catch (e) {
            console.warn('resolveSubmissionIdForGroup failed:', e);
        }
        return targetId;
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

    // ════════════════════════════════════════════════════════════════
    //  运行分组测试
    // ════════════════════════════════════════════════════════════════

    runTest.runGroupTest = async function() {
        var statusSpan = document.getElementById('group_test_status');
        var runBtn = document.getElementById('run_group_test_btn');

        var REG = window.GT_CONFIG_REGISTRY;
        if (REG && typeof REG.hasDirty === 'function' && REG.hasDirty() && typeof REG.commitDirty === 'function') {
            REG.commitDirty();
        }

        // ── 0. 检查是否有分组 ──
        var allBase = (GT.groupSettings.groups && GT.groupSettings.groups.getAll()) || [];
        var nonDerived = allBase.filter(function(g) { return !g.parentId; });
        if (nonDerived.length === 0) {
            if (statusSpan) {
                statusSpan.innerHTML = '✗ 未定义分组，请先在「分组组合设置」中添加分组';
                statusSpan.style.color = '#d40000';
            }
            return;
        }

        // ── 1. 扁平化：收集所有 group + 构建 group_id → groupIndex 映射 ──
        var allStoredGroups = (GT.groupSettings.groups && GT.groupSettings.groups.getAll) ? GT.groupSettings.groups.getAll() : [];
        // 构建全局 group_id → 1-based groupIndex 映射（groupIndex=0 视为1）
        var groupIdToIndex = {};
        for (var ai = 0; ai < allStoredGroups.length; ai++) {
            var ag = allStoredGroups[ai];
            if (!ag || !ag.id) continue;
            var idx = Number(ag.groupIndex || (ag.parentId ? 0 : (ai + 1)));
            groupIdToIndex[ag.id] = idx > 0 ? idx : ai + 1;
        }

        // ── 2. 构建 LS configs（用 groupIndex-1 作为 group 引用） ──
        var allLS = (GT.groupSettings.lsConfigs && GT.groupSettings.lsConfigs.getAll()) || [];
        var flatLSConfigs = [];
        for (var li = 0; li < allLS.length; li++) {
            var ls = allLS[li];
            var longIdx = groupIdToIndex[ls.longGroupId];
            var shortIdx = groupIdToIndex[ls.shortGroupId];
            if (longIdx === undefined || shortIdx === undefined) {
                console.warn('[runGroupTest] LS config ' + ls.id + ' references unknown group(s): long=' + ls.longGroupId + ' short=' + ls.shortGroupId);
                continue;
            }
            var lsName = GT.panels.actions ? GT.panels.actions.lsDisplayName(ls) : (ls.name || 'Long-Short');
            flatLSConfigs.push({
                name: lsName,
                key: lsName,
                long: [{ group: longIdx - 1, weight: 1.0 }],
                short: [{ group: shortIdx - 1, weight: 1.0 }]
            });
        }

        // ── 3. 构建 payload ──
        if (runBtn) runBtn.disabled = true;

        var localRun = prepareLocalRun();
        if (localRun.errors && localRun.errors.length) {
            if (statusSpan) { statusSpan.innerHTML = '✗ ' + localRun.errors[0]; statusSpan.style.color = '#d40000'; }
            if (runBtn) runBtn.disabled = false;
            return;
        }

        if (statusSpan) {
            statusSpan.innerHTML = '分组测试运行中...';
            statusSpan.style.color = '#0078d4';
        }

        // ── 合并 localSettings payload（start_date/end_date/precision/tz/initial_capital 等）──
        var bulkPayload = Object.assign({}, localRun.payload, {
            groups: allStoredGroups,
            ls_configs: flatLSConfigs.length > 0 ? flatLSConfigs : [],
            page_uuid: window._pageUuid || ''
        });

        try {
            // ── 多行并行进度条 ──
            var progressContainerId = 'gt-batch-progress';
            var progressContainer = document.getElementById(progressContainerId);
            if (!progressContainer) {
                progressContainer = document.createElement('div');
                progressContainer.id = progressContainerId;
                progressContainer.className = 'gt-progress-container';
                progressContainer.style.cssText = 'display:block;width:100%;box-sizing:border-box;margin:8px 0;padding:8px;background:#f9f9f9;border-radius:8px;border:1px solid #e0e0e0;';
                var chartContainer = document.getElementById('group_chart_container');
                var insertParent = chartContainer ? chartContainer.parentNode : (runBtn ? runBtn.parentNode : document.body);
                var insertBefore = chartContainer || (runBtn ? runBtn.nextSibling : null);
                insertParent.insertBefore(progressContainer, insertBefore);
            }
            progressContainer.innerHTML = '';

            var pendingGlobalProgress = [];

            var batchMgr = GT.groupSettings.runGroupBatch.createManager({
                progressContainer: progressContainer,
            });

            markProgressRowsDone = function(done, message) {
                batchMgr.markAllDone(done, message);
            };

            var data = await runTest.postBatchGroupTest(bulkPayload, function(event, payload) {
                if (event !== 'result' && event !== 'error') {
                    console.log('[SSE frontend] event:', event, 'payload:', JSON.stringify(payload));
                }
                if (event === 'start') {
                    var newTotal = payload.product_coverage_batch_total || payload.total || 1;
                    batchMgr.syncRows(newTotal);
                    // 回放缓存的无 batch_index 全局进度
                    if (pendingGlobalProgress.length && batchMgr.getIndices().length) {
                        var pending = pendingGlobalProgress;
                        pendingGlobalProgress = [];
                        for (var p = 0; p < pending.length; p++) {
                            batchMgr.updateAllRows(pending[p].phase, pending[p].completed, pending[p].total, pending[p].message);
                        }
                    }
                } else if (event === 'progress') {
                    var bi = payload.product_coverage_batch_index;
                    if (bi !== undefined && bi >= 0) {
                        batchMgr.updateRow(bi, payload.phase, payload.completed || 0, payload.total || 0, payload.message);
                    } else if (!batchMgr.getIndices().length) {
                        pendingGlobalProgress.push({
                            phase: payload.phase,
                            completed: payload.completed || 0,
                            total: payload.total || 0,
                            message: payload.message
                        });
                    } else {
                        batchMgr.updateAllRows(payload.phase, payload.completed || 0, payload.total || 0, payload.message);
                    }
                }
            });

            if (!data.success) {
                var errorText = data.needs_ic_test && !!document.getElementById('ic_test_module')
                    ? '当前测试器还没有 IC 测试结果。请先在 IC 测试模块运行一次 IC 测试。'
                    : data.error;
                markProgressRowsDone(false, errorText || '分组测试失败');
                if (statusSpan) {
                    statusSpan.innerHTML = '✗ 分组测试失败: ' + errorText;
                    statusSpan.style.color = '#d40000';
                }
                if (data.batch_errors) {
                    console.error('[runGroupTest] batch errors:', data.batch_errors);
                }
                return;
            }

            // 标记所有 group 为 done
            var doneGroups = allStoredGroups || [];
            for (var bi = 0; bi < doneGroups.length; bi++) {
                var btch = doneGroups[bi];
                if (GT.panels && GT.panels.ui && !btch.parentId) GT.panels.ui.markGroupFactorStatus(btch.testerId, btch.factorAlias, 'done');
            }
            markProgressRowsDone(true, '分组测试完成');

            // 渲染结果
            if (GT.results && GT.results.renderer && GT.results.renderer.applyGroupTestResult) {
                GT.results.renderer.applyGroupTestResult(data);
            }

            if (statusSpan) {
                var doneMsg = '✓ ' + data.simulation_count + ' 组模拟完成';
                statusSpan.innerHTML = doneMsg;
                statusSpan.style.color = '#28a745';
            }
        } catch (e) {
            console.error('[runGroupTest] error:', e);
            markProgressRowsDone(false, e.message || '未知错误');
            if (statusSpan) {
                statusSpan.innerHTML = '✗ ' + (e.message || '未知错误');
                statusSpan.style.color = '#d40000';
            }
        } finally {
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
