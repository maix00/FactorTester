/**
 * chip_renderer.js — 唯一的前端 chip 实体（window.ChipRenderer）。
 *
 * 一套实现覆盖所有模块的所有 chip：既渲染后端 ChipDefinition（chip_template +
 * source_keys + value_resolvers，可派生），也渲染"每个设置一枚"的 chip（chip_template
 * 里的 {value} 用后端注册的 displaySettingValue 渲染）。值统一来自 FieldStore，chip
 * 订阅自己的 source_keys 字段，字段变更（含 fallback 连带）自动回刷。点击信息 overlay
 * 的分发也内置于此（registerOverlay）。
 *
 * 两种调用形式（二选一）：
 *   ① 低层：传 chips（统一 chip 模型数组）。
 *   ② 便捷：传 manifest + settingKeys[/chipFieldKeys] + tabOf，内部 normalize。
 *
 *   var unbind = ChipRenderer.render(host, {
 *     // ① chips: [...]            或  ② manifest, settingKeys, chipFieldKeys, includeChipFields, tabOf
 *     store,                        // FieldStore（source_keys 取值来源）
 *     resolvers,                    // {resolverName: function(ctx){...}} 模块提供的解析器
 *     settingDefaults,             // 省略时用 manifest.defaults
 *     onOpen,                       // function(tabKey, key)：传入则点击=打开/关闭设置 tab
 *     onAction,                     // function(action, chip, ctx)：ChipDefinition 自定义动作
 *     shouldShow, escapeHTML, renderChipHtml,
 *   });
 *
 * 统一 chip 模型：
 *   { key, chip_template, source_keys:[...], value_resolvers:{placeholder:resolverName},
 *     clickable, category, info_overlay, tab_key, action }
 * 内置解析器 '__setting_display__' → displaySettingValue(defaults[key], store.effective(key))。
 */
(function() {
    if (window.ChipRenderer) return;

    var SETTING_DISPLAY = '__setting_display__';

    function _esc(v) {
        return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    // ── 信息 overlay 分发（内置；后端 info_overlay.type → overlay 组件）──────────────
    var overlayHandlers = {
        'factor_info': function(value) {
            if (!window.FactorInfoOverlay) return;
            if (value === undefined || value === null || value === '') return;
            var alias = (value && typeof value === 'object' && !Array.isArray(value))
                ? (value.alias || value.name || '') : value;
            if (!alias) return;
            var list = window.factorList || [];
            for (var i = 0; i < list.length; i++) {
                if ((list[i].alias || list[i].name) === alias) { window.FactorInfoOverlay.open(list[i]); return; }
            }
        },
        'product_path_selection_products': function(value) {
            var GT = window.GT;
            if (!GT || !GT.overlays || !GT.overlays.productPathSelectionProducts) return;
            if (value === undefined || value === null || value === '') return;
            var u = window.ProductPathSelectionUtils;
            var label = u && u.selectionDisplayLabel ? u.selectionDisplayLabel(value)
                : String(value && (value.label || value.product_group || value.name) || value || '');
            var products = u && u.selectionProducts ? u.selectionProducts(value) : [];
            GT.overlays.productPathSelectionProducts.open(label, products, value);
        },
        'custom_product_fields': function(value, info, chip) {
            var rows = Array.isArray(value) ? value : [];
            var fields = chip && chip.setting && chip.setting.serialization && chip.setting.serialization.fields || [];
            var labelsByField = {};
            fields.forEach(function(field) {
                labelsByField[String(field.value)] = String(field.label || field.value || '');
            });
            var overlay = document.getElementById('custom-product-fields-overlay');
            if (!overlay) {
                overlay = document.createElement('div');
                overlay.id = 'custom-product-fields-overlay';
                overlay.style.cssText = 'display:none;position:fixed;inset:0;z-index:10000;background:rgba(15,23,42,.35);align-items:center;justify-content:center;padding:24px;';
                overlay.innerHTML = '<div style="width:min(900px,96vw);max-height:86vh;background:#fff;border-radius:8px;box-shadow:0 18px 48px rgba(15,23,42,.25);display:flex;flex-direction:column;overflow:hidden;">'
                    + '<div style="display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid #e5e7eb;"><strong>自定义字段</strong><button type="button" data-close style="border:0;background:#f1f5f9;border-radius:4px;padding:4px 8px;cursor:pointer;">关闭</button></div>'
                    + '<div data-body style="padding:14px 18px;overflow:auto;"></div></div>';
                overlay.addEventListener('click', function(e) {
                    if (e.target === overlay || e.target.getAttribute('data-close') != null) overlay.style.display = 'none';
                });
                document.body.appendChild(overlay);
            }
            var body = overlay.querySelector('[data-body]');
            if (!rows.length) {
                body.innerHTML = '<div style="color:#64748b;font-size:13px;">暂无自定义字段。</div>';
            } else {
                body.innerHTML = '<table style="width:100%;border-collapse:collapse;font-size:13px;">'
                    + '<thead><tr><th style="text-align:left;border-bottom:1px solid #e5e7eb;padding:6px;">产品/合约</th><th style="text-align:left;border-bottom:1px solid #e5e7eb;padding:6px;">字段</th><th style="text-align:left;border-bottom:1px solid #e5e7eb;padding:6px;">值</th><th style="text-align:left;border-bottom:1px solid #e5e7eb;padding:6px;">开始</th><th style="text-align:left;border-bottom:1px solid #e5e7eb;padding:6px;">结束</th></tr></thead>'
                    + '<tbody>' + rows.map(function(row) {
                        return '<tr><td style="border-bottom:1px solid #f1f5f9;padding:6px;">' + _esc(row.product || '') + '</td>'
                            + '<td style="border-bottom:1px solid #f1f5f9;padding:6px;">' + _esc(labelsByField[String(row.field)] || row.field || '') + '</td>'
                            + '<td style="border-bottom:1px solid #f1f5f9;padding:6px;">' + _esc(row.value == null ? '' : row.value) + '</td>'
                            + '<td style="border-bottom:1px solid #f1f5f9;padding:6px;">' + _esc(row.start || '') + '</td>'
                            + '<td style="border-bottom:1px solid #f1f5f9;padding:6px;">' + _esc(row.end || '') + '</td></tr>';
                    }).join('') + '</tbody></table>';
            }
            overlay.style.display = 'flex';
        },
    };
    // ctx: { valueOf(name), resolve(resolverName, name), renderChipHtml, escapeHTML }
    function chipHtml(chip, ctx) {
        var esc = ctx.escapeHTML || _esc;
        var text = String(chip.chip_template || '').replace(/\{([^}]+)\}/g, function(_, name) {
            var rn = chip.value_resolvers && chip.value_resolvers[name];
            var v = rn ? ctx.resolve(rn, name) : (ctx.valueOf ? ctx.valueOf(name) : '');
            return v == null ? '' : String(v);
        }).replace(/\s+/g, ' ').trim();
        var m = text.match(/^([^:：]{1,16})[:：]\s*(.*)$/);
        if (ctx.renderChipHtml && m && m[2]) return ctx.renderChipHtml(m[1], m[2], esc);
        return '<span class="gt-backend-chip-value">' + esc(text) + '</span>';
    }

    function overlayType(info) { return typeof info === 'string' ? info : (info && info.type); }
    function overlayHas(info) { return typeof overlayHandlers[overlayType(info)] === 'function'; }
    function overlayOpen(info, value, chip) {
        var fn = overlayHandlers[overlayType(info)];
        if (typeof fn === 'function') { fn(value, info, chip); return true; }
        return false;
    }

    // ── 把 manifest（defaults + chip_fields）规整成统一 chip 模型数组 ────────────────
    function normalizeFromManifest(manifest, opts) {
        opts = opts || {};
        var defaults = (manifest && manifest.defaults) || {};
        var chipFields = (manifest && manifest.chip_fields) || [];
        var out = [];
        (opts.settingKeys || Object.keys(defaults)).forEach(function(key) {
            var def = defaults[key];
            if (!def || !def.chip_template) return;
            out.push({
                key: key, chip_template: def.chip_template, source_keys: [key],
                value_resolvers: { value: SETTING_DISPLAY }, clickable: true, category: 'setting',
                info_overlay: def.info_overlay || null, tab_key: def.tab_key || key, action: null, _setting: true,
                setting: Object.assign({ key: key }, def),
            });
        });
        if (opts.includeChipFields) {
            chipFields.forEach(function(def) {
                if (opts.chipFieldKeys && opts.chipFieldKeys.indexOf(def.key) < 0) return;
                out.push({
                    key: def.key, chip_template: def.chip_template, source_keys: (def.source_keys || []).slice(),
                    value_resolvers: def.value_resolvers || {}, clickable: !!def.clickable,
                    category: def.category || 'identity', info_overlay: def.info_overlay || null,
                    tab_key: def.tab_key || null, action: def.action || null, _setting: false,
                    setting: def,
                });
            });
        }
        return out;
    }

    function render(host, opts) {
        opts = opts || {};
        if (!host) return function() {};
        var manifest = opts.manifest || {};
        var defaults = opts.settingDefaults || manifest.defaults || {};
        var store = opts.store;
        var resolvers = opts.resolvers || {};
        var esc = opts.escapeHTML || _esc;
        var renderChipHtml = opts.renderChipHtml || (window.DomUtils && window.DomUtils.renderChipHtml);
        var BSP = window.BackendSettingsPanel;
        var hasOnOpen = typeof opts.onOpen === 'function';

        // 便捷形式：未直接传 chips 则由 manifest 规整。
        var chips = opts.chips;
        if (!chips && opts.manifest) {
            chips = normalizeFromManifest(manifest, {
                settingKeys: opts.settingKeys,
                chipFieldKeys: opts.chipFieldKeys,
                includeChipFields: !!opts.includeChipFields,
            });
            if (typeof opts.tabOf === 'function') {
                chips.forEach(function(c) { if (c._setting) c.tab_key = opts.tabOf(c.key); });
            }
        }
        chips = chips || [];

        host.innerHTML = '';
        var unsubs = [];

        function effective(key) {
            return store && typeof store.effective === 'function' ? store.effective(key) : undefined;
        }

        function valuesForConditions() {
            var values = {};
            Object.keys(defaults).forEach(function(k) { values[k] = effective(k); });
            return values;
        }

        function settingValue(chip) {
            var setting = Object.assign({ key: chip.key }, defaults[chip.key] || {});
            var values = valuesForConditions();
            if (BSP && !BSP.settingEditableForValues(setting, values)) {
                return BSP.defaultValueForValues(setting, values);
            }
            return effective(setting.serialization && setting.serialization.storage_key || chip.key);
        }

        function conditionKeysForSetting(key) {
            var setting = defaults[key] || {};
            var out = [];
            function addFrom(obj) {
                Object.keys(obj || {}).forEach(function(dep) {
                    if (out.indexOf(dep) < 0) out.push(dep);
                });
            }
            addFrom(setting.visible_when);
            addFrom(setting.editable_when);
            addFrom(setting.default_when);
            return out;
        }

        function subscribeKeysForChip(chip) {
            var keys = (chip.source_keys && chip.source_keys.length ? chip.source_keys : [chip.key]).slice();
            if (chip._setting) {
                var storageKey = defaults[chip.key] && defaults[chip.key].serialization && defaults[chip.key].serialization.storage_key;
                if (storageKey && keys.indexOf(storageKey) < 0) keys.push(storageKey);
                conditionKeysForSetting(chip.key).forEach(function(key) {
                    if (keys.indexOf(key) < 0) keys.push(key);
                });
            }
            return keys;
        }

        // store 取值 + 内置 __setting_display__ + 模块 resolvers，组成 chipHtml 的 ctx。
        function chipCtx(chip) {
            return {
                valueOf: function(name) { return effective(name); },
                resolve: function(resolverName, name) {
                    if (resolverName === SETTING_DISPLAY) {
                        var setting = Object.assign({ key: chip.key }, defaults[chip.key] || {});
                        var value = settingValue(chip);
                        return BSP ? BSP.displaySettingValue(setting, value) : value;
                    }
                    if (typeof resolvers[resolverName] === 'function') {
                        return resolvers[resolverName]({ store: store, chip: chip, key: chip.key, placeholder: name });
                    }
                    return effective(name);
                },
                renderChipHtml: renderChipHtml,
                escapeHTML: esc,
            };
        }

        function chipVisible(chip) {
            if (typeof opts.shouldShow === 'function' && !opts.shouldShow(chip.key)) return false;
            if (chip._setting && BSP && store) {
                var setting = Object.assign({ key: chip.key }, defaults[chip.key] || {});
                return BSP.settingVisibleForValues(setting, valuesForConditions());
            }
            return true;
        }

        function effectiveForOverlay(chip) {
            if (chip._setting) return settingValue(chip);
            return effective((chip.source_keys && chip.source_keys[0]) || chip.key);
        }
        function dispatchClick(chip) {
            if (hasOnOpen && chip.tab_key) { opts.onOpen(chip.tab_key, chip.key); return; }
            if (chip.action && typeof opts.onAction === 'function') { opts.onAction(chip.action, chip, { store: store }); return; }
            if (chip.info_overlay) overlayOpen(chip.info_overlay, effectiveForOverlay(chip), chip);
        }
        function clickable(chip) {
            if (hasOnOpen && chip.tab_key) return true;
            if (chip.action && typeof opts.onAction === 'function') return true;
            return !!(chip.info_overlay && overlayHas(chip.info_overlay));
        }

        chips.forEach(function(chip) {
            var span = document.createElement('span');
            span.className = 'gt-backend-chip unified-backend-chip' + (chip.category ? ' chip-cat-' + chip.category : '');
            span.setAttribute('data-chip-key', chip.key);
            var isClickable = clickable(chip);
            span.style.cursor = isClickable ? 'pointer' : 'default';

            function repaint() {
                if (!chipVisible(chip)) { span.style.display = 'none'; return; }
                span.style.display = '';
                span.innerHTML = chipHtml(chip, chipCtx(chip));
            }
            repaint();
            if (isClickable) span.addEventListener('click', function() { dispatchClick(chip); });
            host.appendChild(span);

            if (store && typeof store.subscribe === 'function') {
                subscribeKeysForChip(chip).forEach(function(k) {
                    unsubs.push(store.subscribe(k, repaint));
                });
            }
        });

        return function unbind() { unsubs.forEach(function(fn) { try { fn(); } catch (e) {} }); unsubs = []; };
    }

    window.ChipRenderer = {
        render: render,
        chipHtml: chipHtml,                 // 单枚 chip 模板→HTML 字符串（list 等字符串场景复用）
        normalizeFromManifest: normalizeFromManifest,
        registerOverlay: function(type, fn) { overlayHandlers[type] = fn; },
        SETTING_DISPLAY: SETTING_DISPLAY,
    };
})();
