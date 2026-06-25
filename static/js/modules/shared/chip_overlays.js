/**
 * chip_overlays.js — chip 信息 overlay 分发（window.SettingsChipOverlays）。
 *
 * 后端 SettingDefinition.info_overlay 声明点击 chip 打开哪个信息 overlay。这里按
 * info_overlay.type 分发到具体 overlay 组件。ChipRenderer 在 chip 无 onOpen / 无
 * action 时调用 open(info_overlay, value)。
 */
(function() {
    if (window.SettingsChipOverlays) return;

    // info_overlay.type → function(value, info)
    var handlers = {
        'factor_info': function(value) {
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
        'product_path_selection_products': function(value) {
            var GT = window.GT;
            if (!GT || !GT.overlays || !GT.overlays.productPathSelectionProducts) return;
            if (value === undefined || value === null || value === '') return;
            var ppsUtils = window.ProductPathSelectionUtils;
            var label = ppsUtils && ppsUtils.selectionDisplayLabel
                ? ppsUtils.selectionDisplayLabel(value)
                : String(value && (value.label || value.product_group || value.name) || value || '');
            var products = ppsUtils && ppsUtils.selectionProducts ? ppsUtils.selectionProducts(value) : [];
            GT.overlays.productPathSelectionProducts.open(label, products, value);
        },
    };

    function open(infoOverlay, value) {
        if (!infoOverlay) return false;
        var type = typeof infoOverlay === 'string' ? infoOverlay : infoOverlay.type;
        var fn = handlers[type];
        if (typeof fn !== 'function') return false;
        fn(value, infoOverlay);
        return true;
    }

    function has(infoOverlay) {
        if (!infoOverlay) return false;
        var type = typeof infoOverlay === 'string' ? infoOverlay : infoOverlay.type;
        return typeof handlers[type] === 'function';
    }

    window.SettingsChipOverlays = { open: open, has: has, register: function(type, fn) { handlers[type] = fn; } };
})();
