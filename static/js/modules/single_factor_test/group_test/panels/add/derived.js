/**
 * panels/add/derived.js — Add-flow panel: "新建派生组" (category-2)
 *
 * Dual-mode panel:
 *   ADD mode (no active node): product multi-select for creating new derived group
 *   View mode (active node): read-only display of inherited or overridden product mask
 *
 * Contract:
 *   GT.state.getActiveDerivedNodeId() → id|null
 *   GT.state.on('activeDerivedNodeChanged', cb)
 *   GT.state.on('derivedGraphChanged', cb)
 *   GT.datamodel.derived_graph.get(id) → node|null
 *   GT.datamodel.base_groups.getAll() → base groups (for product sourcing)
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.derived) { GT.panels.derived = {}; }

    var CONTAINER_ID = 'derived-products-panel';

    var _mounted = false;
    var _activeId = null;
    /** In add mode, tracks selected product codes */
    var _selectedProducts = {};

    function $(id) { return document.getElementById(id); }

    function _getNode() {
        var id = GT.state.getActiveDerivedNodeId();
        if (!id) return null;
        return GT.datamodel.derived_graph.get(id);
    }

    /**
     * Collect all available products from base groups.
     */
    function _allProducts() {
        var set = {};
        var baseGroups = GT.datamodel.base_groups.getAll();
        for (var i = 0; i < baseGroups.length; i++) {
            var prods = baseGroups[i].products || [];
            for (var j = 0; j < prods.length; j++) {
                set[prods[j]] = true;
            }
        }
        return Object.keys(set).sort();
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
            return _effectiveProducts(GT.datamodel.derived_graph.get(node.parentId));
        }
        if (node.baseGroupId) {
            var bg = GT.datamodel.base_groups.get(node.baseGroupId);
            if (bg) {
                return { products: bg.products || [], source: 'baseGroup', name: bg.name || node.baseGroupId };
            }
        }
        return { products: [], source: 'none' };
    }

    // ---------------------------------------------------------------------------
    // Render: Add mode (no active node) — product multi-select
    // ---------------------------------------------------------------------------

    function _renderAddMode(container) {
        var allProducts = _allProducts();

        var html = '<div style="margin-bottom:16px;">';
        html += '<h3 style="margin:0 0 4px 0;font-size:15px;">品种筛选</h3>';
        html += '<p style="margin:0;font-size:12px;color:#666;">选择派生组包含的品种（留空则继承基础组全部品种）</p>';
        html += '</div>';

        if (allProducts.length === 0) {
            html += '<div style="padding:24px;text-align:center;color:#888;">未找到品种数据，请先在基础组定义中创建基础组</div>';
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
                var checked = _selectedProducts[p] ? ' checked' : '';
                html += '<label style="display:inline-flex;align-items:center;margin:3px 8px 3px 0;padding:3px 8px;border:1px solid #e5e7eb;border-radius:4px;cursor:pointer;font-size:12px;' + (_selectedProducts[p] ? 'background:#e8f0fe;border-color:#80bdff;' : 'background:#fff;') + '">';
                html += '<input type="checkbox" class="derived-product-cb" value="' + p + '"' + checked + ' style="margin-right:4px;">';
                html += '<span style="font-family:monospace;">' + p + '</span>';
                html += '</label>';
            }
            html += '</div>';
        }

        container.innerHTML = html;
        _bindAddModeEvents(container, allProducts);
    }

    function _bindAddModeEvents(container, allProducts) {
        // Checkbox toggle
        var cbs = container.querySelectorAll('.derived-product-cb');
        for (var i = 0; i < cbs.length; i++) {
            cbs[i].addEventListener('change', function() {
                _selectedProducts[this.value] = this.checked;
                _updateCount(container);
                _highlightLabel(this);
            });
        }

        // Select all
        var selectAll = container.querySelector('#derived-products-select-all');
        if (selectAll) {
            selectAll.addEventListener('click', function() {
                for (var j = 0; j < allProducts.length; j++) {
                    _selectedProducts[allProducts[j]] = true;
                }
                _renderAddMode(container);
            });
        }

        // Deselect all
        var deselectAll = container.querySelector('#derived-products-deselect-all');
        if (deselectAll) {
            deselectAll.addEventListener('click', function() {
                _selectedProducts = {};
                _renderAddMode(container);
            });
        }
    }

    function _updateCount(container) {
        var countEl = container.querySelector('#derived-products-count');
        if (countEl) {
            countEl.textContent = Object.keys(_selectedProducts).filter(function(k) { return _selectedProducts[k]; }).length;
        }
    }

    function _highlightLabel(cb) {
        var label = cb.closest('label');
        if (label) {
            label.style.background = cb.checked ? '#e8f0fe' : '#fff';
            label.style.borderColor = cb.checked ? '#80bdff' : '#e5e7eb';
        }
    }

    // ---------------------------------------------------------------------------
    // Render: View mode (active node) — read-only product display
    // ---------------------------------------------------------------------------

    function _renderViewMode(container, node) {
        var isOverridden = _hasOverride(node);
        var eff = _effectiveProducts(node);
        var products = eff.products;

        var html = '';

        html += '<div style="margin-bottom:16px;">';
        html += '<span style="font-size:14px;font-weight:600;">品种来源: </span>';
        if (isOverridden) {
            html += '<span style="color:#d97706;font-size:13px;">当前节点覆盖</span>';
        } else {
            var srcLabel = eff.source === 'baseGroup' ? '基础组: ' + (eff.name || '') : '继承自父节点';
            html += '<span style="color:#0078d4;font-size:13px;">' + srcLabel + '</span>';
        }
        html += '</div>';

        if (products.length === 0) {
            html += '<div style="padding:12px;background:#f9fafb;border-radius:6px;border:1px solid #e5e7eb;text-align:center;color:#888;">无品种配置</div>';
        } else {
            html += '<div style="padding:12px;background:#f9fafb;border-radius:6px;border:1px solid #e5e7eb;">';
            html += '<div style="font-size:12px;color:#666;margin-bottom:8px;">有效品种 (' + products.length + ' 个)</div>';
            html += '<div style="display:flex;flex-wrap:wrap;gap:6px;">';
            for (var i = 0; i < products.length; i++) {
                html += '<span style="padding:2px 8px;background:#e8f0fe;border-radius:12px;font-size:12px;font-family:monospace;">' + products[i] + '</span>';
            }
            html += '</div></div>';
        }

        container.innerHTML = html;
    }

    // ---------------------------------------------------------------------------
    // Render dispatcher
    // ---------------------------------------------------------------------------

    function render() {
        var container = $(CONTAINER_ID);
        if (!container) return;

        var node = _getNode();
        if (!node) {
            // ADD mode — show product multi-select for new derived group
            _activeId = null;
            _renderAddMode(container);
        } else {
            _activeId = node.id;
            _renderViewMode(container, node);
        }
    }

    // ---------------------------------------------------------------------------
    // Event handlers
    // ---------------------------------------------------------------------------

    function _onDerivedNodeChanged() { if (_mounted) render(); }
    function _onDerivedGraphChanged() { if (_mounted) render(); }

    // ---------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------

    function mount() {
        _mounted = true;
        _activeId = GT.state.getActiveDerivedNodeId();
        // Reset product selection on mount for fresh add-mode state
        _selectedProducts = {};
        GT.state.on('activeDerivedNodeChanged', _onDerivedNodeChanged);
        GT.state.on('derivedGraphChanged', _onDerivedGraphChanged);
        render();
    }

    function unmount() {
        _mounted = false;
        _activeId = null;
        _selectedProducts = {};
        GT.state.off('activeDerivedNodeChanged', _onDerivedNodeChanged);
        GT.state.off('derivedGraphChanged', _onDerivedGraphChanged);
    }

    function refresh() { if (_mounted) render(); }

    // Expose selected products for external consumption (e.g., by submit)
    function getSelectedProducts() {
        return Object.keys(_selectedProducts).filter(function(k) { return _selectedProducts[k]; });
    }

    // ---------------------------------------------------------------------------
    // Export
    // ---------------------------------------------------------------------------

    GT.panels.add = GT.panels.add || {};
    GT.panels.add.derived = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
        getSelectedProducts: getSelectedProducts,
    };

    GT.log('panels.derived.products loaded');
})();
