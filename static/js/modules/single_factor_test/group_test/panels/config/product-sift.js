/**
 * panels/config/product-sift.js — 品种筛选面板 (CONFIG category)
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.config) { GT.panels.config = {}; }

    var CONTAINER_ID = 'config-product-sift';

    var _mounted = false;
    var _activeId = null;

    /** Get the current productMask from dirty workspace (or fallback). */
    function _dirtyProductMask() {
        var REG = window.GT_CONFIG_REGISTRY;
        return (REG && REG.getDirty('productMask')) || {};
    }

    /** Set productMask into dirty workspace. */
    function _setDirtyProductMask(mask) {
        var REG = window.GT_CONFIG_REGISTRY;
        if (REG) REG.setDirty('productMask', mask);
    }

    /** Get inheritAllProducts flag from dirty workspace. Default: true (inherit all). */
    function _inheritAllProducts() {
        var REG = window.GT_CONFIG_REGISTRY;
        var val = REG && REG.getDirty('inheritAllProducts');
        return val === undefined ? true : !!val;
    }

    /** Set inheritAllProducts flag into dirty workspace. */
    function _setInheritAllProducts(val) {
        var REG = window.GT_CONFIG_REGISTRY;
        if (REG) REG.setDirty('inheritAllProducts', !!val);
    }

    function $(id) { return document.getElementById(id); }

    function escapeHTML(str) { return GT.escapeHTML(str); }

    function _getNode() {
        var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
        var id = sel ? sel.getFirst() : null;
        if (!id) return null;
        return GT.groupSettings.groups.get(id);
    }

    /**
     * Collect available products for the current add context.
     *
     * Rule:
     *   1. draft has parentId (non-null) → walk up parentId chain to root,
     *      then get root's products (from its productList or testerId).
     *   2. draft has parentId = null → get draft's own testerId products.
     */
    function _allProducts() {
        var draft = GT.tabs && GT.tabs.getAddDraft ? GT.tabs.getAddDraft() : null;
        var parentId = (draft && draft.preselectedParentId) || null;
        var map = {};

        if (parentId) {
            // Walk parentId chain to find the root node (parentId === null)
            var root = _getRootByParentChain(parentId);
            if (root) {
                _addProductsFromNode(map, root);
            }
        } else {
            // parentId is null — use testerId from draft's own node or context
            var testerId = (draft && draft.testerId) || null;
            if (!testerId) {
                // No testerId in draft: try get it from the selected node in edit mode
                var node = _getNode();
                if (node) testerId = node.testerId;
            }
            if (testerId) {
                _addProductsFromTesterId(map, testerId);
            }
        }

        // Fallback: collect from all root nodes (parentId === null) via their testerIds
        if (Object.keys(map).length === 0) {
            var groups = GT.groupSettings.groups.getAll();
            var seenTesterIds = {};
            for (var i = 0; i < groups.length; i++) {
                var g = groups[i];
                if (g.parentId) continue;  // only root nodes
                if (g.testerId && !seenTesterIds[g.testerId]) {
                    seenTesterIds[g.testerId] = true;
                    _addProductsFromTesterId(map, g.testerId);
                }
            }
        }

        var sorted = Object.keys(map).sort();
        return sorted.map(function(n) { return { name: n, desc: map[n] || '' }; });
    }

    /** Walk parentId chain to root (node where parentId === null). Returns null if no root found. */
    function _getRootByParentChain(startId) {
        var groups = GT.groupSettings.groups;
        if (!groups) return null;
        var visited = {};
        var id = startId;
        while (id) {
            if (visited[id]) return null; // cycle
            visited[id] = true;
            var node = groups.get(id);
            if (!node) return null;
            if (!node.parentId) return node; // root
            id = node.parentId;
        }
        return null;
    }

    /** Add products from a node: first try its own products list, then testerId. */
    function _addProductsFromNode(map, node) {
        if (!node) return;
        // If node has explicit productList, use it
        if (node.products && node.products.length > 0) {
            for (var i = 0; i < node.products.length; i++) {
                var p = node.products[i];
                var name = typeof p === 'string' ? p : (p.name || '');
                var desc = typeof p === 'string' ? '' : (p.desc || '');
                if (name && !map[name]) map[name] = desc;
            }
            return;
        }
        // Otherwise resolve via testerId
        if (node.testerId) {
            _addProductsFromTesterId(map, node.testerId);
        }
    }

    function _addProductsFromTesterId(map, testerId) {
        var subs = window.submissions || [];
        for (var i = 0; i < subs.length; i++) {
            if (String(subs[i].id) === String(testerId)) {
                var prods = subs[i].products || [];
                for (var j = 0; j < prods.length; j++) {
                    var raw = typeof prods[j] === 'string' ? { name: prods[j], desc: '' } : { name: prods[j].name || '', desc: prods[j].desc || '' };
                    if (raw.name && !map[raw.name]) {
                        map[raw.name] = raw.desc;
                    }
                }
                break;
            }
        }
    }

    function _hasOverride(node) {
        return node && node.productMask && Object.keys(node.productMask).length > 0;
    }

    /**
     * Walk the parentId chain to collect effective products.
     */
    function _effectiveProducts(node) {
        if (!node) return { products: [], source: 'none' };
        if (_hasOverride(node)) {
            return { products: Object.keys(node.productMask).sort(), source: 'override' };
        }
        if (node.parentId) {
            return _effectiveProducts(GT.groupSettings.groups.get(node.parentId));
        }
        // Root node: use its own products or resolve via testerId
        if (node.products && node.products.length > 0) {
            return { products: node.products.slice(), source: 'rootProducts', name: node.name || node.id };
        }
        if (node.testerId) {
            var map = {};
            _addProductsFromTesterId(map, node.testerId);
            var prods = Object.keys(map).sort();
            return { products: prods, source: 'testerId', name: node.name || node.id };
        }
        return { products: [], source: 'none' };
    }

    function _initDirtyFromActiveNode() {
        var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
        var id = sel ? sel.getFirst() : null;
        if (!id) return;
        var node = GT.groupSettings.groups && GT.groupSettings.groups.get(id);
if (!node) return;
        var mask = node.productMask || {};
        var dirtyMask = {};
        var keys = Object.keys(mask);
        for (var i = 0; i < keys.length; i++) {
            if (mask[keys[i]]) dirtyMask[keys[i]] = true;
        }
        _setDirtyProductMask(dirtyMask);
    }

    // ---------------------------------------------------------------------------
    // Render — product multi-select (unified for all modes)
    // ---------------------------------------------------------------------------

    function _render(container) {
        var allProducts = _allProducts();

        // Determine parent info
        var draft = GT.tabs && GT.tabs.getAddDraft ? GT.tabs.getAddDraft() : null;
        var preselectedParentId = (draft && draft.preselectedParentId) || null;
        var parentLabel = '';
        var parentType = '';

        if (preselectedParentId) {
            var pNode = GT.groupSettings.groups && GT.groupSettings.groups.get(preselectedParentId);
            parentLabel = pNode ? (pNode.name || pNode.id) : preselectedParentId;
            parentType = pNode && pNode.parentId ? 'derived' : 'group';
        }

        var inheritAll = _inheritAllProducts();

        var html = '<div style="margin-bottom:16px;">';
        html += '<h3 style="margin:0 0 4px 0;font-size:15px;">品种筛选</h3>';
        if (parentType === 'derived') {
            html += '<p style="margin:0 0 8px 0;font-size:12px;color:#7c3aed;">关联上级派生组: <strong>' + escapeHTML(parentLabel) + '</strong></p>';
        } else if (parentType === 'group') {
            html += '<p style="margin:0 0 8px 0;font-size:12px;color:#0078d4;">关联父分组: <strong>' + escapeHTML(parentLabel) + '</strong></p>';
        }
        html += '</div>';

        // ── Inherit all checkbox ──
        html += '<div style="margin-bottom:12px;">';
        html += '<label id="product-sift-inherit-label" style="display:inline-flex;align-items:center;gap:6px;cursor:pointer;font-size:13px;color:#333;">';
        html += '<input type="checkbox" id="product-sift-inherit-all"' + (inheritAll ? ' checked' : '') + ' style="width:16px;height:16px;">';
        html += '<span>不筛选 · 继承上级全部品种</span>';
        html += '</label>';
        html += '</div>';

        if (allProducts.length === 0) {
            if (!inheritAll) {
                html += '<div style="padding:24px;text-align:center;color:#888;">未找到品种数据</div>';
            }
        } else if (!inheritAll) {
            // Select all / Deselect all
            html += '<div style="margin-bottom:8px;">';
            html += '<button id="derived-products-select-all" style="padding:2px 10px;font-size:12px;border:1px solid #d0d5dd;border-radius:4px;cursor:pointer;margin-right:6px;">全选</button>';
            html += '<button id="derived-products-deselect-all" style="padding:2px 10px;font-size:12px;border:1px solid #d0d5dd;border-radius:4px;cursor:pointer;">取消全选</button>';
            html += '<span style="margin-left:12px;font-size:12px;color:#666;">已选 <span id="derived-products-count">0</span> / ' + allProducts.length + ' 个品种</span>';
            html += '</div>';

            html += '<div id="product-sift-list" style="max-height:300px;overflow-y:auto;border:1px solid #e5e7eb;border-radius:6px;padding:8px;background:#fafbfc;">';
            for (var i = 0; i < allProducts.length; i++) {
                var p = allProducts[i];
                var name = p.name;
                var desc = p.desc || '';
                var checked = _dirtyProductMask()[name] ? ' checked' : '';
                var styleBg = _dirtyProductMask()[name] ? 'background:#e8f0fe;border-color:#80bdff;' : 'background:#fff;';
                html += '<label style="display:inline-flex;align-items:center;margin:3px 8px 3px 0;padding:3px 8px;border:1px solid #e5e7eb;border-radius:4px;cursor:pointer;font-size:12px;' + styleBg + '">';
                html += '<input type="checkbox" class="derived-product-cb" value="' + escapeHTML(name) + '"' + checked + ' style="margin-right:4px;">';
                html += '<span style="font-family:monospace;font-weight:600;">' + escapeHTML(name) + '</span>';
                if (desc) {
                    html += '<span style="margin-left:5px;color:#888;font-size:11px;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + escapeHTML(desc) + '">' + escapeHTML(desc) + '</span>';
                }
                html += '</label>';
            }
            html += '</div>';
        }

        container.innerHTML = html;
        _bindEvents(container, allProducts);
    }

    function _bindEvents(container, allProducts) {
        // Inherit all toggle — re-render when toggled
        var inheritCb = container.querySelector('#product-sift-inherit-all');
        if (inheritCb) {
            inheritCb.addEventListener('change', function() {
                _setInheritAllProducts(this.checked);
                _render(container);
            });
        }

        var cbs = container.querySelectorAll('.derived-product-cb');
        for (var i = 0; i < cbs.length; i++) {
            cbs[i].addEventListener('change', function() {
                var mask = _dirtyProductMask();
                mask[this.value] = this.checked;
                _setDirtyProductMask(mask);
                _updateCount(container);
                _highlightLabel(this);
            });
        }

        var selectAll = container.querySelector('#derived-products-select-all');
        if (selectAll) {
            selectAll.addEventListener('click', function() {
                var mask = {};
                for (var j = 0; j < allProducts.length; j++) {
                    mask[allProducts[j].name] = true;
                }
                _setDirtyProductMask(mask);
                _render(container);
            });
        }

        var deselectAll = container.querySelector('#derived-products-deselect-all');
        if (deselectAll) {
            deselectAll.addEventListener('click', function() {
                _setDirtyProductMask({});
                _render(container);
            });
        }
    }

    function _updateCount(container) {
        var countEl = container.querySelector('#derived-products-count');
        if (countEl) {
            var mask = _dirtyProductMask();
            countEl.textContent = Object.keys(mask).filter(function(k) { return mask[k]; }).length;
        }
    }

    function _highlightLabel(cb) {
        var label = cb.closest('label');
        if (label) {
            label.style.background = cb.checked ? '#e8f0fe' : '#fff';
            label.style.borderColor = cb.checked ? '#80bdff' : '#e5e7eb';
        }
    }

    /** Load product selection from edit selection (derived group's productMask) into dirty workspace. */
    function _loadProductMaskFromSelection() {
        var ids = GT.tabs && GT.tabs.getEditSelection ? GT.tabs.getEditSelection() : null;
        if (!ids) return;
        var selIds = Array.isArray(ids) ? ids : (ids.groupIds || Object.keys(ids).filter(function(k) { return ids[k]; }));
        if (selIds.length !== 1) return;
        var node = GT.groupSettings.groups && GT.groupSettings.groups.get(selIds[0]);
        if (!node) return;
        var mask = node.productMask || {};
        // Copy truthy entries into dirty (shallow copy; productMask keys have boolean values)
        var dirtyMask = {};
        var keys = Object.keys(mask);
        for (var i = 0; i < keys.length; i++) {
            if (mask[keys[i]]) dirtyMask[keys[i]] = true;
        }
        _setDirtyProductMask(dirtyMask);
    }

    // ---------------------------------------------------------------------------
    // Render dispatcher — single unified render (no edit/view mode split).
    // All config panels share the same edit model: read from dirty, write to dirty.
    // Commit is handled centrally by REG.commitDirty().
    // ---------------------------------------------------------------------------

    function render() {
        var container = $(CONTAINER_ID);
        if (!container) return;

        // In all modes, show the product multi-select. The data comes from dirty.
        _render(container);
    }

    // ---------------------------------------------------------------------------
    // Event handlers
    // ---------------------------------------------------------------------------

    function _onSelectionChanged() {
        if (_mounted) {
            var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
            _activeId = sel ? sel.getFirst() : null;
            // Load productMask from the new active node into dirty, then render
            _initDirtyFromActiveNode();
            render();
        }
    }
    function _onDerivedGraphChanged() { if (_mounted) render(); }

    // ---------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------

    function mount() {
        _mounted = true;
        var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
        _activeId = sel ? sel.getFirst() : null;
        // Load from edit selection (derived group's productMask) or add draft (preselected products)
        var draft = GT.tabs && GT.tabs.getAddDraft ? GT.tabs.getAddDraft() : null;
        if (draft && draft.addFlow === 'derived' && draft.preselectedProducts) {
            var mask = {};
            var preselectedProducts = draft.preselectedProducts;
            for (var i = 0; i < preselectedProducts.length; i++) {
                mask[preselectedProducts[i]] = true;
            }
            _setDirtyProductMask(mask);
        } else {
            _loadProductMaskFromSelection();
        }
        if (sel && sel.on) sel.on('selectionChanged', _onSelectionChanged);
        if (GT.events && GT.events.on) GT.events.on('derivedGraphChanged', _onDerivedGraphChanged);
        render();
    }

    function unmount() {
        _mounted = false;
        _activeId = null;
        _setDirtyProductMask({});
        var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
        if (sel && sel.off) sel.off('selectionChanged', _onSelectionChanged);
        if (GT.events && GT.events.off) GT.events.off('derivedGraphChanged', _onDerivedGraphChanged);
    }

    function refresh() { if (_mounted) render(); }

    function getSelectedProducts() {
        if (_inheritAllProducts()) return [];  // empty = inherit all
        var mask = _dirtyProductMask();
        return Object.keys(mask).filter(function(k) { return mask[k]; });
    }

    function getAllProducts() {
        return _allProducts().map(function(p) { return p.name; });
    }

    // ---------------------------------------------------------------------------
    // Export
    // ---------------------------------------------------------------------------

    GT.panels.config.productSift = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
        getSelectedProducts: getSelectedProducts,
        getAllProducts: getAllProducts,
    };

    // Register field schema (so _fillGroupFromConfig preserves this field)
    var GS = GT.groupSettings;
    if (GS && GS.registerField) {
        GS.registerField({ key: 'productMask', type: 'object', default: {} });
        GS.registerField({ key: 'inheritAllProducts', type: 'boolean', default: true });
    }

    // Register as category-3 config panel with productMask field
    if (window.GT_CONFIG_REGISTRY) {
        window.GT_CONFIG_REGISTRY.register({
            name: 'productSift',
            label: '品种筛选',
            panel: GT.panels.config.productSift,
            fields: ['productMask', 'inheritAllProducts'],
        }, 'config-product-sift');
    }

    GT.log('panels/config/productSift loaded');
})();
