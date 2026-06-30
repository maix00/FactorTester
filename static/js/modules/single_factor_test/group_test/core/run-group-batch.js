/**
 * core/run-group-batch.js — native backtest activity UI.
 *
 * One progress bar, one typewriter status line, and one always-visible flow
 * line. Counts are deliberately not rendered.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    var EVENT_PHASE = 'event_replay';

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
        var activeFlowKey = '';
        var activityCache = {};
        var rotateTimer = null;
        var typeTimer = null;
        var rotatePosition = {};
        var done = false;
        var row = buildShell(progressContainer);

        ensureFlowLineStyle();

        function buildShell(parent) {
            var root = document.createElement('div');
            root.className = 'gt-progress-track gt-activity-progress';
            root.style.cssText = 'margin-bottom:10px;';

            var title = document.createElement('div');
            title.style.cssText = 'font-size:12px;font-weight:600;color:#334155;line-height:1.4;';
            title.textContent = '分组测试';
            root.appendChild(title);

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
            message.style.cssText = 'margin-top:5px;min-height:16px;font-size:11px;color:#667085;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
            message.textContent = '等待回测开始';
            root.appendChild(message);

            var diagram = document.createElement('div');
            diagram.style.cssText = 'margin-top:10px;padding:2px 0 4px;overflow-x:auto;';
            root.appendChild(diagram);

            parent.appendChild(root);
            return {
                root: root,
                title: title,
                fill: fill,
                message: message,
                diagram: diagram
            };
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
                normalized.flows.sort(sortFlows);
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

        function sortFlows(a, b) {
            return Number(a.display_order || 0) - Number(b.display_order || 0);
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
            phase.flows.sort(sortFlows);
        }

        function recordActivity(payload) {
            if (done || !payload || !payload.phase) return;
            var phase = normalizePhaseKey(payload.phase);
            if (!phase) return;
            currentPhase = phase;
            activeFlowKey = payload.flow_key || '';
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
                ensureFlowInPhase(phase, payload);
            }
            renderDiagram();
            if (phase === EVENT_PHASE) {
                ensureEventRotation();
                rotateEventFlow();
            } else {
                stopEventRotation();
                var rec = activityCache[phase] && activityCache[phase][payload.flow_key];
                setMessage(rec ? formatRecord(rec) : payload.message || '');
            }
        }

        function ensureFlowInPhase(phase, payload) {
            var phaseSpec = phaseByKey[phase];
            for (var i = 0; i < phaseSpec.flows.length; i++) {
                if (phaseSpec.flows[i].flow_key === payload.flow_key) return;
            }
            phaseSpec.flows.push({
                phase: phase,
                flow_key: payload.flow_key,
                flow_name: payload.flow_name || payload.flow_key,
                flow_label: payload.flow_label || payload.flow_key,
                display_order: payload.display_order || phaseSpec.flows.length + 1,
                event_kind: payload.event_kind || ''
            });
            phaseSpec.flows.sort(sortFlows);
        }

        function ensureEventRotation() {
            if (rotateTimer) return;
            rotateTimer = window.setInterval(rotateEventFlow, 2000);
        }

        function stopEventRotation() {
            if (!rotateTimer) return;
            window.clearInterval(rotateTimer);
            rotateTimer = null;
        }

        function rotateEventFlow() {
            if (done || currentPhase !== EVENT_PHASE) return;
            var phaseSpec = phaseByKey[EVENT_PHASE];
            if (!phaseSpec || !phaseSpec.flows || !phaseSpec.flows.length) return;
            var records = activityCache[EVENT_PHASE] || {};
            var start = rotatePosition[EVENT_PHASE] == null ? -1 : rotatePosition[EVENT_PHASE];
            for (var offset = 1; offset <= phaseSpec.flows.length; offset++) {
                var idx = (start + offset) % phaseSpec.flows.length;
                var flow = phaseSpec.flows[idx];
                var rec = records[flow.flow_key];
                if (!rec) continue;
                rotatePosition[EVENT_PHASE] = idx;
                setMessage(formatRecord(rec));
                return;
            }
        }

        function formatRecord(rec) {
            var prefix = rec.timestamp ? rec.timestamp + ' ' : '';
            return rec.message || (prefix + '正在' + rec.label);
        }

        function setMessage(text) {
            text = text || '等待回测开始';
            if (row.message.title === text && row.message.textContent === text) return;
            if (typeTimer) window.clearInterval(typeTimer);
            row.message.title = text;
            row.message.textContent = '';
            var index = 0;
            typeTimer = window.setInterval(function() {
                index += 1;
                row.message.textContent = text.slice(0, index);
                if (index >= text.length) {
                    window.clearInterval(typeTimer);
                    typeTimer = null;
                }
            }, 18);
        }

        function updateSignalProgress(payload) {
            if (done) return;
            var percent = Number(payload && payload.percent);
            if (!isFinite(percent)) {
                var completed = Number(payload && payload.completed || 0);
                var total = Number(payload && payload.total || 0);
                percent = total > 0 ? completed / total * 100 : 0;
            }
            percent = Math.max(0, Math.min(100, percent));
            row.fill.style.width = percent.toFixed(2) + '%';
        }

        function renderDiagram() {
            if (!row.diagram) return;
            if (!phases.length) {
                row.diagram.innerHTML = '<div style="font-size:11px;color:#98a2b3;">等待流程注册</div>';
                return;
            }
            var html = ['<div class="gt-flow-line-root">'];
            for (var i = 0; i < phases.length; i++) {
                var phase = phases[i];
                var active = phase.key === currentPhase;
                html.push(
                    '<div class="gt-flow-line-phase' + (active ? ' is-active' : '') + (phase.key === EVENT_PHASE ? ' is-event-phase' : '') + '" data-phase="' + escapeHtml(phase.key) + '">'
                    + '<div class="gt-flow-phase-title">' + escapeHtml(phase.label || phase.key) + '</div>'
                    + '<div class="gt-flow-line-track">'
                );
                var flows = phase.flows || [];
                for (var j = 0; j < flows.length; j++) {
                    var flow = flows[j];
                    var nodeActive = active && phase.key !== EVENT_PHASE && flow.flow_key === activeFlowKey;
                    html.push(
                        '<div class="gt-flow-line-node' + (nodeActive ? ' is-current' : '') + '">'
                        + '<span class="gt-flow-dot"></span>'
                        + '<div class="gt-flow-node-label">' + escapeHtml(flow.flow_label || flow.flow_name || flow.flow_key) + '</div>'
                        + '</div>'
                    );
                }
                if (!flows.length) {
                    html.push('<div class="gt-flow-empty">暂无节点</div>');
                }
                html.push('</div></div>');
            }
            html.push('</div>');
            row.diagram.innerHTML = html.join('');
        }

        function ensureFlowLineStyle() {
            if (document.getElementById('gt-flow-line-style')) return;
            var style = document.createElement('style');
            style.id = 'gt-flow-line-style';
            style.textContent = [
                '@keyframes gtFlowLineMove{0%{background-position:0 0}100%{background-position:28px 0}}',
                '.gt-flow-line-root{display:flex;align-items:flex-start;gap:0;min-width:max-content;padding:0 2px 2px;}',
                '.gt-flow-line-phase{position:relative;display:flex;flex-direction:column;align-items:stretch;min-width:96px;padding:0 8px;}',
                '.gt-flow-phase-title{text-align:center;font-size:11px;font-weight:600;color:#64748b;line-height:1.2;margin-bottom:6px;white-space:nowrap;}',
                '.gt-flow-line-track{position:relative;display:flex;align-items:flex-start;gap:16px;padding-top:8px;}',
                '.gt-flow-line-track:before{content:"";position:absolute;left:0;right:0;top:14px;height:2px;background:#d0d5dd;}',
                '.gt-flow-line-phase.is-active .gt-flow-phase-title{color:#0f766e;}',
                '.gt-flow-line-phase.is-event-phase.is-active .gt-flow-line-track:before{background:repeating-linear-gradient(90deg,#14b8a6 0,#14b8a6 12px,#99f6e4 12px,#99f6e4 24px);background-size:28px 2px;animation:gtFlowLineMove .75s linear infinite;}',
                '.gt-flow-line-node{position:relative;z-index:1;display:flex;flex-direction:column;align-items:center;min-width:20px;}',
                '.gt-flow-dot{width:12px;height:12px;border-radius:999px;background:#fff;border:2px solid #cbd5e1;box-sizing:border-box;}',
                '.gt-flow-line-node.is-current .gt-flow-dot{border-color:#0f766e;background:#14b8a6;box-shadow:0 0 0 4px rgba(20,184,166,.16);}',
                '.gt-flow-node-label{margin-top:5px;font-size:10px;line-height:1.08;color:#475467;writing-mode:vertical-rl;text-orientation:mixed;white-space:nowrap;}',
                '.gt-flow-line-node.is-current .gt-flow-node-label{color:#0f766e;font-weight:600;}',
                '.gt-flow-empty{font-size:11px;color:#98a2b3;padding:4px 0 0;}'
            ].join('');
            document.head.appendChild(style);
        }

        function stopTimers() {
            stopEventRotation();
            if (typeTimer) {
                window.clearInterval(typeTimer);
                typeTimer = null;
            }
        }

        function markAllDone(success, message) {
            done = true;
            stopTimers();
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
            renderDiagram();
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
                        phase: phase || EVENT_PHASE,
                        flow_key: (phase || EVENT_PHASE) + '.legacy',
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
