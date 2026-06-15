/**
 * core/run-group-batch.js — productCoverageBatch progress UI
 *
 * 管理与后端 product_coverage_batch_index 一一对应的运行批次进度条。
 * 每个 productCoverageBatch 在后端由 FactorGroupTester.build_overlap_batches() 确定，
 * 前端通过 SSE 事件中的 product_coverage_batch_index 字段接收进度。
 *
 * 进度条设计：
 * - 单条渐变色进度条，颜色随当前阶段变化
 * - 下拉列表（点击 ▼ 展开）显示每阶段的完成详情
 * - 布局：Batch标签 + 阶段名 + 渐变色进度条 + 计数 + ▼按钮
 * - 进度永不回退（pct 只增不减）
 *
 * 挂载到 GT.groupSettings.runGroupBatch（内部模块，由 run-test.js 调用）。
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    // ═══════════════════════════════════════════════════════════════
    // Helpers
    // ═══════════════════════════════════════════════════════════════

    function _escapeProgressHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    /** 根据阶段返回渐变色 */
    function _phaseColor(phase) {
        switch (phase) {
            case 'simulate':    return 'linear-gradient(90deg,#ff9800,#ffc107)';
            case 'trade_data':  return 'linear-gradient(90deg,#2196f3,#64b5f6)';
            case 'membership':  return 'linear-gradient(90deg,#9c27b0,#ce93d8)';
            case 'liquidity':   return 'linear-gradient(90deg,#00bcd4,#4dd0e1)';
            case 'serialize':   return 'linear-gradient(90deg,#6366f1,#a5b4fc)';
            case 'batch':       return 'linear-gradient(90deg,#607d8b,#90a4ae)';
            default:            return 'linear-gradient(90deg,#4caf50,#81c784)';
        }
    }

    // ═══════════════════════════════════════════════════════════════
    // Factory
    // ═══════════════════════════════════════════════════════════════

    function createProductCoverageBatchManager(opts) {
        var progressContainer = opts.progressContainer;
        var phaseLabels = Object.assign({ init: '准备' }, opts.phaseLabels || {});
        /** { phaseKey: { subStepKey: label, ... } }  — phases 元数据中的 sub_steps */
        var subStepLabels = opts.subStepLabels || {};
        var skipPhases = { info: true, product_coverage_batch: true, init: true };
        // 不在下拉历史中显示的阶段（但仍参与进度条更新）
        var hideInHistory = { batch: true };

        var phaseOrder = [];           // 有序 phase key 列表
        var seenPhases = {};           // 去重
        var knownTotalPhases = 0;      // emit_start 告知的总阶段数

        var coverageBatchRows = {};
        var totalCoverageBatches = 0;

        // ---- phase registration ----
        function _registerPhase(phase) {
            if (!phase || skipPhases[phase] || seenPhases[phase]) return;
            seenPhases[phase] = true;
            if (phaseLabels[phase] === undefined) phaseLabels[phase] = phase;
            phaseOrder.push(phase);
        }

        /** 设置子步骤标签（由 run-test.js 传入 phases 元数据中的 sub_steps） */
        function setSubStepLabels(labels) {
            subStepLabels = Object.assign({}, labels || {});
        }

        /** 计算阶段全局进度百分比，永不回退。
         *  均匀分配：每个非隐藏阶段占据相等的进度条宽度。
         *  阶段内按 completed/total 线性填充。
         *  当 phase 有子步骤时，completed/total 按所有子步骤聚合计算。 */
        function _computePct(row, phase, completed, total) {
            if (phase === 'info' || skipPhases[phase]) return row.pct;

            // 非隐藏阶段列表（按 phaseOrder）
            var visiblePhases = [];
            for (var i = 0; i < phaseOrder.length; i++) {
                if (!skipPhases[phaseOrder[i]] && !hideInHistory[phaseOrder[i]]) {
                    visiblePhases.push(phaseOrder[i]);
                }
            }
            if (visiblePhases.indexOf(phase) < 0 && !skipPhases[phase] && !hideInHistory[phase]) {
                visiblePhases.push(phase);
            }
            var numPhases = visiblePhases.length;
            if (numPhases <= 0) return row.pct;

            var phaseIdx = visiblePhases.indexOf(phase);
            if (phaseIdx < 0) return row.pct;

            // 每个阶段占 1/numPhases 的宽度
            var segmentWidth = 100 / numPhases;
            var localFrac;
            if (row.phaseHistory[phase] && row.phaseHistory[phase].subSteps && !_subStepsEmpty(row.phaseHistory[phase].subSteps)) {
                // 有子步骤：聚合所有子步骤的完成度
                var agg = _aggregateSubSteps(row.phaseHistory[phase].subSteps);
                localFrac = agg.total > 0 ? Math.max(0, Math.min(1, agg.completed / agg.total)) : 0;
            } else {
                localFrac = total > 0 ? Math.max(0, Math.min(1, completed / total)) : 0;
            }
            var newPct = Math.round((phaseIdx + localFrac) * segmentWidth);
            if (newPct > (row.pct || 0)) row.pct = newPct;
            return row.pct;
        }

        /** 聚合子步骤：total = 所有子步骤 total 之和，completed = 所有已完成子步骤 total + 当前进行中子步骤的 completed */
        function _aggregateSubSteps(subSteps) {
            var aggTotal = 0, aggCompleted = 0;
            var keys = Object.keys(subSteps);
            for (var k = 0; k < keys.length; k++) {
                var ss = subSteps[keys[k]];
                aggTotal += ss.total || 0;
                if (ss.done) {
                    aggCompleted += ss.total || 0;
                } else {
                    aggCompleted += ss.completed || 0;
                }
            }
            return { completed: aggCompleted, total: aggTotal };
        }

        function _subStepsEmpty(subSteps) {
            return Object.keys(subSteps).length === 0;
        }

        // ---- 下拉历史面板 ----
        function _renderPhaseHistory(row) {
            if (!row.historyEl) return;
            var items = [];
            for (var j = 0; j < phaseOrder.length; j++) {
                var p = phaseOrder[j];
                var h = row.phaseHistory[p];
                if (!h || hideInHistory[p]) continue;
                // 只显示已完成的阶段 + 当前进行中的阶段（未开始的跳过）
                if (!h.done && p !== row.currentPhase) continue;
                items.push({
                    phase: p,
                    label: _escapeProgressHtml(phaseLabels[p] || p),
                    completed: h.completed,
                    total: h.total,
                    done: h.done,
                    message: _escapeProgressHtml(h.message || ''),
                    subSteps: h.subSteps || null,
                    subStepKeys: h.subStepKeys || null
                });
            }
            if (!items.length) {
                row.historyEl.innerHTML = '<div style="color:#98a2b3;padding:4px 0;">暂无阶段记录</div>';
                return;
            }
            var htmlParts = [];
            for (var ii = 0; ii < items.length; ii++) {
                var it = items[ii];
                var count = it.total > 0 ? (it.completed + '/' + it.total) : '--';
                var status = it.done ? '✓ 已完成' : '◷ 进行中';
                var color = it.done ? '#12a150' : '#0078d4';
                htmlParts.push(
                    '<div style="display:grid;grid-template-columns:80px 100px 70px minmax(0,1fr);gap:8px;align-items:center;padding:2px 0;font-size:11px;">'
                    + '<span style="font-weight:600;color:#475467;">' + it.label + '</span>'
                    + '<span style="color:#667085;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;overflow:hidden;text-overflow:ellipsis;" title="' + count + '">' + count + '</span>'
                    + '<span style="color:' + color + ';white-space:nowrap;">' + status + '</span>'
                    + '<span style="color:#667085;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="' + it.message + '">' + it.message + '</span>'
                    + '</div>'
                );

                // 渲染子步骤（缩进显示）
                if (it.subSteps && it.subStepKeys) {
                    for (var sk = 0; sk < it.subStepKeys.length; sk++) {
                        var skey = it.subStepKeys[sk];
                        var ss = it.subSteps[skey];
                        if (!ss) continue;
                        var phaseSubs = subStepLabels[it.phase] || {};
                        var ssLabel = _escapeProgressHtml(phaseSubs[skey] || skey);
                        var ssCount = ss.total > 0 ? (ss.completed + '/' + ss.total) : '--';
                        var ssDone = ss.total > 0 && ss.completed >= ss.total;
                        var ssStatus = ssDone ? '✓' : (it.done ? '✓' : '◷');
                        var ssColor = ssDone ? '#12a150' : (it.done ? '#12a150' : '#0078d4');
                        var ssMsg = _escapeProgressHtml(ss.message || '');
                        htmlParts.push(
                            '<div style="display:grid;grid-template-columns:80px 100px 70px minmax(0,1fr);gap:8px;align-items:center;padding:1px 0;font-size:10px;color:#667085;">'
                            + '<span style="padding-left:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="' + ssLabel + '">└ ' + ssLabel + '</span>'
                            + '<span style="text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;" title="' + ssCount + '">' + ssCount + '</span>'
                            + '<span style="color:' + ssColor + ';white-space:nowrap;">' + ssStatus + '</span>'
                            + '<span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="' + ssMsg + '">' + ssMsg + '</span>'
                            + '</div>'
                        );
                    }
                }
            }
            row.historyEl.innerHTML = htmlParts.join('');
        }

        function _recordPhaseProgress(row, phase, completed, total, message, subStep) {
            if (!phase || skipPhases[phase]) return;

            // info 类型：不创建新条目，只更新消息
            if (phase === 'info') {
                if (row.currentPhase && row.phaseHistory[row.currentPhase]) {
                    var cur = row.phaseHistory[row.currentPhase];
                    cur.message = message || cur.message || '';
                    _renderPhaseHistory(row);
                }
                return;
            }

            // 隐藏阶段：不记录历史，但标记前一个阶段完成
            if (hideInHistory[phase]) {
                if (row.currentPhase && row.phaseHistory[row.currentPhase]) {
                    row.phaseHistory[row.currentPhase].done = true;
                }
                row.currentPhase = phase;
                _renderPhaseHistory(row);
                return;
            }

            // 切换阶段时，标记上一个阶段完成
            if (row.currentPhase && row.currentPhase !== phase && row.phaseHistory[row.currentPhase]) {
                row.phaseHistory[row.currentPhase].done = true;
            }
            row.currentPhase = phase;

            var existing = row.phaseHistory[phase] || {};
            var newCompleted = Math.max(existing.completed || 0, completed || 0);
            var newTotal = Math.max(existing.total || 0, total || 0);
            // 如果 phase 被重新进入（如 simulate 在多个 batch 中重复），done 必须重置
            var isNowDone = newTotal > 0 && newCompleted >= newTotal;
            // 跳过类消息（total=0 表示"已有缓存跳过"）不覆盖已有的有意义消息
            var skipLike = (total != null && total === 0) || (message && message.indexOf('跳过') >= 0);
            var bestMessage = existing.message || '';
            if (message && (!skipLike || !bestMessage)) {
                bestMessage = message;
            }

            // 子步骤处理
            var existingSubs = existing.subSteps || {};
            var existingSubKeys = existing.subStepKeys || [];
            if (subStep) {
                var oldSub = existingSubs[subStep] || {};
                var subComp = Math.max(oldSub.completed || 0, completed || 0);
                var subTot = Math.max(oldSub.total || 0, total || 0);
                var subDone = subTot > 0 && subComp >= subTot;
                existingSubs[subStep] = {
                    completed: subComp,
                    total: subTot,
                    done: subDone,
                    message: message || oldSub.message || ''
                };
                if (existingSubKeys.indexOf(subStep) < 0) {
                    existingSubKeys.push(subStep);
                }

                // 有子步骤时，阶段的 completed/total 按聚合计算
                var agg = _aggregateSubSteps(existingSubs);
                newCompleted = agg.completed;
                newTotal = agg.total;
                isNowDone = newTotal > 0 && newCompleted >= newTotal;
            }

            row.phaseHistory[phase] = {
                completed: newCompleted,
                total: newTotal,
                message: bestMessage,
                done: isNowDone,
                subSteps: existingSubs,
                subStepKeys: existingSubKeys.length > 0 ? existingSubKeys : null
            };
            _renderPhaseHistory(row);
        }

        // ---- DOM row management ----
        function _ensureCoverageBatchRow(index, label) {
            if (coverageBatchRows[index]) {
                var r = coverageBatchRows[index];
                if (label && r.labelEl) r.labelEl.textContent = label;
                return r;
            }

            var row = document.createElement('div');
            row.style.cssText = 'margin-bottom:6px;';

            // 第一行：标签 + 阶段名 + 进度条 + 计数 + 展开按钮
            var line = document.createElement('div');
            line.style.cssText = 'display:flex;align-items:center;gap:8px;width:100%;';

            // 标签（左侧信息栏）
            var labelEl = document.createElement('span');
            labelEl.style.cssText = 'flex:0 0 70px;font-size:12px;font-weight:600;color:#333;white-space:nowrap;';
            labelEl.textContent = label || ('Batch ' + (index + 1));
            line.appendChild(labelEl);

            // 阶段名
            var phaseEl = document.createElement('span');
            phaseEl.style.cssText = 'flex:0 0 65px;font-size:11px;color:#888;white-space:nowrap;';
            phaseEl.textContent = '准备中';
            line.appendChild(phaseEl);

            // 单条渐变色进度条
            var barWrap = document.createElement('span');
            barWrap.style.cssText = 'flex:1 1 auto;min-width:120px;';
            var bar = document.createElement('span');
            bar.style.cssText = 'display:block;background:#e0e0e0;border-radius:4px;height:8px;overflow:hidden;';
            var fill = document.createElement('span');
            fill.style.cssText = 'display:block;width:0%;height:100%;background:linear-gradient(90deg,#4caf50,#81c784);transition:width 0.3s;border-radius:4px;';
            bar.appendChild(fill);
            barWrap.appendChild(bar);
            line.appendChild(barWrap);

            // 计数
            var textEl = document.createElement('span');
            textEl.style.cssText = 'flex:0 0 100px;font-size:11px;color:#666;text-align:right;white-space:nowrap;';
            textEl.textContent = '0/0';
            line.appendChild(textEl);

            // 展开按钮
            var toggle = document.createElement('button');
            toggle.type = 'button';
            toggle.style.cssText = 'flex:0 0 24px;width:24px;height:22px;display:flex;align-items:center;justify-content:center;padding:0;border:1px solid #d0d5dd;border-radius:4px;background:#fff;color:#475467;font-size:12px;cursor:pointer;line-height:1;';
            toggle.textContent = '▾';
            line.appendChild(toggle);

            row.appendChild(line);

            // 消息行
            var messageEl = document.createElement('div');
            messageEl.style.cssText = 'margin-left:143px;margin-right:32px;margin-top:2px;font-size:11px;color:#667085;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
            messageEl.textContent = '';
            row.appendChild(messageEl);

            // 下拉历史面板（默认隐藏）
            var historyEl = document.createElement('div');
            historyEl.style.cssText = 'display:none;margin-left:143px;margin-right:32px;margin-top:4px;padding:6px 8px;background:#fff;border:1px solid #eaecf0;border-radius:6px;font-size:11px;';
            row.appendChild(historyEl);

            toggle.addEventListener('click', function() {
                var open = historyEl.style.display === 'none';
                historyEl.style.display = open ? 'block' : 'none';
                toggle.textContent = open ? '▴' : '▾';
            });

            progressContainer.appendChild(row);

            var newRow = {
                rowEl: row,
                labelEl: labelEl,
                fillEl: fill,
                textEl: textEl,
                phaseEl: phaseEl,
                messageEl: messageEl,
                historyEl: historyEl,
                phaseHistory: {},
                currentPhase: '',
                pct: 0,
                _phaseTotalMax: {}   // phase -> max total seen（用于加权进度条）
            };
            coverageBatchRows[index] = newRow;
            return newRow;
        }

        function _updateCoverageBatchRow(index, phase, completed, total, message, subStep) {
            var row = _ensureCoverageBatchRow(index, '');

            _registerPhase(phase);
            _computePct(row, phase, completed, total);
            _recordPhaseProgress(row, phase, completed, total, message, subStep);

            // 更新阶段名
            if (phase && !skipPhases[phase] && row.phaseEl) {
                row.phaseEl.textContent = phaseLabels[phase] || phase;
            }
            // 更新消息行：如果有子步骤，显示 "阶段名 › 子步骤标签：消息"
            if (row.messageEl) {
                var displayMsg = message || '';
                if (subStep && phase) {
                    var phaseSubs = subStepLabels[phase] || {};
                    var subLabel = phaseSubs[subStep] || subStep;
                    displayMsg = (phaseLabels[phase] || phase) + ' › ' + subLabel + (message ? '：' + message : '');
                }
                if (displayMsg) {
                    row.messageEl.textContent = displayMsg;
                    row.messageEl.title = displayMsg;
                }
            }
            // 更新进度条
            if (!skipPhases[phase] && row.fillEl) {
                row.fillEl.style.width = row.pct + '%';
                row.fillEl.style.background = _phaseColor(phase);
            }
            // 更新计数
            if (total > 0) {
                row.textEl.textContent = completed + '/' + total;
            }
        }

        // ---- Public API ----
        return {
            ensureRow: _ensureCoverageBatchRow,
            updateRow: _updateCoverageBatchRow,

            updateAllRows: function(phase, completed, total, message, subStep) {
                var keys = Object.keys(coverageBatchRows);
                for (var k = 0; k < keys.length; k++) {
                    _updateCoverageBatchRow(parseInt(keys[k]), phase, completed, total, message, subStep);
                }
            },

            markAllDone: function(success, message) {
                var indices = Object.keys(coverageBatchRows);
                for (var i = 0; i < indices.length; i++) {
                    var row = coverageBatchRows[indices[i]];
                    if (!row) continue;
                    // 标记当前阶段完成
                    if (row.currentPhase && row.phaseHistory[row.currentPhase]) {
                        row.phaseHistory[row.currentPhase].done = !!success;
                        if (message) row.phaseHistory[row.currentPhase].message = message;
                    }
                    if (success) {
                        row.pct = 100;
                        row.fillEl.style.width = '100%';
                        row.fillEl.style.background = 'linear-gradient(90deg,#12a150,#4caf50)';
                        row.phaseEl.textContent = '✓';
                        row.phaseEl.style.color = '#12a150';
                        row.textEl.textContent = '完成';
                        // 完成后隐藏消息行，只保留左侧标签 + 进度条 + 计数
                        if (row.messageEl) {
                            row.messageEl.style.display = 'none';
                        }
                    } else {
                        row.phaseEl.textContent = '✗';
                        row.phaseEl.style.color = '#d92d20';
                        row.fillEl.style.background = 'linear-gradient(90deg,#d92d20,#f97066)';
                    }
                    if (message && row.messageEl) {
                        row.messageEl.textContent = message;
                        row.messageEl.title = message;
                        row.messageEl.style.display = '';
                    }
                    _renderPhaseHistory(row);
                    // 自动展开失败的历史
                    if (!success && row.historyEl) {
                        row.historyEl.style.display = 'block';
                        var btn = row.rowEl && row.rowEl.querySelector('button');
                        if (btn) btn.textContent = '▴';
                    }
                }
            },

            syncRows: function(nextTotal) {
                var existingKeys = Object.keys(coverageBatchRows);
                // 只删除超出范围的旧行，保留范围内的行（含其 phaseHistory 和 pct）
                for (var i = 0; i < existingKeys.length; i++) {
                    var idx = parseInt(existingKeys[i]);
                    if (idx >= nextTotal) {
                        var r = coverageBatchRows[idx];
                        if (r && r.rowEl && r.rowEl.parentNode) {
                            r.rowEl.parentNode.removeChild(r.rowEl);
                        }
                        delete coverageBatchRows[idx];
                    }
                }
                totalCoverageBatches = nextTotal;
                // 只创建缺失的行
                for (var j = 0; j < nextTotal; j++) {
                    _ensureCoverageBatchRow(j, '');
                }
            },

            getRow: function(idx) { return coverageBatchRows[idx] || null; },

            getIndices: function() { return Object.keys(coverageBatchRows).map(Number); },

            getTotal: function() { return totalCoverageBatches; },

            /** 设置后端告知的总阶段数（优先于动态发现） */
            setTotalPhases: function(n) {
                if (n > 0) knownTotalPhases = n;
            },

            /** 注册阶段列表（emit_start 告知）。
             *  多次调用安全（seenPhases 去重），且总是用后端告知的 phaseOrder
             *  长度更新 knownTotalPhases。 */
            registerPhases: function(phases) {
                if (!Array.isArray(phases)) return;
                for (var pi = 0; pi < phases.length; pi++) {
                    var p = phases[pi];
                    if (!p || skipPhases[p] || seenPhases[p]) continue;
                    _registerPhase(p);
                }
                // 总是用最新的后端告知的阶段数覆盖（可能比动态发现的多）
                if (phaseOrder.length > 0) {
                    knownTotalPhases = phaseOrder.length;
                }
            },

            setPhaseLabels: function(labels) {
                if (!labels || typeof labels !== 'object') return;
                var keys = Object.keys(labels);
                for (var i = 0; i < keys.length; i++) {
                    phaseLabels[keys[i]] = labels[keys[i]];
                }
                var indices = Object.keys(coverageBatchRows);
                for (var j = 0; j < indices.length; j++) {
                    _renderPhaseHistory(coverageBatchRows[indices[j]]);
                }
            },

            setSubStepLabels: setSubStepLabels,

            getPhaseLabels: function() { return phaseLabels; },

            // 诊断暴露
            _debug_phaseOrder: phaseOrder,
            get _debug_knownTotalPhases() { return knownTotalPhases; },
            get _debug_coverageBatchRows() { return coverageBatchRows; },
            get _debug_phaseLabels() { return phaseLabels; },
        };
    }

    // ═══════════════════════════════════════════════════════════════
    // Export
    // ═══════════════════════════════════════════════════════════════

    GT.groupSettings = GT.groupSettings || {};
    GT.groupSettings.runGroupBatch = {
        createManager: createProductCoverageBatchManager,
    };

})();
