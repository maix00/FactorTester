/**
 * submission_bus.js — product-path-selection 变更通知总线
 *
 * 多个下游模块（IC、GroupTest、global_template 等）仍通过 legacy
 * submissions 事件名感知产品路径选择变更。
 *
 * 事件类型：
 *   submission:added      — 新增测试器 { submission }
 *   submission:removed    — 删除测试器 { id_time, submission }
 *   submission:renamed    — 重命名     { id_time, newName }
 *   submission:reordered  — 重新排序   { submissions }
 *   submission:pathsChanged — 路径变更  { id_time, submission }
 *   submission:synced     — 从后端同步 { submissions }
 *
 * 特殊订阅：
 *   on('*', fn)  — 监听所有事件
 *
 * 用法：
 *   window._submissionBus.on('submission:removed', function(data) { ... })
 *   window._submissionBus.emit('submission:removed', { id_time: '...' })
 */

(function() {
    'use strict';

    var _listeners = {};   // { eventName: [fn, ...] }
    var _wildcards = [];   // [fn, ...]  for '*'

    /**
     * 订阅事件
     * @param {string} event - 事件名 或 '*'
     * @param {function} fn - 回调函数
     * @returns {function} unsubscribe 函数
     */
    function on(event, fn) {
        if (typeof fn !== 'function') {
            console.warn('[submission_bus] on() requires a function, got', typeof fn);
            return function() {};
        }
        if (event === '*') {
            _wildcards.push(fn);
        } else {
            if (!_listeners[event]) _listeners[event] = [];
            _listeners[event].push(fn);
        }
        return function() { off(event, fn); };
    }

    /**
     * 取消订阅
     * @param {string} event - 事件名 或 '*'
     * @param {function} fn - 之前注册的回调函数
     */
    function off(event, fn) {
        if (event === '*') {
            _wildcards = _wildcards.filter(function(f) { return f !== fn; });
        } else {
            var arr = _listeners[event];
            if (arr) {
                _listeners[event] = arr.filter(function(f) { return f !== fn; });
            }
        }
    }

    /**
     * 发布事件
     * @param {string} event - 事件名
     * @param {object} data - 事件数据
     */
    function emit(event, data) {
        // 通知精确订阅者
        var arr = _listeners[event];
        if (arr) {
            arr.slice().forEach(function(fn) {
                try { fn(data); } catch(e) { console.error('[submission_bus] handler error for ' + event + ':', e); }
            });
        }
        // 通知通配符订阅者
        _wildcards.slice().forEach(function(fn) {
            try { fn(event, data); } catch(e) { console.error('[submission_bus] wildcard handler error for ' + event + ':', e); }
        });
    }

    /**
     * 移除所有监听器（用于测试/重置）
     */
    function reset() {
        _listeners = {};
        _wildcards = [];
    }

    // 暴露到全局
    window._submissionBus = {
        on: on,
        off: off,
        emit: emit,
        reset: reset,
        EVENTS: {
            ADDED: 'submission:added',
            REMOVED: 'submission:removed',
            RENAMED: 'submission:renamed',
            REORDERED: 'submission:reordered',
            PATHS_CHANGED: 'submission:pathsChanged',
            SYNCED: 'submission:synced',
        }
    };

    console.log('[submission_bus] initialized');
})();
