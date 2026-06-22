/** Product-path selection utility helpers shared by test modules. */
(function() {
    if (window.ProductPathSelectionUtils) return;

    function clone(value) {
        if (value == null || typeof value !== 'object') return value;
        if (Array.isArray(value)) return value.map(clone);
        var out = {};
        Object.keys(value).forEach(function(key) { out[key] = clone(value[key]); });
        return out;
    }

    function selectionId(selection) {
        return selection ? String(selection.product_path_selection_id || selection.selection_id || selection.id || '') : '';
    }

    function selectionLabel(selection) {
        return selection ? (selection.product_group || selection.label || selection.name || selectionId(selection)) : '';
    }

    function selectionProducts(selection) {
        var raw = selection && ((Array.isArray(selection.products) && selection.products.length)
            ? selection.products
            : (selection.product_groups || []));
        return (raw || []).map(function(item) {
            if (typeof item === 'string') return { name: item, desc: '' };
            return item && item.name ? { name: item.name, desc: item.desc || '' } : null;
        }).filter(Boolean);
    }

    function dedupe(selections) {
        var seen = {};
        var out = [];
        (selections || []).forEach(function(selection) {
            var id = selectionId(selection);
            if (!id || seen[id]) return;
            seen[id] = true;
            out.push(selection);
        });
        return out;
    }

    window.ProductPathSelectionUtils = {
        clone: clone,
        cloneList: function(list) { return Array.isArray(list) ? list.map(clone) : []; },
        selectionId: selectionId,
        selectionLabel: selectionLabel,
        selectionProducts: selectionProducts,
        dedupe: dedupe,
    };
})();
