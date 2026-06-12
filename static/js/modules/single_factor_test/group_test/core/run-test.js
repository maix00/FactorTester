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

        var markProgressRowsDone = function() {};
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

        // ── 3. 构建单个扁平 entry ──
        if (runBtn) runBtn.disabled = true;

        var firstGroup = nonDerived[0];
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
        for (var fgi = 0; fgi < allStoredGroups.length; fgi++) {
            var fg = allStoredGroups[fgi];
            if (fg.parentId) continue;
            if (fg.feeMode === 'per_product') hasPerProduct = true;
            if (fg.feeMode === 'uniform' && fee === 0) {
                fee = fg.feeRate != null ? fg.feeRate : 0.0025;
            }
        }
        if (hasPerProduct && GT.fee) {
            try {
                await GT.fee.ensureFeeData();
                fee_modifications = GT.fee.getModifications ? GT.fee.getModifications() : [];
            } catch (err) {
                console.error('[runBatch] ensureFeeData failed:', err);
            }
        }
        var use_closetoday = GT.fee ? GT.fee.useCloseToday() : false;
        if (statusSpan) {
            statusSpan.innerHTML = '分组测试运行中...';
            statusSpan.style.color = '#0078d4';
        }

        // 解析 submission_id
        var resolvedSubmissionId = await resolveSubmissionIdForGroup(firstGroup.testerId);
        var n_groups = firstGroup.groupCount || nonDerived.length || 1;

        var bulkPayload = {
            batches: [{
                submission_id: resolvedSubmissionId || firstGroup.testerId,
                factor_alias: firstGroup.factorAlias,
                n_groups: n_groups,
                groups: allStoredGroups,
                ls_configs: flatLSConfigs.length > 0 ? flatLSConfigs : null
            }],
            factor_family_alias: window.factorFamilyAlias || '',
            page_uuid: window._pageUuid || '',
            fee: fee,
            fee_modifications: fee_modifications,
            use_closetoday: use_closetoday,
            rebalance_mode: rebalance_mode
        };
        Object.assign(bulkPayload, localRun.payload || {});

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

            // 阶段中文映射
            var phaseLabels = {
                factor_eval: '因子计算',
                returns_eval: '收益计算',
                membership: '隶属度',
                flat_membership: '展平',
                remap: '重映射',
                trade_data: '交易数据',
                liquidity: '流动性',
                simulate: '模拟中',
                serialize: '序列化',
                batch: '批次',
                info: ''
            };
            var nonTimelinePhases = { batch: true, info: true };
            var phaseOrder = Object.keys(phaseLabels).filter(function(phase) {
                return !nonTimelinePhases[phase];
            });
            var batchRows = {};     // batchIndex → { rowEl, fillEl, textEl, phaseEl, messageEl }
            var totalBatches = 0;
            var pendingGlobalProgress = [];

            function _phaseProgressPct(phase, completed, total) {
                if (total <= 0) return null;
                if (phase && phaseLabels[phase] === undefined && !nonTimelinePhases[phase]) {
                    phaseLabels[phase] = phase;
                    phaseOrder.push(phase);
                }
                var localPct = Math.max(0, Math.min(1, completed / total));
                var phaseIdx = phaseOrder.indexOf(phase);
                if (phaseIdx >= 0) {
                    return Math.round(((phaseIdx + localPct) / phaseOrder.length) * 100);
                }
                return null;
            }

            function _escapeProgressHtml(value) {
                return String(value == null ? '' : value)
                    .replace(/&/g, '&amp;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;')
                    .replace(/"/g, '&quot;')
                    .replace(/'/g, '&#39;');
            }

            function _renderPhaseHistory(row) {
                if (!row.historyEl) return;
                var phases = Object.keys(row.phaseHistory || {});
                if (!phases.length) {
                    row.historyEl.innerHTML = '<div style="color:#98a2b3;">暂无阶段记录</div>';
                    return;
                }
                phases.sort(function(a, b) {
                    var ai = phaseOrder.indexOf(a);
                    var bi = phaseOrder.indexOf(b);
                    if (ai < 0) ai = 999;
                    if (bi < 0) bi = 999;
                    return ai - bi;
                });
                var html = phases.map(function(phase) {
                    var item = row.phaseHistory[phase] || {};
                    var label = _escapeProgressHtml(phaseLabels[phase] || phase);
                    var status = item.done ? '已完成' : '进行中';
                    var count = item.total > 0 ? (item.completed + '/' + item.total) : '--';
                    var msg = _escapeProgressHtml(item.message || '');
                    return '<div style="display:grid;grid-template-columns:80px minmax(12ch,max-content) 54px minmax(0,1fr);gap:8px;align-items:center;padding:2px 0;">'
                        + '<span style="font-weight:600;color:#475467;">' + label + '</span>'
                        + '<span style="color:#667085;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;">' + count + '</span>'
                        + '<span style="color:' + (item.done ? '#12a150' : '#0078d4') + ';white-space:nowrap;">' + status + '</span>'
                        + '<span style="color:#667085;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="' + msg + '">' + msg + '</span>'
                        + '</div>';
                }).join('');
                row.historyEl.innerHTML = html;
            }

            function _recordPhaseProgress(row, phase, completed, total, message) {
                if (!phase) return;
                if (phase === 'info') {
                    if (row.currentPhase && row.phaseHistory[row.currentPhase]) {
                        var currentItem = row.phaseHistory[row.currentPhase];
                        var preserveCurrentCount = total > 0 && currentItem.total > total;
                        if (!preserveCurrentCount) {
                            currentItem.completed = completed || currentItem.completed || 0;
                            currentItem.total = total || currentItem.total || 0;
                        }
                        row.phaseHistory[row.currentPhase].message = message || row.phaseHistory[row.currentPhase].message || '';
                        _renderPhaseHistory(row);
                    }
                    return;
                }
                if (nonTimelinePhases[phase]) return;
                if (row.currentPhase && row.currentPhase !== phase && row.phaseHistory[row.currentPhase]) {
                    row.phaseHistory[row.currentPhase].done = true;
                }
                row.currentPhase = phase;
                var isDone = total > 0 && completed >= total;
                var existing = row.phaseHistory[phase] || {};
                var preserveCount = total > 0 && existing.total > total;
                row.phaseHistory[phase] = {
                    completed: preserveCount ? existing.completed : (completed || 0),
                    total: preserveCount ? existing.total : (total || 0),
                    message: message || existing.message || '',
                    done: !!(isDone || existing.done)
                };
                _renderPhaseHistory(row);
            }

            markProgressRowsDone = function(done, message) {
                var keys = Object.keys(batchRows);
                for (var i = 0; i < keys.length; i++) {
                    var row = batchRows[keys[i]];
                    if (!row) continue;
                    if (row.currentPhase && row.phaseHistory[row.currentPhase]) {
                        row.phaseHistory[row.currentPhase].done = !!done;
                        if (message) row.phaseHistory[row.currentPhase].message = message;
                    }
                    if (done) {
                        row.pct = 100;
                        row.fillEl.style.width = '100%';
                        row.phaseEl.textContent = '完成';
                    } else {
                        row.phaseEl.textContent = '失败';
                        row.fillEl.style.background = 'linear-gradient(90deg,#d92d20,#f97066)';
                    }
                    if (message && row.messageEl) {
                        row.messageEl.textContent = message;
                        row.messageEl.title = message;
                    }
                    _renderPhaseHistory(row);
                }
            };

            function _ensureBatchRow(batchIndex, batchLabel, batchTotal) {
                if (batchRows[batchIndex]) {
                    var existingLabel = batchRows[batchIndex].labelEl;
                    if (existingLabel) {
                        existingLabel.textContent = batchLabel || ('Batch ' + (batchIndex + 1));
                    }
                    return batchRows[batchIndex];
                }
                var row = document.createElement('div');
                row.style.cssText = 'margin-bottom:6px;';
                var line = document.createElement('div');
                line.style.cssText = 'display:flex;align-items:center;gap:8px;width:100%;';
                row.appendChild(line);
                // 标签
                var label = document.createElement('span');
                label.style.cssText = 'flex:0 0 70px;font-size:12px;font-weight:600;color:#333;white-space:nowrap;';
                label.textContent = batchLabel || ('Batch ' + (batchIndex + 1));
                line.appendChild(label);
                // 阶段标签
                var phaseSpan = document.createElement('span');
                phaseSpan.style.cssText = 'flex:0 0 65px;font-size:11px;color:#888;white-space:nowrap;';
                phaseSpan.textContent = '准备中';
                line.appendChild(phaseSpan);
                // 进度条
                var barWrap = document.createElement('span');
                barWrap.style.cssText = 'flex:1 1 auto;min-width:120px;';
                var bar = document.createElement('span');
                bar.style.cssText = 'display:block;background:#e0e0e0;border-radius:4px;height:8px;overflow:hidden;';
                var fill = document.createElement('span');
                fill.style.cssText = 'display:block;width:0%;height:100%;background:linear-gradient(90deg,#4caf50,#81c784);transition:width 0.3s;border-radius:4px;';
                bar.appendChild(fill);
                barWrap.appendChild(bar);
                line.appendChild(barWrap);
                // 数字
                var text = document.createElement('span');
                text.style.cssText = 'flex:0 0 100px;font-size:11px;color:#666;text-align:right;white-space:nowrap;';
                text.textContent = '0/0';
                line.appendChild(text);
                var toggle = document.createElement('button');
                toggle.type = 'button';
                toggle.style.cssText = 'flex:0 0 24px;width:24px;height:22px;display:flex;align-items:center;justify-content:center;padding:0;border:1px solid #d0d5dd;border-radius:4px;background:#fff;color:#475467;font-size:12px;cursor:pointer;line-height:1;';
                toggle.textContent = '▾';
                line.appendChild(toggle);

                var message = document.createElement('div');
                message.style.cssText = 'margin-left:151px;margin-right:140px;margin-top:2px;font-size:11px;color:#667085;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
                message.textContent = '';
                row.appendChild(message);
                var history = document.createElement('div');
                history.style.cssText = 'display:none;margin-left:151px;margin-right:140px;margin-top:4px;padding:6px 8px;background:#fff;border:1px solid #eaecf0;border-radius:6px;font-size:11px;';
                row.appendChild(history);
                toggle.addEventListener('click', function() {
                    var open = history.style.display === 'none';
                    history.style.display = open ? 'block' : 'none';
                    toggle.textContent = open ? '▴' : '▾';
                });

                progressContainer.appendChild(row);
                batchRows[batchIndex] = {
                    rowEl: row,
                    labelEl: label,
                    fillEl: fill,
                    textEl: text,
                    phaseEl: phaseSpan,
                    messageEl: message,
                    historyEl: history,
                    phaseHistory: {},
                    currentPhase: '',
                    pct: 0
                };
                return batchRows[batchIndex];
            }

            function _updateBatchRow(batchIndex, phase, completed, total, message) {
                var row = _ensureBatchRow(batchIndex, '', 0);
                _recordPhaseProgress(row, phase, completed, total, message);
                if (phase && !nonTimelinePhases[phase] && row.phaseEl) {
                    row.phaseEl.textContent = phaseLabels[phase] || phase;
                }
                if (message && row.messageEl) {
                    row.messageEl.textContent = message;
                    row.messageEl.title = message;
                }
                if (total > 0) {
                    var pct = _phaseProgressPct(phase, completed, total);
                    if (pct !== null) {
                        row.pct = Math.max(row.pct || 0, pct);
                        row.fillEl.style.width = row.pct + '%';
                    }
                    row.textEl.textContent = completed + '/' + total;
                } else if (total === 0 && completed === 0) {
                    row.textEl.textContent = '0/0';
                }
                // 根据阶段改变颜色
                if (phase === 'simulate') {
                    row.fillEl.style.background = 'linear-gradient(90deg,#ff9800,#ffc107)';
                } else if (phase === 'trade_data') {
                    row.fillEl.style.background = 'linear-gradient(90deg,#2196f3,#64b5f6)';
                } else if (phase === 'membership') {
                    row.fillEl.style.background = 'linear-gradient(90deg,#9c27b0,#ce93d8)';
                } else {
                    row.fillEl.style.background = 'linear-gradient(90deg,#4caf50,#81c784)';
                }
            }

            function _updateGlobalProgress(phase, completed, total, message) {
                // 更新所有行（用于没有 batch_index 的全局进度）
                var keys = Object.keys(batchRows);
                for (var k = 0; k < keys.length; k++) {
                    _updateBatchRow(parseInt(keys[k]), phase, completed, total, message);
                }
            }

            function _syncBatchRows(nextTotal) {
                var existingKeys = Object.keys(batchRows);
                for (var i = 0; i < existingKeys.length; i++) {
                    var idx = parseInt(existingKeys[i]);
                    if (idx >= nextTotal) {
                        var oldRow = batchRows[idx];
                        if (oldRow && oldRow.rowEl && oldRow.rowEl.parentNode) {
                            oldRow.rowEl.parentNode.removeChild(oldRow.rowEl);
                        }
                        delete batchRows[idx];
                    }
                }
                for (var bi = 0; bi < nextTotal; bi++) {
                    _ensureBatchRow(bi, 'Batch ' + (bi + 1), nextTotal);
                }
            }

            function _replayPendingGlobalProgress() {
                if (!pendingGlobalProgress.length || !Object.keys(batchRows).length) return;
                var pending = pendingGlobalProgress;
                pendingGlobalProgress = [];
                for (var p = 0; p < pending.length; p++) {
                    _updateGlobalProgress(
                        pending[p].phase,
                        pending[p].completed,
                        pending[p].total,
                        pending[p].message
                    );
                }
            }

            var data = await runTest.postBatchGroupTest(bulkPayload, function(event, payload) {
                if (event !== 'result' && event !== 'error') {
                    console.log('[SSE frontend] event:', event, 'payload:', JSON.stringify(payload));
                }
                if (event === 'start') {
                    _syncBatchRows(1);
                    _replayPendingGlobalProgress();
                } else if (event === 'progress') {
                    var bi = payload.batch_index;
                    if (bi !== undefined && bi >= 0) {
                        _updateBatchRow(bi, payload.phase, payload.completed || 0, payload.total || 0, payload.message);
                    } else if (!Object.keys(batchRows).length) {
                        pendingGlobalProgress.push({
                            phase: payload.phase,
                            completed: payload.completed || 0,
                            total: payload.total || 0,
                            message: payload.message
                        });
                    } else {
                        _updateGlobalProgress(payload.phase, payload.completed || 0, payload.total || 0, payload.message);
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
