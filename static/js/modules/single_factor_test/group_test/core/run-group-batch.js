/**
 * core/run-group-batch.js — productCoverageBatch progress UI
 *
 * 管理与后端 product_coverage_batch_index 一一对应的运行批次进度条。
 * 每个 productCoverageBatch 在后端由 FactorGroupTester.build_overlap_batches() 确定，
 * 前端通过 SSE 事件中的 product_coverage_batch_index 字段接收进度。
 *
 * 进度条设计：
 * - 使用多段分段进度条，每段代表一个阶段
 * - 段宽度按 flex-grow 权重分配：第 i 段权重 = 2^i（后面阶段预留更多空间）
 * - 新增阶段时，已完成占比不变，重新分配剩余空间的段权重
 * - 进度条永不回退（completed/total 只增不减）
 * - 下方直接打印阶段完成情况，无需点展开
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

    // flex-grow 权重：阶段 i 的权重 = 2^i，前段小后段大
    function _phaseWeight(i) { return Math.pow(2, i); }

    function _phaseColor(phase) {
        switch (phase) {
            case 'simulate': return 'linear-gradient(90deg,#ff9800,#ffc107)';
            case 'trade_data': return 'linear-gradient(90deg,#2196f3,#64b5f6)';
            case 'membership': return 'linear-gradient(90deg,#9c27b0,#ce93d8)';
            case 'liquidity': return 'linear-gradient(90deg,#00bcd4,#4dd0e1)';
            case 'serialize': return 'linear-gradient(90deg,#795548,#a1887f)';
            case 'batch': return 'linear-gradient(90deg,#607d8b,#90a4ae)';
            default: return 'linear-gradient(90deg,#4caf50,#81c784)';
        }
    }

    // ═══════════════════════════════════════════════════════════════
    // Factory
    // ═══════════════════════════════════════════════════════════════

    function createProductCoverageBatchManager(opts) {
        var progressContainer = opts.progressContainer;
        var phaseLabels = Object.assign({ init: '准备' }, opts.phaseLabels || {});
        var skipPhases = { info: true, product_coverage_batch: true, init: true };

        var phaseOrder = [];           // 有序 phase key 列表
        var seenPhases = {};           // 去重
        var phaseMaxCompleted = {};    // phase -> 最大 completed（不回退）
        var phaseMaxTotal = {};        // phase -> 最大 total
        var phaseDone = {};            // phase -> completed >= total

        var coverageBatchRows = {};
        var totalCoverageBatches = 0;

        // ---- phase registration ----
        function _registerPhase(phase) {
            if (!phase || skipPhases[phase] || seenPhases[phase]) return;
            seenPhases[phase] = true;
            if (phaseLabels[phase] === undefined) phaseLabels[phase] = phase;
            phaseOrder.push(phase);
        }

        // ---- 重建所有行的分段进度条 ----
        function _rebuildAllPhaseBars() {
            var keys = Object.keys(coverageBatchRows).map(Number);
            for (var k = 0; k < keys.length; k++) {
                _rebuildPhaseBar(coverageBatchRows[keys[k]]);
            }
        }

        function _rebuildPhaseBar(row) {
            var container = row.barContainer;
            if (!container) return;
            container.innerHTML = '';

            var segs = {};
            row.phaseSegments = segs;

            if (!phaseOrder.length) {
                var empty = document.createElement('span');
                empty.style.cssText = 'display:block;width:100%;height:100%;background:#e0e0e0;border-radius:3px;';
                container.appendChild(empty);
                return;
            }

            for (var i = 0; i < phaseOrder.length; i++) {
                var p = phaseOrder[i];
                var w = _phaseWeight(i);
                var cm = phaseMaxCompleted[p] || 0;
                var tt = phaseMaxTotal[p] || 1;
                var localDone = Math.min(1, cm / tt);
                var isFirst = i === 0;
                var isLast = i === phaseOrder.length - 1;

                var seg = document.createElement('span');
                seg.style.flexGrow = String(w);
                seg.style.flexBasis = '0';
                seg.style.display = 'block';
                seg.style.height = '100%';
                seg.style.float = 'left';
                seg.style.background = '#e8ecf0';
                seg.style.boxSizing = 'border-box';
                seg.style.borderRight = isLast ? '0' : '1px solid #fff';
                seg.style.borderRadius = isFirst ? '3px 0 0 3px' : isLast ? '0 3px 3px 0' : '0';
                seg.style.overflow = 'hidden';
                seg.style.position = 'relative';

                var fill = document.createElement('span');
                fill.style.display = 'block';
                fill.style.height = '100%';
                fill.style.width = (localDone * 100) + '%';
                fill.style.background = _phaseColor(p);
                fill.style.borderRadius = 'inherit';
                fill.style.transition = 'width 0.3s';
                seg.appendChild(fill);

                segs[p] = { el: seg, fill: fill };
                container.appendChild(seg);
            }
        }

        function _updatePhaseSegment(row, phase) {
            var segs = row.phaseSegments;
            if (!segs || !segs[phase]) return;
            var cm = phaseMaxCompleted[phase] || 0;
            var tt = phaseMaxTotal[phase] || 1;
            segs[phase].fill.style.width = (Math.min(1, cm / tt) * 100) + '%';
        }

        // ---- 阶段进度记录 ----
        function _recordPhaseProgress(row, phase, completed, total, message) {
            if (!phase || skipPhases[phase]) return;

            // 保证不回退：只增不减
            var prevC = phaseMaxCompleted[phase] || 0;
            var prevT = phaseMaxTotal[phase] || 0;
            if (completed > prevC) phaseMaxCompleted[phase] = completed;
            if (total > prevT) phaseMaxTotal[phase] = total;
            if (total > 0 && completed >= total) phaseDone[phase] = true;

            _registerPhase(phase);
            row.currentPhase = phase;
            _updatePhaseSegment(row, phase);
            _renderPhaseStatus(row);
            _updateGlobalPct(row);
        }

        function _updateGlobalPct(row) {
            if (!phaseOrder.length) return;
            var accum = 0;
            for (var i = 0; i < phaseOrder.length; i++) {
                var p = phaseOrder[i];
                var cm = phaseMaxCompleted[p] || 0;
                var tt = phaseMaxTotal[p] || 1;
                accum += Math.min(1, cm / tt);
            }
            row.pct = Math.round((accum / phaseOrder.length) * 100);
        }

        // ---- 阶段状态面板（始终可见，在进度条下方） ----
        function _renderPhaseStatus(row) {
            if (!row.statusEl) return;
            var html = '';
            for (var i = 0; i < phaseOrder.length; i++) {
                var p = phaseOrder[i];
                var label = _escapeProgressHtml(phaseLabels[p] || p);
                var cm = phaseMaxCompleted[p] || 0;
                var tt = phaseMaxTotal[p] || 0;
                var done = phaseDone[p];
                var count = tt > 0 ? (cm + '/' + tt) : '—';
                var color = done ? '#12a150' : (cm > 0 ? '#0078d4' : '#98a2b3');
                var icon = done ? '✓' : (cm > 0 ? '◷' : '○');
                html += '<span style="display:inline-flex;align-items:center;gap:3px;margin-right:14px;font-size:11px;color:' + color + ';white-space:nowrap;">'
                    + '<span style="font-weight:600;">' + label + '</span>'
                    + '<span style="font-variant-numeric:tabular-nums;">' + count + '</span>'
                    + '<span style="font-size:10px;">' + icon + '</span>'
                    + '</span>';
            }
            row.statusEl.innerHTML = html || '<span style="color:#98a2b3;font-size:11px;">等待中…</span>';
        }

        // ---- DOM row management ----
        function _ensureCoverageBatchRow(index, label, _total) {
            if (coverageBatchRows[index]) {
                var r = coverageBatchRows[index];
                if (label && r.labelEl) r.labelEl.textContent = label;
                return r;
            }

            var row = document.createElement('div');
            row.style.cssText = 'margin-bottom:10px;padding:8px 12px;background:#f9fafb;border-radius:8px;border:1px solid #eaecf0;';

            // 第一行：标签 + 阶段名 + 分段进度条 + 总完成%
            var line = document.createElement('div');
            line.style.cssText = 'display:flex;align-items:center;gap:8px;width:100%;';

            var labelEl = document.createElement('span');
            labelEl.style.cssText = 'flex:0 0 70px;font-size:12px;font-weight:600;color:#333;white-space:nowrap;';
            labelEl.textContent = label || ('Batch ' + (index + 1));
            line.appendChild(labelEl);

            var phaseEl = document.createElement('span');
            phaseEl.style.cssText = 'flex:0 0 70px;font-size:11px;color:#888;white-space:nowrap;text-align:center;';
            phaseEl.textContent = '等待中';
            line.appendChild(phaseEl);

            // 多段进度条 — 用 flex 容器
            var barWrap = document.createElement('span');
            barWrap.style.cssText = 'flex:1 1 auto;min-width:100px;height:8px;display:flex;flex-direction:row;background:#e0e0e0;border-radius:3px;overflow:hidden;';
            line.appendChild(barWrap);

            // 总百分比
            var pctEl = document.createElement('span');
            pctEl.style.cssText = 'flex:0 0 42px;font-size:11px;color:#999;text-align:right;white-space:nowrap;';
            pctEl.textContent = '';
            line.appendChild(pctEl);

            row.appendChild(line);

            // 第二行：阶段完成状态（始终可见）
            var statusEl = document.createElement('div');
            statusEl.style.cssText = 'margin-top:4px;margin-left:148px;line-height:1.6;';
            row.appendChild(statusEl);

            progressContainer.appendChild(row);

            var newRow = {
                rowEl: row,
                labelEl: labelEl,
                barContainer: barWrap,
                phaseEl: phaseEl,
                textEl: pctEl,
                statusEl: statusEl,
                phaseSegments: {},
                currentPhase: '',
                pct: 0
            };
            coverageBatchRows[index] = newRow;
            return newRow;
        }

        function _updateCoverageBatchRow(index, phase, completed, total, message) {
            var row = _ensureCoverageBatchRow(index, '', 0);

            // 首次见到此 phase → 注册 + 重建所有分段条
            if (phase && !skipPhases[phase] && !seenPhases[phase]) {
                _registerPhase(phase);
                _rebuildAllPhaseBars();
            }

            _recordPhaseProgress(row, phase, completed, total, message);

            if (phase && !skipPhases[phase] && row.phaseEl) {
                row.phaseEl.textContent = phaseLabels[phase] || phase;
            }
            if (row.textEl) {
                row.textEl.textContent = row.pct > 0 ? (row.pct + '%') : '';
            }
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
                if (success) {
                    // 标记所有阶段完成
                    for (var j = 0; j < phaseOrder.length; j++) {
                        var p = phaseOrder[j];
                        if (!phaseDone[p] && phaseMaxCompleted[p] === 0) continue;
                        phaseDone[p] = true;
                        phaseMaxCompleted[p] = phaseMaxTotal[p] || 1;
                    }
                    _rebuildAllPhaseBars();
                }
                var indices = Object.keys(coverageBatchRows);
                for (var i = 0; i < indices.length; i++) {
                    var row = coverageBatchRows[indices[i]];
                    if (!row) continue;
                    if (success) {
                        row.phaseEl.textContent = '✓';
                        row.phaseEl.style.color = '#12a150';
                        row.textEl.textContent = '100%';
                    } else {
                        row.phaseEl.textContent = '✗';
                        row.phaseEl.style.color = '#d92d20';
                    }
                    if (message && row.statusEl) {
                        row.statusEl.innerHTML = '<span style="color:' + (success ? '#12a150' : '#d92d20') + ';font-size:11px;">' + _escapeProgressHtml(message) + '</span>';
                    }
                    _renderPhaseStatus(row);
                }
            },

            syncRows: function(nextTotal) {
                var existingKeys = Object.keys(coverageBatchRows);
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
                for (var j = 0; j < nextTotal; j++) {
                    var row = _ensureCoverageBatchRow(j, '', 0);
                    // 如果已有注册的阶段，为新行构建段
                    if (phaseOrder.length) _rebuildPhaseBar(row);
                }
            },

            getRow: function(idx) { return coverageBatchRows[idx] || null; },

            getIndices: function() { return Object.keys(coverageBatchRows).map(Number); },

            getTotal: function() { return totalCoverageBatches; },

            /**
             * 注册阶段列表（后端 emit_start 告知）。
             * 如果比之前多了，重建进度条段。
             */
            registerPhases: function(phases) {
                if (!Array.isArray(phases)) return;
                var added = false;
                for (var pi = 0; pi < phases.length; pi++) {
                    var p = phases[pi];
                    if (!p || skipPhases[p] || seenPhases[p]) continue;
                    _registerPhase(p);
                    added = true;
                }
                if (added) _rebuildAllPhaseBars();
            },

            setPhaseLabels: function(labels) {
                if (!labels || typeof labels !== 'object') return;
                var keys = Object.keys(labels);
                for (var i = 0; i < keys.length; i++) {
                    phaseLabels[keys[i]] = labels[keys[i]];
                }
                var indices = Object.keys(coverageBatchRows);
                for (var j = 0; j < indices.length; j++) {
                    _renderPhaseStatus(coverageBatchRows[indices[j]]);
                }
            },

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
