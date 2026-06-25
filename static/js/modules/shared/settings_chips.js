/**
 * settings_chips.js — manifest 驱动的设置 chip 栏（window.SettingsChips）。
 *
 * chip 行为统一由后端注册派生，不在各模块手写：
 *   - 哪些 chip：manifest 里有 chip_template 的设置；
 *   - 显示什么：BackendSettingsPanel.displaySettingValue(setting, 有效值)（按 serialization.kind）；
 *   - 何时更新：每个 chip subscribe 自己的字段（FieldStore），字段变更（含 fallback 连带）自动回刷；
 *   - 可见性：BackendSettingsPanel.settingVisibleForValues（按 visible_when）。
 *
 *   var unbind = SettingsChips.render(host, {
 *     manifest, store,                 // manifest + FieldStore 实例
 *     settingKeys: ['factor_selections','product_path_selections', ...],  // 要显示的设置（顺序）
 *     tabOf: function(key){ return tabKey; },   // chip → 所属 tab（点击打开）
 *     onOpen: function(tabKey){ ... },          // 点击 chip 打开对应 tab
 *     escapeHTML, renderChipHtml,
 *   });
 *   // 返回 unbind()：解除所有订阅（重渲染前调用）。
 */
(function() {
    if (window.SettingsChips) return;

    function _esc(v) {
        return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function render(host, opts) {
        opts = opts || {};
        if (!host) return function() {};
        var manifest = opts.manifest || {};
        var defaults = manifest.defaults || {};
        var store = opts.store;
        var esc = opts.escapeHTML || _esc;
        var renderChipHtml = opts.renderChipHtml || (window.DomUtils && window.DomUtils.renderChipHtml);
        var BSP = window.BackendSettingsPanel;
        var keys = (opts.settingKeys || []).filter(function(k) {
            return defaults[k] && defaults[k].chip_template;
        });

        host.innerHTML = '';
        var unsubs = [];

        function chipText(key) {
            var setting = Object.assign({ key: key }, defaults[key] || {});
            var value = store ? store.effective(key) : (setting.value);
            // chip 值统一以后端注册的 displaySettingValue 为准（按 serialization.kind）。
            var shown = BSP ? BSP.displaySettingValue(setting, value) : String(value);
            return String(setting.chip_template).replace('{value}', shown);
        }

        function chipVisible(key) {
            // 模块自定义运行时跳过（如"无产品路径则不显示 product"），manifest 表达不了的。
            if (typeof opts.shouldShow === 'function' && !opts.shouldShow(key)) return false;
            if (!BSP || !store) return true;
            var setting = Object.assign({ key: key }, defaults[key] || {});
            // 用所有字段的有效值判断 visible_when
            var values = {};
            Object.keys(defaults).forEach(function(k) { values[k] = store.effective(k); });
            return BSP.settingVisibleForValues(setting, values);
        }

        keys.forEach(function(key) {
            var span = document.createElement('span');
            span.className = 'gt-backend-chip unified-backend-chip';
            span.setAttribute('data-settings-chip', key);
            span.style.cursor = opts.onOpen ? 'pointer' : 'default';

            function repaint() {
                if (!chipVisible(key)) { span.style.display = 'none'; return; }
                span.style.display = '';
                var text = chipText(key);
                // chip_template 形如 "标签: {value}" → 拆成 label/value
                var m = text.match(/^([^:：]{1,16})[:：]\s*(.*)$/);
                if (renderChipHtml && m && m[2]) span.innerHTML = renderChipHtml(m[1], m[2], esc);
                else span.innerHTML = '<span class="gt-backend-chip-value">' + esc(text) + '</span>';
            }
            repaint();
            if (opts.onOpen) {
                var tabKey = opts.tabOf ? opts.tabOf(key) : key;
                span.addEventListener('click', function() { opts.onOpen(tabKey, key); });
            }
            host.appendChild(span);

            // 订阅字段：字段（或其 fallback 源）变更时自动回刷本 chip。
            if (store && typeof store.subscribe === 'function') {
                unsubs.push(store.subscribe(key, repaint));
            }
        });

        return function unbind() { unsubs.forEach(function(fn) { try { fn(); } catch (e) {} }); unsubs = []; };
    }

    window.SettingsChips = { render: render };
})();
