/**
 * chip_renderer.js — 统一的 chip 渲染器（window.ChipRenderer）。
 *
 * 一套实现，覆盖所有模块的所有 chip：既能渲染后端 ChipDefinition（chip_template +
 * source_keys + value_resolvers，可派生），也能渲染"每个设置一枚"的 chip（chip_template
 * 里的 {value} 用后端注册的 displaySettingValue 渲染）。值统一来自 FieldStore，chip
 * 订阅自己的 source_keys 字段，字段变更（含 fallback 连带）自动回刷——不在各模块手写。
 *
 *   var unbind = ChipRenderer.render(host, {
 *     chips,            // 统一 chip 模型数组（见 normalizeFromManifest）
 *     store,            // FieldStore 实例（source_keys 的取值来源）
 *     resolvers,        // {resolverName: function(ctx){...}} 模块提供的取值解析器
 *     settingDefaults,  // manifest.defaults（per-setting chip 的 displaySettingValue / info_overlay / visible_when）
 *     onOpen,           // 可选 function(tabKey, key)：传入则该 chip 点击=打开/关闭设置 tab（tab/内容那条 chip 行）
 *     onAction,         // 可选 function(action, chip, ctx)：ChipDefinition 的自定义动作（如 tester-products）
 *     shouldShow,       // 可选 function(chipKey)：运行时跳过
 *     escapeHTML, renderChipHtml,
 *   });
 *
 * 统一 chip 模型：
 *   { key, chip_template, source_keys:[...], value_resolvers:{placeholder:resolverName},
 *     clickable, category, info_overlay, tab_key, action }
 * 内置解析器：'__setting_display__' → displaySettingValue(defaults[key], store.effective(key))。
 */
(function() {
    if (window.ChipRenderer) return;

    var SETTING_DISPLAY = '__setting_display__';

    function _esc(v) {
        return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    // 把 manifest（defaults + chip_fields）规整成统一 chip 模型数组。
    //  - 每个有 chip_template 的设置 → 一枚 per-setting chip；
    //  - 每个 chip_fields 条目（ChipDefinition）→ 一枚 chip。
    // settingKeys/chipKeys 可选，用于筛选与排序；不传则全取。
    function normalizeFromManifest(manifest, opts) {
        opts = opts || {};
        var defaults = (manifest && manifest.defaults) || {};
        var chipFields = (manifest && manifest.chip_fields) || [];
        var out = [];
        var wantSetting = opts.settingKeys || null;   // 数组：只取这些设置；保持其顺序
        (wantSetting || Object.keys(defaults)).forEach(function(key) {
            var def = defaults[key];
            if (!def || !def.chip_template) return;
            out.push({
                key: key,
                chip_template: def.chip_template,
                source_keys: [key],
                value_resolvers: { value: SETTING_DISPLAY },
                clickable: true,
                category: 'setting',
                info_overlay: def.info_overlay || null,
                tab_key: def.tab_key || key,
                action: null,
                _setting: true,
            });
        });
        if (opts.includeChipFields !== false) {
            chipFields.forEach(function(def) {
                out.push({
                    key: def.key,
                    chip_template: def.chip_template,
                    source_keys: (def.source_keys || []).slice(),
                    value_resolvers: def.value_resolvers || {},
                    clickable: !!def.clickable,
                    category: def.category || 'identity',
                    info_overlay: def.info_overlay || null,
                    tab_key: def.tab_key || null,
                    action: def.action || null,
                    _setting: false,
                });
            });
        }
        return out;
    }

    function render(host, opts) {
        opts = opts || {};
        if (!host) return function() {};
        var chips = opts.chips || [];
        var store = opts.store;
        var defaults = opts.settingDefaults || {};
        var resolvers = opts.resolvers || {};
        var esc = opts.escapeHTML || _esc;
        var renderChipHtml = opts.renderChipHtml || (window.DomUtils && window.DomUtils.renderChipHtml);
        var BSP = window.BackendSettingsPanel;
        var hasOnOpen = typeof opts.onOpen === 'function';

        host.innerHTML = '';
        var unsubs = [];

        function effective(key) {
            return store && typeof store.effective === 'function' ? store.effective(key) : undefined;
        }

        // 解析一个 {placeholder}
        function resolvePlaceholder(chip, name) {
            var resolverName = chip.value_resolvers && chip.value_resolvers[name];
            if (resolverName === SETTING_DISPLAY) {
                var setting = Object.assign({ key: chip.key }, defaults[chip.key] || {});
                return BSP ? BSP.displaySettingValue(setting, effective(chip.key)) : effective(chip.key);
            }
            if (resolverName && typeof resolvers[resolverName] === 'function') {
                return resolvers[resolverName]({ store: store, chip: chip, key: chip.key, placeholder: name });
            }
            // 无解析器：直接取同名字段的有效值
            var v = effective(name);
            return v == null ? '' : v;
        }

        function chipText(chip) {
            return String(chip.chip_template || '').replace(/\{([^}]+)\}/g, function(_, name) {
                return resolvePlaceholder(chip, name);
            }).replace(/\s+/g, ' ').trim();
        }

        function chipVisible(chip) {
            if (typeof opts.shouldShow === 'function' && !opts.shouldShow(chip.key)) return false;
            // per-setting chip 仍走 visible_when
            if (chip._setting && BSP && store) {
                var setting = Object.assign({ key: chip.key }, defaults[chip.key] || {});
                var values = {};
                Object.keys(defaults).forEach(function(k) { values[k] = effective(k); });
                return BSP.settingVisibleForValues(setting, values);
            }
            return true;
        }

        var overlays = window.SettingsChipOverlays;

        function effectiveForOverlay(chip) {
            // overlay 取该 chip 主字段的有效值
            return effective((chip.source_keys && chip.source_keys[0]) || chip.key);
        }

        function dispatchClick(chip) {
            if (hasOnOpen && chip.tab_key) { opts.onOpen(chip.tab_key, chip.key); return; }
            if (chip.action && typeof opts.onAction === 'function') { opts.onAction(chip.action, chip, { store: store }); return; }
            if (chip.info_overlay && overlays) overlays.open(chip.info_overlay, effectiveForOverlay(chip));
        }

        function clickable(chip) {
            if (hasOnOpen && chip.tab_key) return true;
            if (chip.action && typeof opts.onAction === 'function') return true;
            return !!(chip.info_overlay && overlays && overlays.has(chip.info_overlay));
        }

        chips.forEach(function(chip) {
            var span = document.createElement('span');
            span.className = 'gt-backend-chip unified-backend-chip'
                + (chip.category ? ' chip-cat-' + chip.category : '');
            span.setAttribute('data-chip-key', chip.key);
            var isClickable = clickable(chip);
            span.style.cursor = isClickable ? 'pointer' : 'default';

            function repaint() {
                if (!chipVisible(chip)) { span.style.display = 'none'; return; }
                span.style.display = '';
                var text = chipText(chip);
                var m = text.match(/^([^:：]{1,16})[:：]\s*(.*)$/);
                if (renderChipHtml && m && m[2]) span.innerHTML = renderChipHtml(m[1], m[2], esc);
                else span.innerHTML = '<span class="gt-backend-chip-value">' + esc(text) + '</span>';
            }
            repaint();

            if (isClickable) {
                span.addEventListener('click', function() { dispatchClick(chip); });
            }
            host.appendChild(span);

            // 订阅所有 source_keys：任一变更（含 fallback 连带）即回刷本 chip。
            if (store && typeof store.subscribe === 'function') {
                (chip.source_keys && chip.source_keys.length ? chip.source_keys : [chip.key]).forEach(function(k) {
                    unsubs.push(store.subscribe(k, repaint));
                });
            }
        });

        return function unbind() { unsubs.forEach(function(fn) { try { fn(); } catch (e) {} }); unsubs = []; };
    }

    window.ChipRenderer = { render: render, normalizeFromManifest: normalizeFromManifest, SETTING_DISPLAY: SETTING_DISPLAY };
})();
