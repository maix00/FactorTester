/**
 * core/run-group-batch.js — native backtest activity UI.
 *
 * Public API intentionally keeps the old createManager shape used by
 * run-test.js, but the UI is now one signal-progress bar plus a parallel
 * flow-process diagram. There is no N/M display.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function normalizePhaseKey(value) {
        return String(value || '').trim();
    }

    function createProductCoverageBatchManager(opts) {
        var progressContainer = opts.progressContainer;
        var phases = [];
        var phaseByKey = {};
        var currentPhase = '';
        var activityCache = {};
        var rotateTimers = {};
        var rotatePosition = {};
        var row = buildShell(progressContainer);

        function buildShell(parent) {
            var root = document.createElement('div');
            root.className = 'gt-progress-track gt-activity-progress';
            root.style.cssText = 'margin-bottom:10px;';

            var line = document.createElement('div');
            line.style.cssText = 'display:flex;align-items:center;gap:8px;width:100%;';

            var title = document.createElement('span');
            title.style.cssText = 'flex:1 1 auto;min-width:0;font-size:12px;font-weight:600;color:#334155;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
            title.textContent = '分组测试';
            line.appendChild(title);

            var toggle = document.createElement('button');
            toggle.type = 'button';
            toggle.style.cssText = 'flex:0 0 24px;width:24px;height:22px;display:flex;align-items:center;justify-content:center;padding:0;border:1px solid #d0d5dd;border-radius:4px;background:#fff;color:#475467;font-size:12px;cursor:pointer;line-height:1;';
            toggle.textContent = '▾';
            line.appendChild(toggle);
            root.appendChild(line);

            var barWrap = document.createElement('div');
            barWrap.style.cssText = 'width:100%;margin-top:6px;';
            var bar = document.createElement('div');
            bar.style.cssText = 'display:block;background:#e2e8f0;border-radius:999px;height:7px;overflow:hidden;';
            var fill = document.createElement('div');
            fill.style.cssText = 'display:block;width:0%;height:100%;background:linear-gradient(90deg,#0f766e,#14b8a6);transition:width .28s ease;border-radius:999px;';
            bar.appendChild(fill);
            barWrap.appendChild(bar);
            root.appendChild(barWrap);

            var message = document.createElement('div');
            message.style.cssText = 'margin-top:4px;font-size:11px;color:#667085;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
            message.textContent = '等待回测开始';
            root.appendChild(message);

            var diagram = document.createElement('div');
            diagram.style.cssText = 'display:none;margin-top:8px;padding:8px;background:#fff;border:1px solid #eaecf0;border-radius:6px;overflow-x:auto;';
            root.appendChild(diagram);

            toggle.addEventListener('click', function() {
                var open = diagram.style.display === 'none';
                diagram.style.display = open ? 'block' : 'none';
                toggle.textContent = open ? '▴' : '▾';
            });

            parent.appendChild(root);
            return {
                root: root,
                title: title,
                fill: fill,
                message: message,
                diagram: diagram,
                toggle: toggle
            };
        }

        function phaseLabel(key) {
            var phase = phaseByKey[key];
            return phase && phase.label ? phase.label : key;
        }

        function registerActivityManifest(manifestPhases) {
            if (!Array.isArray(manifestPhases)) return;
            for (var i = 0; i < manifestPhases.length; i++) {
                var phase = manifestPhases[i] || {};
                var key = normalizePhaseKey(phase.key || phase.phase);
                if (!key) continue;
                var normalized = {
                    key: key,
                    label: phase.label || key,
                    flows: Array.isArray(phase.flows) ? phase.flows.slice() : []
                };
                normalized.flows.sort(function(a, b) {
                    return Number(a.display_order || 0) - Number(b.display_order || 0);
                });
                if (phaseByKey[key]) {
                    phaseByKey[key].label = normalized.label || phaseByKey[key].label;
                    mergeFlows(phaseByKey[key], normalized.flows);
                } else {
                    phaseByKey[key] = normalized;
                    phases.push(normalized);
                }
            }
            renderDiagram();
        }

        function mergeFlows(phase, newFlows) {
            var seen = {};
            for (var i = 0; i < phase.flows.length; i++) {
                seen[phase.flows[i].flow_key] = true;
            }
            for (var j = 0; j < newFlows.length; j++) {
                if (!seen[newFlows[j].flow_key]) {
                    phase.flows.push(newFlows[j]);
                    seen[newFlows[j].flow_key] = true;
                }
            }
            phase.flows.sort(function(a, b) {
                return Number(a.display_order || 0) - Number(b.display_order || 0);
            });
        }

        function renderDiagram() {
            if (!row.diagram) return;
            if (!phases.length) {
                row.diagram.innerHTML = '<div style="font-size:11px;color:#98a2b3;">等待流程注册</div>';
                return;
            }
            var html = ['<div class="gt-flow-process" style="display:flex;align-items:stretch;gap:8px;min-width:max-content;">'];
            for (var i = 0; i < phases.length; i++) {
                var phase = phases[i];
                var active = phase.key === currentPhase;
                html.push(
                    '<div data-phase="' + escapeHtml(phase.key) + '" class="gt-flow-phase' + (active ? ' is-active' : '') + '"'
                    + ' style="position:relative;display:flex;flex-direction:column;gap:6px;padding:6px 8px 8px;border:1px solid ' + (active ? '#14b8a6' : '#d0d5dd') + ';border-radius:6px;background:' + (active ? '#f0fdfa' : '#f8fafc') + ';">'
                    + '<div style="text-align:center;font-size:11px;font-weight:600;color:#475467;white-space:nowrap;">(' + escapeHtml(phase.label || phase.key) + ')</div>'
                    + '<div style="display:flex;gap:6px;align-items:stretch;position:relative;">'
                );
                if (active) {
                    html.push('<div class="gt-flow-phase-sweep" style="position:absolute;inset:0;border-radius:4px;pointer-events:none;background:linear-gradient(90deg,transparent,rgba(20,184,166,.18),transparent);animation:gtFlowSweep 1.45s linear infinite;"></div>');
                }
                var flows = phase.flows || [];
                if (!flows.length) {
                    html.push('<div style="font-size:11px;color:#98a2b3;padding:12px 4px;">暂无节点</div>');
                }
                for (var j = 0; j < flows.length; j++) {
                    html.push(
                        '<div class="gt-flow-node" style="position:relative;z-index:1;display:flex;align-items:center;justify-content:center;width:24px;min-height:92px;padding:4px 2px;border:1px solid #e2e8f0;border-radius:4px;background:#fff;color:#475467;font-size:11px;line-height:1.1;writing-mode:vertical-rl;text-orientation:mixed;white-space:nowrap;">'
                        + escapeHtml(flows[j].flow_label || flows[j].flow_name || flows[j].flow_key)
                        + '</div>'
                    );
                }
                html.push('</div></div>');
            }
            html.push('</div>');
            row.diagram.innerHTML = html.join('');
            ensureSweepStyle();
        }

        function ensureSweepStyle() {
            if (document.getElementById('gt-flow-sweep-style')) return;
            var style = document.createElement('style');
            style.id = 'gt-flow-sweep-style';
            style.textContent = '@keyframes gtFlowSweep{0%{transform:translateX(-60%);opacity:.25}50%{opacity:1}100%{transform:translateX(60%);opacity:.25}}';
            document.head.appendChild(style);
        }

        function recordActivity(payload) {
            if (!payload || !payload.phase) return;
            var phase = normalizePhaseKey(payload.phase);
            if (!phase) return;
            currentPhase = phase;
            if (!phaseByKey[phase]) {
                registerActivityManifest([{ key: phase, label: payload.phase_label || phase, flows: [] }]);
            }
            if (payload.flow_key) {
                activityCache[phase] = activityCache[phase] || {};
                activityCache[phase][payload.flow_key] = {
                    timestamp: payload.timestamp || '',
                    label: payload.flow_label || payload.flow_name || payload.flow_key,
                    message: payload.message || ''
                };
                var phaseSpec = phaseByKey[phase];
                var exists = false;
                for (var i = 0; i < phaseSpec.flows.length; i++) {
                    if (phaseSpec.flows[i].flow_key === payload.flow_key) {
                        exists = true;
                        break;
                    }
                }
                if (!exists) {
                    phaseSpec.flows.push({
                        phase: phase,
                        flow_key: payload.flow_key,
                        flow_name: payload.flow_name || payload.flow_key,
                        flow_label: payload.flow_label || payload.flow_key,
                        display_order: payload.display_order || phaseSpec.flows.length + 1,
                        event_kind: payload.event_kind || ''
                    });
                    phaseSpec.flows.sort(function(a, b) {
                        return Number(a.display_order || 0) - Number(b.display_order || 0);
                    });
                }
            }
            renderDiagram();
            scheduleRotation(phase);
        }

        function scheduleRotation(phase) {
            if (rotateTimers[phase]) return;
            rotateOne(phase);
            rotateTimers[phase] = window.setInterval(function() {
                rotateOne(phase);
            }, 2000);
        }

        function rotateOne(phase) {
            if (phase !== currentPhase) return;
            var phaseSpec = phaseByKey[phase];
            if (!phaseSpec || !phaseSpec.flows || !phaseSpec.flows.length) return;
            var records = activityCache[phase] || {};
            var flows = phaseSpec.flows;
            var start = rotatePosition[phase] == null ? -1 : rotatePosition[phase];
            for (var offset = 1; offset <= flows.length; offset++) {
                var idx = (start + offset) % flows.length;
                var flow = flows[idx];
                var rec = records[flow.flow_key];
                if (!rec) continue;
                rotatePosition[phase] = idx;
                var prefix = rec.timestamp ? rec.timestamp + ' ' : '';
                var text = rec.message || (prefix + '正在' + rec.label);
                row.message.textContent = text;
                row.message.title = text;
                row.title.textContent = phaseLabel(phase);
                return;
            }
        }

        function updateSignalProgress(payload) {
            var percent = Number(payload && payload.percent);
            if (!isFinite(percent)) {
                var completed = Number(payload && payload.completed || 0);
                var total = Number(payload && payload.total || 0);
                percent = total > 0 ? completed / total * 100 : 0;
            }
            percent = Math.max(0, Math.min(100, percent));
            row.fill.style.width = percent.toFixed(2) + '%';
        }

        function markAllDone(success, message) {
            if (success) {
                row.fill.style.width = '100%';
                row.fill.style.background = 'linear-gradient(90deg,#12a150,#4caf50)';
                row.title.textContent = '分组测试完成';
                row.title.style.color = '#12a150';
            } else {
                row.fill.style.background = 'linear-gradient(90deg,#d92d20,#f97066)';
                row.title.textContent = '分组测试失败';
                row.title.style.color = '#d92d20';
            }
            if (message) {
                row.message.textContent = message;
                row.message.title = message;
            }
        }

        return {
            registerActivityManifest: registerActivityManifest,
            recordActivity: recordActivity,
            updateSignalProgress: updateSignalProgress,
            markAllDone: markAllDone,
            syncRows: function() {},
            ensureRow: function() { return row; },
            updateRow: function(_idx, phase, completed, total, message) {
                updateSignalProgress({ completed: completed, total: total });
                if (message) {
                    recordActivity({
                        phase: phase || 'event_replay',
                        flow_key: (phase || 'event_replay') + '.legacy',
                        flow_label: message,
                        message: message
                    });
                }
            },
            updateAllRows: function(phase, completed, total, message) {
                this.updateRow(0, phase, completed, total, message);
            },
            registerPhases: function(phaseKeys) {
                if (!Array.isArray(phaseKeys)) return;
                registerActivityManifest(phaseKeys.map(function(key) {
                    return { key: key, label: key, flows: [] };
                }));
            },
            setPhaseLabels: function(labels) {
                labels = labels || {};
                var keys = Object.keys(labels);
                for (var i = 0; i < keys.length; i++) {
                    if (!phaseByKey[keys[i]]) registerActivityManifest([{ key: keys[i], label: labels[keys[i]], flows: [] }]);
                    else phaseByKey[keys[i]].label = labels[keys[i]];
                }
                renderDiagram();
            },
            setSubStepLabels: function() {},
            getIndices: function() { return [0]; },
            getTotal: function() { return 1; },
            getPhaseLabels: function() {
                var labels = {};
                for (var i = 0; i < phases.length; i++) labels[phases[i].key] = phases[i].label;
                return labels;
            },
            getRow: function() { return row; }
        };
    }

    GT.groupSettings = GT.groupSettings || {};
    GT.groupSettings.runGroupBatch = {
        createManager: createProductCoverageBatchManager,
    };
})();
