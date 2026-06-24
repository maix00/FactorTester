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

    window.SingleFactorProgress = {
        aggregateSubSteps: aggregateSubSteps,
        completePhaseRecord: completePhaseRecord,
        computeLinearPct: computeLinearPct,
        isEmptyObject: isEmptyObject,
        isTerminalMessage: isTerminalMessage,
        normalizeProgress: normalizeProgress,
    };
})();
