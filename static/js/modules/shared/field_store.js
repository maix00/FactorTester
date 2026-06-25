/**
 * field_store.js — 响应式设置字段存储（window.FieldStore）。
 *
 * 解决"chip 更新耦合在各部件里"的问题：字段是唯一真源，chip / 依赖字段只需
 * 订阅它；字段变更时由 store 主动通知订阅者，没有部件间相互耦合。
 *
 * fallback 也是字段间关系，且由后端 manifest 声明（serialization 里的
 * shared_page_field / candidate_field / fallback），store 据此：
 *   - effective(key)：解析"自身值 → fallback 链"得到有效值；
 *   - set(key)：通知 key 的订阅者，并连带通知所有"回退到 key"的字段的订阅者。
 *
 *   var store = FieldStore.create({ defaults: manifest.defaults, values: {...} });
 *   store.subscribe('factor_candidates', function(effVal){ chip.update(effVal); });
 *   store.set('factor', f);        // 自动通知 factor 的 chip + 回退到 factor 的字段(如 factor_selections)的 chip
 *   store.effective('factor_selections');  // 空时回退到 candidate_field 的有效值
 */
(function() {
    if (window.FieldStore) return;

    function _isEmpty(v) {
        return v === undefined || v === null || v === '' || (Array.isArray(v) && v.length === 0);
    }

    function create(opts) {
        opts = opts || {};
        var defaults = opts.defaults || {};                 // {key: {value, serialization}}
        var values = Object.assign(Object.create(null), opts.values || {});
        var listeners = Object.create(null);                // key -> [fn]

        // 预计算"反向 fallback"：key -> [回退到 key 的字段...]
        var dependents = Object.create(null);
        function _fallbackTargets(key) {
            var s = (defaults[key] && defaults[key].serialization) || {};
            var out = [];
            if (s.fallback === 'candidates' && s.candidate_field) out.push(s.candidate_field);
            if (s.shared_page_field && s.shared_page_field !== key) out.push(s.shared_page_field);
            return out;
        }
        Object.keys(defaults).forEach(function(key) {
            _fallbackTargets(key).forEach(function(target) {
                (dependents[target] = dependents[target] || []).push(key);
            });
        });

        function get(key) {
            return Object.prototype.hasOwnProperty.call(values, key) ? values[key]
                : (defaults[key] ? defaults[key].value : undefined);
        }

        // 有效值：自身非空则用自身，否则沿 fallback 链解析。
        function effective(key, _seen) {
            _seen = _seen || {};
            if (_seen[key]) return get(key);  // 防环
            _seen[key] = true;
            var own = get(key);
            if (!_isEmpty(own)) return own;
            var targets = _fallbackTargets(key);
            for (var i = 0; i < targets.length; i++) {
                var v = effective(targets[i], _seen);
                if (!_isEmpty(v)) return v;
            }
            return own;
        }

        function _notify(key, _seen) {
            _seen = _seen || {};
            if (_seen[key]) return;
            _seen[key] = true;
            (listeners[key] || []).forEach(function(fn) {
                try { fn(effective(key), key); } catch (e) { console.warn('[FieldStore] 订阅回调异常 ' + key, e); }
            });
            // 连带通知"回退到 key"的字段：它们的有效值可能随 key 改变。
            (dependents[key] || []).forEach(function(dep) { _notify(dep, _seen); });
        }

        function set(key, value) {
            if (value === undefined) delete values[key];
            else values[key] = value;
            _notify(key);
            return store;
        }

        function setMany(obj) {
            Object.keys(obj || {}).forEach(function(k) {
                if (obj[k] === undefined) delete values[k]; else values[k] = obj[k];
            });
            // 全量变更后统一通知（去重）
            var seen = {};
            Object.keys(obj || {}).forEach(function(k) { _notify(k, seen); });
            return store;
        }

        function subscribe(key, fn) {
            if (typeof fn !== 'function') return function() {};
            (listeners[key] = listeners[key] || []).push(fn);
            return function unsubscribe() {
                var arr = listeners[key] || [];
                var i = arr.indexOf(fn);
                if (i >= 0) arr.splice(i, 1);
            };
        }

        var store = {
            get: get,
            effective: effective,
            set: set,
            setMany: setMany,
            subscribe: subscribe,
            values: function() { var o = {}; Object.keys(values).forEach(function(k) { o[k] = values[k]; }); return o; },
            _dependents: dependents,
        };
        return store;
    }

    window.FieldStore = { create: create };
})();
