/**
 * settings_flows.js — 中立的"列表动作(flow)分发器"公共组件（window.SettingsFlows）。
 *
 * 读后端 manifest 的 `flows`（见 SurfaceFlow 契约），按当前选中数 + 结构条件算出
 * 可用动作，渲染成动作按钮栏，点击时分发给模块注册的 handler。
 *
 * 声明（哪些动作、何时可用、什么标签）来自后端、跨客户端统一；行为（创建草稿、
 * 提交、派生/LS 逻辑）由各模块用 registerHandler 注入——和 GroupTest 的 GT.modes、
 * IC 的配置逻辑对接。
 *
 *   // 模块注入行为
 *   SettingsFlows.registerHandler('group_test', 'groups', 'create_derived', function(ctx){ ... });
 *
 *   // 列表渲染时算可用动作并渲染按钮栏
 *   SettingsFlows.renderActionBar(host, {
 *     flows: manifest.flows,           // 整份 flows
 *     surface: 'groups',               // 当前列表 surface key
 *     selectedCount: 1,
 *     predicates: { has_derived_groups: true },  // 供 flow.requires 匹配
 *     onFlow: function(flow) { ... },  // 可选；不传则走 registerHandler 注册表
 *     app: 'group_test',               // 走注册表时需要
 *     context: { ... },                // 透传给 handler
 *     escapeHTML,
 *   });
 */
(function() {
    if (window.SettingsFlows) return;

    var _handlers = {};   // "app::surface::flow" -> fn

    function _hkey(app, surface, flow) { return app + '::' + surface + '::' + flow; }

    function _escapeHTML(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function registerHandler(app, surface, flow, fn) {
        if (!app || !surface || !flow || typeof fn !== 'function') {
            console.warn('[SettingsFlows] registerHandler 参数不全', app, surface, flow);
            return;
        }
        _handlers[_hkey(app, surface, flow)] = fn;
    }

    function getHandler(app, surface, flow) {
        return _handlers[_hkey(app, surface, flow)] || null;
    }

    // flow 在当前上下文是否可用：surface 匹配 + 选中数区间 + requires 谓词
    function _isAvailable(flow, surface, selectedCount, predicates) {
        if (flow.surface !== surface) return false;
        var n = selectedCount || 0;
        if (flow.min_selected != null && n < flow.min_selected) return false;
        if (flow.max_selected != null && n > flow.max_selected) return false;
        var requires = flow.requires || {};
        for (var key in requires) {
            if (!Object.prototype.hasOwnProperty.call(requires, key)) continue;
            var want = requires[key];
            var got = predicates ? predicates[key] : undefined;
            if (got !== want) return false;
        }
        return true;
    }

    function available(flows, surface, selectedCount, predicates) {
        return (Array.isArray(flows) ? flows : [])
            .filter(function(flow) { return _isAvailable(flow, surface, selectedCount, predicates); })
            .sort(function(a, b) { return (a.order || 0) - (b.order || 0); });
    }

    var _KIND_STYLE = {
        create: 'border:1px solid #93c5fd;background:#eff6ff;color:#1d4ed8;',
        derive: 'border:1px solid #c7d2fe;background:#eef2ff;color:#4338ca;',
        compose: 'border:1px solid #c7d2fe;background:#eef2ff;color:#4338ca;',
        edit: 'border:1px solid #cbd5e1;background:#fff;color:#475569;',
        clone: 'border:1px solid #cbd5e1;background:#fff;color:#475569;',
        delete: 'border:1px solid #fca5a5;background:#fef2f2;color:#dc2626;',
    };

    function renderActionBar(host, opts) {
        opts = opts || {};
        if (!host) return;
        var esc = opts.escapeHTML || _escapeHTML;
        var flows = available(opts.flows, opts.surface, opts.selectedCount, opts.predicates);

        if (!flows.length) { host.innerHTML = ''; return; }

        var html = '<div class="settings-flow-bar" style="display:flex;flex-wrap:wrap;gap:6px;">';
        flows.forEach(function(flow) {
            var style = _KIND_STYLE[flow.kind] || _KIND_STYLE.edit;
            html += '<button type="button" class="settings-flow-btn" data-flow-key="' + esc(flow.key) + '"'
                + ' style="height:24px;padding:0 10px;border-radius:4px;font-size:12px;cursor:pointer;' + style + '">'
                + esc(flow.label) + '</button>';
        });
        html += '</div>';
        host.innerHTML = html;

        var byKey = {};
        flows.forEach(function(f) { byKey[f.key] = f; });

        host.querySelectorAll('.settings-flow-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var flow = byKey[btn.getAttribute('data-flow-key')];
                if (!flow) return;
                if (typeof opts.onFlow === 'function') { opts.onFlow(flow, opts.context); return; }
                var fn = getHandler(opts.app, opts.surface, flow.key);
                if (fn) fn(opts.context, flow);
                else console.warn('[SettingsFlows] 无 handler:', opts.app, opts.surface, flow.key);
            });
        });
    }

    window.SettingsFlows = {
        registerHandler: registerHandler,
        getHandler: getHandler,
        available: available,
        renderActionBar: renderActionBar,
    };
})();
