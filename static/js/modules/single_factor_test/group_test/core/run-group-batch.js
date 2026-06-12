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
            case 'serialize':   return 'linear-gradient(90deg,#795548,#a1887f)';
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

        /** 计算阶段全局进度百分比，永不回退。
         *  按各阶段 total 加权分配进度条区域（非均匀）。
         *  Cap 规则：某个阶段 total 超过其他所有总和 2 倍时，capped 为 2×其他总和。 */
        function _computePct(row, phase, completed, total) {
            if (phase === 'info' || skipPhases[phase]) return row.pct;

            // 动态记录该 phase 的 total（取最大值）
            if (total > 0) {
                var prev = row._phaseTotalMax[phase] || 0;
                if (total > prev) row._phaseTotalMax[phase] = total;
            }

            var allTotals = row._phaseTotalMax;
            var phaseKeys = Object.keys(allTotals);
            // 需要至少 2 个阶段才有加权意义
            if (phaseKeys.length < 2) {
                // 回退到均匀分配
                var numPhases = knownTotalPhases > 0 ? knownTotalPhases : phaseOrder.length;
                if (numPhases <= 0) return row.pct;
                var phaseIdx = phaseOrder.indexOf(phase);
                if (phaseIdx < 0) {
                    _registerPhase(phase);
                    phaseIdx = phaseOrder.indexOf(phase);
                    numPhases = knownTotalPhases > 0 ? knownTotalPhases : Math.max(1, phaseOrder.length);
                }
                if (phaseIdx < 0) return row.pct;
                var localPct = total > 0 ? Math.max(0, Math.min(1, completed / total)) : 0;
                var newPct = Math.round(((phaseIdx + localPct) / numPhases) * 100);
                if (newPct > (row.pct || 0)) row.pct = newPct;
                return row.pct;
            }

            // --- 加权计算 ---
            // 1) 计算原始权重 = 各 phase 的 total
            // 2) 检测是否有 phase 需要 cap
            var sumAll = 0;
            for (var k = 0; k < phaseKeys.length; k++) {
                sumAll += allTotals[phaseKeys[k]];
            }
            var weights = {};
            for (var w = 0; w < phaseKeys.length; w++) {
                var pk = phaseKeys[w];
                var t = allTotals[pk];
                var sumOthers = sumAll - t;
                // Cap: 如果 t > 2 * sumOthers，则 capped = 2 * sumOthers
                weights[pk] = (sumOthers > 0 && t > 2 * sumOthers) ? 2 * sumOthers : t;
            }

            // 3) 计算加权占比
            var weightSum = 0;
            var wKeys = Object.keys(weights);
            for (var ws = 0; ws < wKeys.length; ws++) {
                weightSum += weights[wKeys[ws]];
            }
            if (weightSum <= 0) return row.pct;

            // 4) 计算当前 phase 之前的累计权重占比 + 当前 phase 内进度
            var cumWeightBefore = 0;
            for (var j = 0; j < phaseOrder.length; j++) {
                var pj = phaseOrder[j];
                if (pj === phase) break;
                if (weights[pj] !== undefined) cumWeightBefore += weights[pj];
            }
            var curWeight = weights[phase] || 0;
            var localFrac = total > 0 ? Math.max(0, Math.min(1, completed / total)) : 0;
            var weightedPct = Math.round(((cumWeightBefore + curWeight * localFrac) / weightSum) * 100);

            if (weightedPct > (row.pct || 0)) row.pct = weightedPct;
            return row.pct;
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
                    message: _escapeProgressHtml(h.message || '')
                });
            }
            if (!items.length) {
                row.historyEl.innerHTML = '<div style="color:#98a2b3;padding:4px 0;">暂无阶段记录</div>';
                return;
            }
            var html = items.map(function(it) {
                var count = it.total > 0 ? (it.completed + '/' + it.total) : '--';
                var status = it.done ? '✓ 已完成' : '◷ 进行中';
                var color = it.done ? '#12a150' : '#0078d4';
                return '<div style="display:grid;grid-template-columns:80px minmax(12ch,max-content) 70px minmax(0,1fr);gap:8px;align-items:center;padding:2px 0;font-size:11px;">'
                    + '<span style="font-weight:600;color:#475467;">' + it.label + '</span>'
                    + '<span style="color:#667085;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;">' + count + '</span>'
                    + '<span style="color:' + color + ';white-space:nowrap;">' + status + '</span>'
                    + '<span style="color:#667085;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="' + it.message + '">' + it.message + '</span>'
                    + '</div>';
            }).join('');
            row.historyEl.innerHTML = html;
        }

        function _recordPhaseProgress(row, phase, completed, total, message) {
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
            var isNewDone = total > 0 && completed >= total;
            // 保证不回退：completed/total 只增不减
            row.phaseHistory[phase] = {
                completed: Math.max(existing.completed || 0, completed || 0),
                total: Math.max(existing.total || 0, total || 0),
                message: message || existing.message || '',
                done: !!(isNewDone || existing.done)
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

        function _updateCoverageBatchRow(index, phase, completed, total, message) {
            console.log('[GT-BATCH] updateRow | idx=' + index
                + ' | phase=' + phase
                + ' | completed=' + completed
                + ' | total=' + total
                + ' | phaseOrder_len=' + phaseOrder.length
                + ' | knownTotalPhases=' + knownTotalPhases
                + ' | skip=' + !!skipPhases[phase]
                + ' | msg=' + (message || '').substring(0, 80));
            var row = _ensureCoverageBatchRow(index, '');

            _registerPhase(phase);
            _computePct(row, phase, completed, total);
            _recordPhaseProgress(row, phase, completed, total, message);

            // 更新阶段名
            if (phase && !skipPhases[phase] && row.phaseEl) {
                row.phaseEl.textContent = phaseLabels[phase] || phase;
            }
            // 更新消息行
            if (message && row.messageEl) {
                row.messageEl.textContent = message;
                row.messageEl.title = message;
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
            console.log('[GT-BATCH] updateRow_done | idx=' + index + ' | newPct=' + row.pct + ' | phaseOrder=' + JSON.stringify(phaseOrder));
        }

        // ---- Public API ----
        return {
            ensureRow: _ensureCoverageBatchRow,
            updateRow: _updateCoverageBatchRow,

            updateAllRows: function(phase, completed, total, message) {
                var keys = Object.keys(coverageBatchRows);
                for (var k = 0; k < keys.length; k++) {
                    _updateCoverageBatchRow(parseInt(keys[k]), phase, completed, total, message);
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
