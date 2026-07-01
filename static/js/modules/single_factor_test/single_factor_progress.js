/**
 * single_factor_progress.js
 *
 * Shared progress semantics for single-factor test modules.
 *
 * Backends emit count-based phases/sub-steps. Frontend modules may render them
 * differently, but completion, terminal count-less messages, and sub-step
 * aggregation must stay identical across GroupTest, IC, factor evaluation, and
 * later analysis modules.
 */
(function() {
    'use strict';

    function isEmptyObject(value) {
        return !value || Object.keys(value).length === 0;
    }

    function isTerminalMessage(message) {
        var msg = String(message || '');
        return (
            msg.indexOf('完成') >= 0 ||
            msg.indexOf('就绪') >= 0 ||
            msg.indexOf('跳过') >= 0 ||
            msg.indexOf('已有缓存') >= 0
        );
    }

    function normalizeProgress(completed, total, message) {
        var c = Number(completed || 0);
        var t = Number(total || 0);
        if (t <= 0 && isTerminalMessage(message)) {
            return { completed: 1, total: 1, terminal: true };
        }
        return { completed: c, total: t, terminal: false };
    }

    function aggregateSubSteps(subSteps) {
        var aggTotal = 0;
        var aggCompleted = 0;
        var keys = Object.keys(subSteps || {});
        for (var k = 0; k < keys.length; k++) {
            var ss = subSteps[keys[k]] || {};
            var total = Number(ss.total || 0);
            aggTotal += total;
            aggCompleted += ss.done ? total : Number(ss.completed || 0);
        }
        return { completed: aggCompleted, total: aggTotal };
    }

    function completePhaseRecord(record) {
        if (!record) return;
        if (record.subSteps && !isEmptyObject(record.subSteps)) {
            var keys = Object.keys(record.subSteps);
            for (var i = 0; i < keys.length; i++) {
                var ss = record.subSteps[keys[i]];
                if (!ss) continue;
                if ((ss.total || 0) <= 0) ss.total = 1;
                if ((ss.completed || 0) < ss.total) ss.completed = ss.total;
                ss.done = true;
            }
            var agg = aggregateSubSteps(record.subSteps);
            record.completed = agg.completed;
            record.total = agg.total;
        } else {
            if ((record.total || 0) <= 0) record.total = 1;
            if ((record.completed || 0) < record.total) record.completed = record.total;
        }
        record.done = true;
    }

    function computeLinearPct(phaseOrder, hiddenPhases, phase, localCompleted, localTotal, currentPct) {
        if (!Array.isArray(phaseOrder) || !phase) return currentPct || 0;
        var visible = [];
        var hidden = hiddenPhases || {};
        for (var i = 0; i < phaseOrder.length; i++) {
            if (!hidden[phaseOrder[i]]) visible.push(phaseOrder[i]);
        }
        if (visible.indexOf(phase) < 0 && !hidden[phase]) visible.push(phase);
        if (!visible.length) return currentPct || 0;
        var phaseIdx = visible.indexOf(phase);
        if (phaseIdx < 0) return currentPct || 0;
        var frac = localTotal > 0 ? Math.max(0, Math.min(1, localCompleted / localTotal)) : 0;
        var nextPct = Math.round((phaseIdx + frac) * (100 / visible.length));
        return Math.max(currentPct || 0, nextPct);
    }

    function clampPct(value) {
        var pct = Number(value || 0);
        if (!Number.isFinite(pct)) pct = 0;
        return Math.max(0, Math.min(100, Math.floor(pct)));
    }

    function createSimpleProgressController(options) {
        var opts = options || {};
        var hideTimer = null;

        function resolve() {
            if (typeof opts.resolve === 'function') return opts.resolve() || {};
            return {
                wrapper: opts.wrapper || null,
                bar: opts.bar || null,
                text: opts.text || null,
                runBtn: opts.runBtn || null,
            };
        }

        function set(value, text) {
            var ui = resolve();
            var next = clampPct(value);
            if (ui.bar) ui.bar.style.width = next + '%';
            if (ui.text) ui.text.textContent = text || (next + '%');
            return next;
        }

        function show(text) {
            if (hideTimer) {
                clearTimeout(hideTimer);
                hideTimer = null;
            }
            var ui = resolve();
            set(0, text || '0%');
            if (ui.wrapper) ui.wrapper.style.display = opts.visibleDisplay == null ? 'flex' : opts.visibleDisplay;
            if (ui.runBtn) ui.runBtn.disabled = true;
        }

        function done(text, delayMs) {
            var ui = resolve();
            set(100, text || '完成');
            if (ui.runBtn) ui.runBtn.disabled = false;
            var delay = delayMs == null ? 500 : delayMs;
            if (delay >= 0 && ui.wrapper) {
                hideTimer = setTimeout(function() {
                    var latest = resolve();
                    if (latest.wrapper) latest.wrapper.style.display = 'none';
                    hideTimer = null;
                }, delay);
            }
        }

        function fail(text, value, delayMs) {
            var ui = resolve();
            set(value == null ? 0 : value, text || '失败');
            if (ui.runBtn) ui.runBtn.disabled = false;
            if (ui.wrapper) ui.wrapper.style.display = opts.visibleDisplay == null ? 'flex' : opts.visibleDisplay;
            var delay = delayMs == null ? 1000 : delayMs;
            if (delay >= 0 && ui.wrapper) {
                hideTimer = setTimeout(function() {
                    var latest = resolve();
                    if (latest.wrapper) latest.wrapper.style.display = 'none';
                    hideTimer = null;
                }, delay);
            }
        }

        function setCount(completed, total, suffix) {
            var norm = normalizeProgress(completed, total, suffix || '');
            var pct = norm.total > 0 ? (norm.completed / norm.total * 100) : 0;
            var label = norm.total > 0
                ? (norm.completed + '/' + norm.total + (suffix ? ' ' + suffix : ''))
                : (suffix || '--');
            set(pct, label);
        }

        return {
            done: done,
            fail: fail,
            set: set,
            setCount: setCount,
            show: show,
        };
    }

    window.SingleFactorProgress = {
        aggregateSubSteps: aggregateSubSteps,
        clampPct: clampPct,
        completePhaseRecord: completePhaseRecord,
        computeLinearPct: computeLinearPct,
        createSimpleProgressController: createSimpleProgressController,
        isEmptyObject: isEmptyObject,
        isTerminalMessage: isTerminalMessage,
        normalizeProgress: normalizeProgress,
    };
})();
