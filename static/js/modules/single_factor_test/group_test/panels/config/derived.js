/**
 * panels/config/derived.js — 品种筛选面板 (CONFIG category)
 *
 * Dual-mode panel for editing a derived group's product mask:
 *   Edit mode: product multi-select with inherited/overridden state
 *   View mode (active node): read-only display of inherited or overridden product mask
 *
 * Contract:
 *   GT.panels.list.selection.getFirst() → id|null
 *   GT.panels.list.selection.on('selectionChanged', cb)
 *   GT.state.on('derivedGraphChanged', cb)
 *   GT.groupSettings.groups.get(id) → node|null
 *   GT.groupSettings.groups.getAll() → base groups (for product sourcing)
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.config) { GT.panels.config = {}; }

    var CONTAINER_ID = 'config-derived';

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

    function $(id) { return document.getElementById(id); }

    function escapeHTML(str) { return GT.escapeHTML(str); }

    function _getNode() {
        var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
        var id = sel ? sel.getFirst() : null;
        if (!id) return null;
        return GT.groupSettings.groups.get(id);
    }

    /**
     * Collect all available products from base groups.
     * Resolves products via window.submissions using testerId.
     * Returns [{name, desc}] objects.
     */
    function _allProducts() {
        var map = {}; // keyed by name for dedup
        var baseGroups = GT.groupSettings.groups.getAll();
        var seenTesterIds = {};

        // Try the active derived node first — use its effective products
        var draft = GT.ui && GT.ui.getAddDraft ? GT.ui.getAddDraft() : null;
        var preselectedParentDerivedId = (draft && draft.preselectedParentDerivedId) || null;
        if (preselectedParentDerivedId) {
            var pNode = GT.groupSettings.groups && GT.groupSettings.groups.get(preselectedParentDerivedId);
            if (pNode) {
                var effProds = _effectiveProducts(pNode);
                for (var ep = 0; ep < effProds.products.length; ep++) {
                    var epn = effProds.products[ep];
                    if (typeof epn === 'string') {
                        map[epn] = '';
                    } else if (epn && epn.name) {
                        map[epn.name] = epn.desc || '';
                    }
                }
                if (pNode.baseGroupId && pNode.baseGroupId !== '__batch__') {
                    var bg = GT.groupSettings.groups && GT.groupSettings.groups.get(pNode.baseGroupId);
                    if (bg && bg.testerId) {
                        _addProductsFromTesterId(map, bg.testerId);
                    }
                }
                var names = Object.keys(map).sort();
                return names.map(function(n) { return { name: n, desc: map[n] || '' }; });
            }
        }

        // Fallback: collect from all base groups
        for (var i = 0; i < baseGroups.length; i++) {
            var tid = baseGroups[i].testerId;
            if (tid && !seenTesterIds[tid]) {
                seenTesterIds[tid] = true;
                _addProductsFromTesterId(map, tid);
            }
        }
        var baseId = (draft && draft.preselectedBaseGroupId) || null;
        if (baseId) {
            var bg2 = GT.groupSettings.groups.get(baseId);
            if (bg2 && bg2.testerId && !seenTesterIds[bg2.testerId]) {
                seenTesterIds[bg2.testerId] = true;
                _addProductsFromTesterId(map, bg2.testerId);
            }
        }
        var sorted = Object.keys(map).sort();
        return sorted.map(function(n) { return { name: n, desc: map[n] || '' }; });
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
     * Walk the chain to collect effective products.
     */
    function _effectiveProducts(node) {
        if (!node) return { products: [], source: 'none' };
        if (_hasOverride(node)) {
            return { products: Object.keys(node.productMask).sort(), source: 'override' };
        }
        if (node.parentId) {
            return _effectiveProducts(GT.groupSettings.groups.get(node.parentId));
        }
        if (node.baseGroupId) {
            var bg = GT.groupSettings.groups.get(node.baseGroupId);
            if (bg) {
                return { products: bg.products || [], source: 'baseGroup', name: bg.name || node.baseGroupId };
            }
        }
        return { products: [], source: 'none' };
    }

    function _initDirtyFromActiveNode() {
        var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
        var id = sel ? sel.getFirst() : null;
        if (!id) return;
        var node = GT.groupSettings.groups && GT.groupSettings.groups.get(id);
        if (!node || !node.isDerived) return;
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
        var draft = GT.ui && GT.ui.getAddDraft ? GT.ui.getAddDraft() : null;
        var preselectedBaseGroupId = (draft && draft.preselectedBaseGroupId) || null;
        var preselectedParentDerivedId = (draft && draft.preselectedParentDerivedId) || null;
        var parentLabel = '';
        var parentType = '';

        if (preselectedParentDerivedId) {
            var pNode = GT.groupSettings.groups && GT.groupSettings.groups.get(preselectedParentDerivedId);
            parentLabel = pNode ? (pNode.name || pNode.id) : preselectedParentDerivedId;
            parentType = 'derived';
        } else if (preselectedBaseGroupId) {
            var bg = GT.groupSettings.groups.get(preselectedBaseGroupId);
            parentLabel = bg ? (bg.name || bg.id) : preselectedBaseGroupId;
            parentType = 'base';
        }

        var html = '<div style="margin-bottom:16px;">';
        html += '<h3 style="margin:0 0 4px 0;font-size:15px;">品种筛选</h3>';
        if (parentType === 'derived') {
            html += '<p style="margin:0 0 8px 0;font-size:12px;color:#7c3aed;">关联上级派生组: <strong>' + escapeHTML(parentLabel) + '</strong></p>';
        } else if (parentType === 'base') {
            html += '<p style="margin:0 0 8px 0;font-size:12px;color:#0078d4;">关联基础组: <strong>' + escapeHTML(parentLabel) + '</strong></p>';
        }
        html += '<p style="margin:0;font-size:12px;color:#666;">选择派生组包含的品种（留空则继承上级全部品种）</p>';
        html += '</div>';

        if (allProducts.length === 0) {
            html += '<div style="padding:24px;text-align:center;color:#888;">未找到品种数据</div>';
        } else {
            // Select all / Deselect all
            html += '<div style="margin-bottom:8px;">';
            html += '<button id="derived-products-select-all" style="padding:2px 10px;font-size:12px;border:1px solid #d0d5dd;border-radius:4px;cursor:pointer;margin-right:6px;">全选</button>';
            html += '<button id="derived-products-deselect-all" style="padding:2px 10px;font-size:12px;border:1px solid #d0d5dd;border-radius:4px;cursor:pointer;">取消全选</button>';
            html += '<span style="margin-left:12px;font-size:12px;color:#666;">已选 <span id="derived-products-count">0</span> / ' + allProducts.length + ' 个品种</span>';
            html += '</div>';

            html += '<div style="max-height:300px;overflow-y:auto;border:1px solid #e5e7eb;border-radius:6px;padding:8px;background:#fafbfc;">';
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
        var ids = GT.ui && GT.ui.getEditSelection ? GT.ui.getEditSelection() : null;
        if (!ids) return;
        var selIds = Array.isArray(ids) ? ids : (ids.groupIds || Object.keys(ids).filter(function(k) { return ids[k]; }));
        if (selIds.length !== 1) return;
        var node = GT.groupSettings.groups && GT.groupSettings.groups.get(selIds[0]);
        if (!node || !node.isDerived) return;
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
        var draft = GT.ui && GT.ui.getAddDraft ? GT.ui.getAddDraft() : null;
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
        GT.state.on('derivedGraphChanged', _onDerivedGraphChanged);
        render();
    }

    function unmount() {
        _mounted = false;
        _activeId = null;
        _setDirtyProductMask({});
        var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
        if (sel && sel.off) sel.off('selectionChanged', _onSelectionChanged);
        GT.state.off('derivedGraphChanged', _onDerivedGraphChanged);
    }

    function refresh() { if (_mounted) render(); }

    function getSelectedProducts() {
        var mask = _dirtyProductMask();
        return Object.keys(mask).filter(function(k) { return mask[k]; });
    }

    function getAllProducts() {
        return _allProducts().map(function(p) { return p.name; });
    }

    // ---------------------------------------------------------------------------
    // Export
    // ---------------------------------------------------------------------------

    GT.panels.config.derived = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
        getSelectedProducts: getSelectedProducts,
        getAllProducts: getAllProducts,
    };

    // Register as category-3 config panel with productMask field
    if (window.GT_CONFIG_REGISTRY) {
        window.GT_CONFIG_REGISTRY.register({
            name: 'derived',
            label: '品种筛选',
            panel: GT.panels.config.derived,
            fields: ['productMask'],
        }, 'config-derived');
    }

    GT.log('panels.config.derived loaded');
})();
