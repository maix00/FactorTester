/**
 * settings_chips.js — 兼容垫片：把旧的 SettingsChips.render 委托给统一的 ChipRenderer。
 *
 * 历史上每个设置一枚 chip 的渲染走 SettingsChips；现已统一到 ChipRenderer
 * （ChipDefinition + FieldStore）。本文件保留旧签名，内部转成统一 chip 模型后调用
 * ChipRenderer，使既有调用方（IC/页面/factor_type_analysis/factor_series_viewer/
 * group_test 本地栏）无需改动即可切换到统一实现。
 *
 *   SettingsChips.render(host, { manifest, store, settingKeys, tabOf, onOpen,
 *                                shouldShow, escapeHTML, renderChipHtml });
 */
(function() {
    if (window.SettingsChips) return;

    function render(host, opts) {
        opts = opts || {};
        if (!host || !window.ChipRenderer) { if (host) host.innerHTML = ''; return function() {}; }
        var manifest = opts.manifest || {};
        // 只取 per-setting chip（不混入 chip_fields——旧 SettingsChips 只渲染设置 chip）。
        var chips = window.ChipRenderer.normalizeFromManifest(manifest, {
            settingKeys: opts.settingKeys,
            includeChipFields: false,
        });
        // 旧接口用 tabOf(key) 决定 chip 归属 tab（点击打开）。
        if (typeof opts.tabOf === 'function') {
            chips.forEach(function(chip) { chip.tab_key = opts.tabOf(chip.key); });
        }
        return window.ChipRenderer.render(host, {
            chips: chips,
            store: opts.store,
            settingDefaults: manifest.defaults || {},
            onOpen: opts.onOpen,
            shouldShow: opts.shouldShow,
            escapeHTML: opts.escapeHTML,
            renderChipHtml: opts.renderChipHtml,
        });
    }

    window.SettingsChips = { render: render };
})();
