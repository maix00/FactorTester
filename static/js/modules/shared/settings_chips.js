/**
 * settings_chips.js — manifest 驱动的设置 chip 栏（window.SettingsChips）。
 *
 * chip 行为统一由后端注册派生，不在各模块手写：
 *   - 哪些 chip：manifest 里有 chip_template 的设置；
 *   - 显示什么：BackendSettingsPanel.displaySettingValue(setting, 有效值)（按 serialization.kind）；
 *   - 何时更新：每个 chip subscribe 自己的字段（FieldStore），字段变更（含 fallback 连带）自动回刷；
 *   - 可见性：BackendSettingsPanel.settingVisibleForValues（按 visible_when）。
 *
 * 点击行为：
 *   - onOpen 传入 → 调用 onOpen(tabKey, key)（chip-bar 场景：打开/关闭 tab）
 *   - onOpen 未传入 → 默认行为：按 serialization.kind 打开对应信息 overlay（chooser/结果展示等）
 *
 *   var unbind = SettingsChips.render(host, {
 *     manifest, store,                 // manifest + FieldStore 实例
 *     settingKeys: ['factor_selections','product_path_selections', ...],  // 要显示的设置（顺序）
 *     tabOf: function(key){ return tabKey; },   // chip → 所属 tab（仅 onOpen 模式需要）
 *     onOpen: function(tabKey, key){ ... },     // 可选。不传则用默认 overlay 行为
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

    // 后端注册的 info_overlay.type → 点击 handler 注册表。
    // key: SettingDefinition.info_overlay.type 的值（如 'factor_info'）
    // value: function(realValue) — realValue 是点击时从 store 读到的实时有效值
    var _overlayHandlers = {
        'factor_info': function _openFactorInfo(value) {
            if (!window.FactorInfoOverlay) return;
            if (value === undefined || value === null || value === '') return;
            var alias = value;
            if (value && typeof value === 'object' && !Array.isArray(value)) {
                alias = value.alias || value.name || '';
            }
            if (!alias) return;
            var list = window.factorList || [];
            for (var i = 0; i < list.length; i++) {
                if ((list[i].alias || list[i].name) === alias) {
                    window.FactorInfoOverlay.open(list[i]);
                    return;
                }
            }
        },
        'product_path_selection_products': function _openProductPathInfo(value) {
            if (!GT || !GT.overlays || !GT.overlays.productPathSelectionProducts) return;
            if (value === undefined || value === null || value === '') return;
            var ppsUtils = window.ProductPathSelectionUtils;
            var label = ppsUtils && ppsUtils.selectionDisplayLabel
                ? ppsUtils.selectionDisplayLabel(value)
                : String(value && (value.label || value.product_group || value.name) || value || '');
            var products = ppsUtils && ppsUtils.selectionProducts
                ? ppsUtils.selectionProducts(value)
                : [];
            GT.overlays.productPathSelectionProducts.open(label, products, value);
        },
    };

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
        // onOpen 传入 → 用传入的；未传入 → 用默认 overlay 分发
        var hasCustomOnOpen = typeof opts.onOpen === 'function';
        var onOpenFn = hasCustomOnOpen ? opts.onOpen : null;

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
            var setting = Object.assign({ key: key }, defaults[key] || {});
            var overlayName = setting.info_overlay && setting.info_overlay.type;
            var span = document.createElement('span');
            span.className = 'gt-backend-chip unified-backend-chip';
            span.setAttribute('data-settings-chip', key);
            var clickable = hasCustomOnOpen || (!!overlayName && !!_overlayHandlers[overlayName]);
            span.style.cursor = clickable ? 'pointer' : 'default';

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

            if (hasCustomOnOpen) {
                var tabKey = opts.tabOf ? opts.tabOf(key) : key;
                span.addEventListener('click', function() { onOpenFn(tabKey, key); });
            } else if (overlayName && _overlayHandlers[overlayName]) {
                var handler = _overlayHandlers[overlayName];
                span.addEventListener('click', function() {
                    var value = store ? store.effective(key) : setting.value;
                    handler(value);
                });
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
