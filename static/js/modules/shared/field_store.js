/**
 * field_store.js — 响应式设置字段存储（window.FieldStore）。
 *
 * 字段是唯一真源，chip / 依赖字段只需订阅它；字段变更时由 store 主动通知订阅者。
 *
 * fallback 由后端 manifest 声明（serialization），store 统一据此解析，分三种：
 *   1. 本 store 内候选回退：fallback="candidates" + candidate_field
 *      （如 factor_selections → factor_candidates）。
 *   2. 跨 store 回退到页面 store 的同义字段：shared_page_field + opts.parent
 *      （如 测试模块 factor_candidates → 页面 factor_candidates）。
 *   3. 因子库/数据源回退（load_*_when_page_empty）：异步，由页面在 store 之外把库数据
 *      灌入页面字段（页面字段空时），再经 2 向下回退——不在同步的 effective() 里做。
 *
 * 跨 store 广播：父（页面）store 的字段变更，会通知本 store 中回退到它的字段的订阅者。
 *
 *   var page = FieldStore.create({ defaults, values });
 *   var ic   = FieldStore.create({ defaults, values, parent: page });
 *   ic.effective('factor_candidates');   // 本空 → 回退到 page 的 factor_candidates
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
        var parent = opts.parent || null;                   // 父（页面）store：跨 store 回退/广播
        var listeners = Object.create(null);                // key -> [fn]
        var parentUnsubs = [];

        function serial(key) { return (defaults[key] && defaults[key].serialization) || {}; }

        // 本 store 内候选回退目标（candidate_field）。shared_page_field 是跨 store 的，单独处理。
        function _inStoreTargets(key) {
            var s = serial(key);
            return (s.fallback === 'candidates' && s.candidate_field) ? [s.candidate_field] : [];
        }

        // 反向依赖：本 store 内 key 变 → 通知回退到 key 的字段。
        var dependents = Object.create(null);
        Object.keys(defaults).forEach(function(key) {
            _inStoreTargets(key).forEach(function(target) {
                (dependents[target] = dependents[target] || []).push(key);
            });
        });

        function get(key) {
            return Object.prototype.hasOwnProperty.call(values, key) ? values[key]
                : (defaults[key] ? defaults[key].value : undefined);
        }

        // 有效值：自身非空则用自身，否则沿 fallback 链解析（本 store 候选 → 父 store 同义字段）。
        function effective(key, _seen) {
            _seen = _seen || {};
            if (_seen[key]) return get(key);  // 防环
            _seen[key] = true;
            var own = get(key);
            if (!_isEmpty(own)) return own;
            var s = serial(key);
            if (s.fallback === 'candidates' && s.candidate_field) {
                var cv = effective(s.candidate_field, _seen);
                if (!_isEmpty(cv)) return cv;
            }
            if (s.shared_page_field && parent && typeof parent.effective === 'function') {
                var pv = parent.effective(s.shared_page_field);
                if (!_isEmpty(pv)) return pv;
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

        // 跨 store 广播：父（页面）store 的 shared_page_field 变更 → 通知本 store 中回退到它的字段。
        _wireParentBroadcast();

        function destroy() {
            parentUnsubs.forEach(function(fn) { try { fn(); } catch (e) {} });
            parentUnsubs = [];
        }

        // 延迟绑定父 store：用于确保 create 后 parent 才就绪的场景（如页面 store 在子模块之后初始化）。
        function setParent(p) {
            if (!p || parent === p) return;
            parent = p;
            _wireParentBroadcast();
        }

        function _wireParentBroadcast() {
            if (!parent || typeof parent.subscribe !== 'function') return;
            var pageFieldDeps = Object.create(null);
            Object.keys(defaults).forEach(function(key) {
                var pf = serial(key).shared_page_field;
                if (pf) (pageFieldDeps[pf] = pageFieldDeps[pf] || []).push(key);
            });
            Object.keys(pageFieldDeps).forEach(function(pf) {
                parentUnsubs.push(parent.subscribe(pf, function() {
                    var seen = {};
                    pageFieldDeps[pf].forEach(function(key) { _notify(key, seen); });
                }));
            });
        }

        var store = {
            get: get,
            effective: effective,
            set: set,
            setMany: setMany,
            subscribe: subscribe,
            destroy: destroy,
            setParent: setParent,
            values: function() { var o = {}; Object.keys(values).forEach(function(k) { o[k] = values[k]; }); return o; },
            _dependents: dependents,
        };
        return store;
    }

    window.FieldStore = { create: create };
})();
