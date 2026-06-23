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
        if (!selection) return '';
        return selection.product_group || selection.label || selection.name || selectionId(selection);
    }

    function selectionSourceLabel(selection) {
        if (!selection) return '';
        if (selection.product_group_template_id || selection.product_group || selection.product_group_name) return '产品组';
        if (selection.path_id) return '路径组';
        return '现场';
    }

    function selectionDisplayLabel(selection) {
        var label = selectionLabel(selection);
        var source = selectionSourceLabel(selection);
        return source ? label + ' · ' + source : label;
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

    function compactSelection(selection, serialization) {
        var id = selectionId(selection);
        if (!selection || !id) return null;
        serialization = serialization || {};
        var idKeys = serialization.id_keys || ['product_path_selection_id', 'selection_id', 'id'];
        var referenceKeys = serialization.product_group_reference_keys || ['product_group_template_id', 'path_id'];
        var sourceType = serialization.product_group_source_type || 'user_product_group_template';
        var manualPathKeys = serialization.manual_path_keys || ['paths', 'selected_paths'];
        var productGroupId = '';
        referenceKeys.forEach(function(key) {
            if (!productGroupId && selection[key]) productGroupId = String(selection[key]);
        });
        if (!productGroupId && selection.source_type === sourceType) {
            idKeys.forEach(function(key) {
                if (!productGroupId && selection[key]) productGroupId = String(selection[key]);
            });
        }
        if (productGroupId) return { product_path_selection_id: productGroupId };
        var paths = [];
        manualPathKeys.forEach(function(key) {
            if (!paths.length && Array.isArray(selection[key])) paths = selection[key];
        });
        var compact = { product_path_selection_id: id };
        if (Array.isArray(paths) && paths.length) {
            compact.paths = paths.map(function(path) { return String(path || '').trim(); }).filter(Boolean);
        }
        return compact;
    }

    function selectionIdentity(selection) {
        if (!selection) return '';
        var templateId = selection.product_group_template_id || selection.path_id || '';
        if (templateId) return 'template:' + String(templateId);
        var paths = selection.paths || selection.selected_paths || [];
        if (Array.isArray(paths) && paths.length) {
            return 'paths:' + paths.map(function(path) { return String(path || '').trim(); })
                .filter(Boolean)
                .sort()
                .join('|');
        }
        var id = selectionId(selection);
        return id ? 'id:' + id : '';
    }

    function dedupe(selections) {
        var seen = {};
        var out = [];
        (selections || []).forEach(function(selection) {
            var id = selectionIdentity(selection);
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
        selectionSourceLabel: selectionSourceLabel,
        selectionDisplayLabel: selectionDisplayLabel,
        selectionIdentity: selectionIdentity,
        selectionProducts: selectionProducts,
        compactSelection: compactSelection,
        dedupe: dedupe,
    };
})();
