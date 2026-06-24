/**
 * panel_registry.js — 页面面板统一注册表（window.Panels）。
 *
 * 解决的问题：此前各面板（设置面板的各 tab、IC/分组/相关性等测试模块）各自
 * 暴露裸全局、各自管理状态、各自决定是否进模板快照，没有统一名册。注册表把
 * 这些收敛成一个契约：
 *
 *   Panels.register({
 *     key:    '唯一标识',
 *     kind:   'setting' | 'test',         // setting=有设置字段；test=响应换因子
 *     order:  number,                      // 应用/遍历顺序，默认 100
 *     el:     '#css-selector',             // 该面板根节点（用于"存在才挂载"），可空
 *     store:  Panels.createStore(backing), // 该面板的设置存储位置，可空
 *     mount:  function (ctx) {},           // 生命周期：挂载/初始化，幂等
 *     onFactorChange: function (ctx) {},   // 换因子广播回调（test 面板用）
 *     snapshot: {                          // ★ opt-in：设了才进模板快照
 *       keys:  ['字段A', '字段B'],          // 该面板拥有的顶层快照字段（可多个）
 *       key:   '单字段名',                  // keys 的单字段简写，默认取 panel.key
 *       order: number,                     // apply 顺序，默认取 panel.order
 *       get:   function () { return { 字段A: ..., 字段B: ... }; },  // 返回按 keys 命名的对象
 *       set:   function (subset) {},        // 收到仅含本面板 keys 的子对象
 *       summarize: function (subset) {},    // 同上，返回摘要行
 *     },
 *   });
 *
 * store 是"面板设置字段的页面存储与获取"——面板自己决定 backing 在哪：
 *   - 页面级面板（因子家族测试设置）→ createStore(state.values)，共享一份
 *   - 私有状态面板 → createStore(自己的对象)
 */
(function() {
    if (window.Panels) { console.warn('[Panels] already loaded'); return; }

    var _panels = {};
    var _order = [];

    function _reorder() {
        _order = Object.keys(_panels).sort(function(a, b) {
            return _panels[a].order - _panels[b].order;
        });
    }

    function _each(fn) {
        for (var i = 0; i < _order.length; i++) {
            var p = _panels[_order[i]];
            try { fn(p); } catch (e) { console.warn('[Panels] ' + p.key + ' 回调异常', e); }
        }
    }

    function _present(p) {
        return !p.el || !!document.querySelector(p.el);
    }

    /**
     * 受控存储：面板设置字段的页面存储与获取入口。
     * backing 缺省时新建一个；传入既有对象（如 state.values）则原地包装。
     */
    function createStore(backing) {
        backing = backing || Object.create(null);
        var subs = [];
        var store = {
            get: function(field) {
                return field == null ? backing : backing[field];
            },
            has: function(field) {
                return Object.prototype.hasOwnProperty.call(backing, field);
            },
            set: function(field, value) {
                if (value === undefined) delete backing[field];
                else backing[field] = value;
                for (var i = 0; i < subs.length; i++) {
                    try { subs[i](field, value); } catch (e) { console.warn('[Panels.store] 订阅异常', e); }
                }
                return store;
            },
            getAll: function() {
                var out = {};
                Object.keys(backing).forEach(function(k) { out[k] = backing[k]; });
                return out;
            },
            setAll: function(obj) {
                Object.keys(obj || {}).forEach(function(k) { store.set(k, obj[k]); });
                return store;
            },
            subscribe: function(fn) {
                if (typeof fn === 'function') subs.push(fn);
                return store;
            },
            _backing: backing,
        };
        return store;
    }

    function register(spec) {
        if (!spec || !spec.key) { console.warn('[Panels] 无效注册', spec); return null; }
        if (_panels[spec.key]) console.warn('[Panels] 覆盖已注册面板: ' + spec.key);

        var snapshot = null;
        if (spec.snapshot) {
            var s = spec.snapshot === true ? {} : spec.snapshot;
            // keys: 该面板拥有的顶层快照字段名数组。get() 返回 { key: value, ... }，
            // 这些键被铺平到顶层快照；set(obj)/summarize(obj) 收到仅含这些键的子对象。
            // 兼容旧写法 key:'x' → keys:['x']。
            var keys = Array.isArray(s.keys) && s.keys.length ? s.keys.slice() : [s.key || spec.key];
            // 无显式 get/set 时回退到 store：把整份 store 作为单键值。
            var storeKey = keys[0];
            var getFn = s.get;
            var setFn = s.set;
            if (!getFn && spec.store) {
                getFn = function() { var o = {}; o[storeKey] = spec.store.getAll(); return o; };
            }
            if (!setFn && spec.store) {
                setFn = function(obj) { spec.store.setAll((obj && obj[storeKey]) || {}); };
            }
            snapshot = {
                keys: keys,
                order: typeof s.order === 'number' ? s.order : (typeof spec.order === 'number' ? spec.order : 100),
                get: getFn || null,
                set: setFn || null,
                summarize: typeof s.summarize === 'function' ? s.summarize : null,
            };
        }

        var entry = {
            key: spec.key,
            kind: spec.kind || 'setting',
            order: typeof spec.order === 'number' ? spec.order : 100,
            label: spec.label || spec.key,
            icon: spec.icon || '',
            el: spec.el || null,
            store: spec.store || null,
            mount: typeof spec.mount === 'function' ? spec.mount : null,
            onFactorChange: typeof spec.onFactorChange === 'function' ? spec.onFactorChange : null,
            snapshot: snapshot,
        };
        _panels[spec.key] = entry;
        _reorder();
        return entry;
    }

    function get(key) { return _panels[key] || null; }
    function store(key) { return _panels[key] ? _panels[key].store : null; }
    function list(kind) {
        return _order.map(function(k) { return _panels[k]; })
            .filter(function(p) { return !kind || p.kind === kind; });
    }

    // ── 生命周期 ──────────────────────────────────────────────────────────
    function mountAll(ctx) {
        _each(function(p) { if (p.mount && _present(p)) p.mount(ctx || {}); });
    }
    function notifyFactorChange(ctx) {
        _each(function(p) { if (p.onFactorChange && _present(p)) p.onFactorChange(ctx || {}); });
    }

    // 从快照中取出某面板拥有的键子集；未命中任何键返回 null
    function _subsetForPanel(snap, p) {
        var subset = null;
        p.snapshot.keys.forEach(function(key) {
            if (Object.prototype.hasOwnProperty.call(snap, key)) {
                if (!subset) subset = {};
                subset[key] = snap[key];
            }
        });
        return subset;
    }

    // ── 快照（仅 opt-in 的面板参与） ──────────────────────────────────────
    function snapshot() {
        var out = {};
        _each(function(p) {
            if (!p.snapshot || typeof p.snapshot.get !== 'function') return;
            var data = p.snapshot.get();
            if (data === undefined || data === null) return;
            // get() 返回 { key: value, ... }，铺平到顶层
            p.snapshot.keys.forEach(function(key) {
                if (Object.prototype.hasOwnProperty.call(data, key) && data[key] !== undefined && data[key] !== null) {
                    out[key] = data[key];
                }
            });
        });
        return out;
    }
    async function applySnapshot(snap) {
        snap = snap || {};
        // 按 snapshot.order 升序 apply，逐个等待（set 可能是 async）
        var entries = list().filter(function(p) {
            return p.snapshot && typeof p.snapshot.set === 'function' && _subsetForPanel(snap, p);
        }).sort(function(a, b) { return a.snapshot.order - b.snapshot.order; });
        for (var i = 0; i < entries.length; i++) {
            var p = entries[i];
            try { await p.snapshot.set(_subsetForPanel(snap, p)); }
            catch (e) { console.warn('[Panels] apply 失败: ' + p.key, e); }
        }
    }

    /** 汇总各面板 snapshot.summarize() → [{key, label, icon, value}]，仅含 opt-in 的面板 */
    function summarize(snap) {
        snap = snap || {};
        var sections = [];
        _each(function(p) {
            if (!p.snapshot || typeof p.snapshot.summarize !== 'function') return;
            var subset = _subsetForPanel(snap, p);
            if (!subset) return;
            try {
                var value = p.snapshot.summarize(subset);
                if (value === undefined || value === null) return;
                if (Array.isArray(value) && value.length === 0) return;
                sections.push({ key: p.key, label: p.label, icon: p.icon, value: value });
            } catch (e) { console.warn('[Panels] summarize 失败: ' + p.key, e); }
        });
        return sections;
    }

    window.Panels = {
        createStore: createStore,
        register: register,
        get: get,
        store: store,
        list: list,
        mountAll: mountAll,
        notifyFactorChange: notifyFactorChange,
        snapshot: snapshot,
        applySnapshot: applySnapshot,
        summarize: summarize,
        _panels: _panels,
    };
})();
