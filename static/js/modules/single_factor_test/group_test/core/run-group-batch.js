/**
 * core/run-group-batch.js — productCoverageBatch progress UI
 *
 * 管理与后端 product_coverage_batch_index 一一对应的运行批次进度条。
 * 每个 productCoverageBatch 在后端由 FactorGroupTester.build_overlap_batches() 确定，
 * 前端通过 SSE 事件中的 product_coverage_batch_index 字段接收进度。
 *
 * 挂载到 GT.groupSettings.runGroupBatch（内部模块，由 run-test.js 调用）。
 *
 * 与 add-group-batch.js 的区别：
 *   - addGroupBatch = UI 列表分组（前端显示用）
 *   - productCoverageBatch = 后端计算批次（与后端 product_coverage_batch_index 一一对应）
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

    // ═══════════════════════════════════════════════════════════════
    // Factory: create a productCoverageBatch progress manager
    // ═══════════════════════════════════════════════════════════════

    /**
     * @param {Object} opts
     * @param {HTMLElement} opts.progressContainer - 进度条容器 DOM 元素
     * @param {Object} [opts.phaseLabels] - 阶段中文标签映射，默认见下方
     * @returns {Object} manager
     */
    function createProductCoverageBatchManager(opts) {
        var progressContainer = opts.progressContainer;
        var phaseLabels = Object.assign({ product_coverage_batch: '批次', info: '', init: '准备' }, opts.phaseLabels || {});
        var nonTimelinePhases = { product_coverage_batch: true, info: true, init: true };

        // phaseOrder: 动态发现，按首次出现顺序排列
        var phaseOrder = [];
        var knownTotalPhases = 0;       // emit_start 告知的总阶段数，优先使用
        var seenPhases = {};            // phase → true（已注册到 phaseOrder）

        function _registerPhase(phase) {
            if (!phase || nonTimelinePhases[phase] || seenPhases[phase]) return;
            seenPhases[phase] = true;
            if (phaseLabels[phase] === undefined) {
                phaseLabels[phase] = phase;
            }
            phaseOrder.push(phase);
        }

        var coverageBatchRows = {};     // coverageBatchIndex → { rowEl, fillEl, textEl, phaseEl, messageEl, ... }
        var totalCoverageBatches = 0;

        // ── phase progress helpers ──

        function _phaseProgressPct(phase, completed, total) {
            if (total <= 0) return null;
            _registerPhase(phase);
            var numPhases = knownTotalPhases > 0 ? knownTotalPhases : Math.max(1, phaseOrder.length);
            var localPct = Math.max(0, Math.min(1, completed / total));
            var phaseIdx = phaseOrder.indexOf(phase);
            if (phaseIdx >= 0) {
                return Math.round(((phaseIdx + localPct) / numPhases) * 100);
            }
            return null;
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

        // ── DOM row management ──

        function _ensureCoverageBatchRow(coverageBatchIndex, coverageBatchLabel, coverageBatchTotal) {
            if (coverageBatchRows[coverageBatchIndex]) {
                var existingLabel = coverageBatchRows[coverageBatchIndex].labelEl;
                if (existingLabel) {
                    existingLabel.textContent = coverageBatchLabel || ('Batch ' + (coverageBatchIndex + 1));
                }
                return coverageBatchRows[coverageBatchIndex];
            }
            var row = document.createElement('div');
            row.style.cssText = 'margin-bottom:6px;';
            var line = document.createElement('div');
            line.style.cssText = 'display:flex;align-items:center;gap:8px;width:100%;';
            row.appendChild(line);
            // 标签
            var label = document.createElement('span');
            label.style.cssText = 'flex:0 0 70px;font-size:12px;font-weight:600;color:#333;white-space:nowrap;';
            label.textContent = coverageBatchLabel || ('Batch ' + (coverageBatchIndex + 1));
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
            coverageBatchRows[coverageBatchIndex] = {
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
            return coverageBatchRows[coverageBatchIndex];
        }

        function _updateCoverageBatchRow(coverageBatchIndex, phase, completed, total, message) {
            var row = _ensureCoverageBatchRow(coverageBatchIndex, '', 0);
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

        // ── Public API ──

        return {
            /** 确保某行存在，返回 row 对象 */
            ensureRow: _ensureCoverageBatchRow,

            /** 更新某行进度 */
            updateRow: _updateCoverageBatchRow,

            /** 更新所有行（全局进度，无 coverage_batch_index 时用） */
            updateAllRows: function(phase, completed, total, message) {
                var keys = Object.keys(coverageBatchRows);
                for (var k = 0; k < keys.length; k++) {
                    _updateCoverageBatchRow(parseInt(keys[k]), phase, completed, total, message);
                }
            },

            /** 标记所有行完成/失败 */
            markAllDone: function(done, message) {
                var keys = Object.keys(coverageBatchRows);
                for (var i = 0; i < keys.length; i++) {
                    var row = coverageBatchRows[keys[i]];
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
            },

            /** 同步行数到 nextTotal */
            syncRows: function(nextTotal) {
                var existingKeys = Object.keys(coverageBatchRows);
                for (var i = 0; i < existingKeys.length; i++) {
                    var idx = parseInt(existingKeys[i]);
                    if (idx >= nextTotal) {
                        var row = coverageBatchRows[idx];
                        if (row && row.rowEl && row.rowEl.parentNode) {
                            row.rowEl.parentNode.removeChild(row.rowEl);
                        }
                        delete coverageBatchRows[idx];
                    }
                }
                totalCoverageBatches = nextTotal;
            },

            /** 获取某行数据 */
            getRow: function(idx) { return coverageBatchRows[idx] || null; },

            /** 获取所有行索引 */
            getIndices: function() { return Object.keys(coverageBatchRows).map(Number); },

            /** 获取批次数 */
            getTotal: function() { return totalCoverageBatches; },

            /** 设置后端告知的总阶段数（优先于动态发现） */
            setTotalPhases: function(n) {
                if (n > 0) knownTotalPhases = n;
            },

            /** 预注册阶段列表（后端 emit_start 告知的完整 phase 顺序） */
            registerPhases: function(phases) {
                if (!Array.isArray(phases)) return;
                for (var pi = 0; pi < phases.length; pi++) {
                    _registerPhase(phases[pi]);
                }
                knownTotalPhases = phases.length;
                console.log('[batchMgr] registerPhases:', JSON.stringify(phases), 'knownTotalPhases:', knownTotalPhases);
            },

            /** 设置阶段标签（后端告知，替换默认） */
            setPhaseLabels: function(labels) {
                if (!labels || typeof labels !== 'object') return;
                var keys = Object.keys(labels);
                for (var i = 0; i < keys.length; i++) {
                    phaseLabels[keys[i]] = labels[keys[i]];
                }
                console.log('[batchMgr] setPhaseLabels:', JSON.stringify(phaseLabels));
            },

            /** 阶段标签 */
            getPhaseLabels: function() { return phaseLabels; },
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
