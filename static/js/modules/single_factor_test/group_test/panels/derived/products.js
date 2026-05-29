/**
 * panels/derived/products.js — Derived group products panel (Tab 2, sub-tab "品种")
 *
 * Phase 4 UI panel. Shows the effective product set for the selected derived
 * group node. Read-only display of inherited or overridden product mask.
 *
 * For derived groups, the product set comes from the inherited chain:
 * - If node has overridden productMask, show it
 * - Otherwise show effective products from parent/baseGroup chain
 *
 * Contract:
 *   GT.state.getActiveDerivedNodeId() → id|null
 *   GT.state.on('activeDerivedNodeChanged', cb)
 *   GT.state.on('derivedGraphChanged', cb)
 *   GT.datamodel.derived_graph.get(id) → node|null
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.derived) { GT.panels.derived = {}; }

    var CONTAINER_ID = 'derived-products-panel';

    var _mounted = false;
    var _activeId = null;

    function $(id) { return document.getElementById(id); }

    function _getNode() {
        var id = GT.state.getActiveDerivedNodeId();
        if (!id) return null;
        return GT.datamodel.derived_graph.get(id);
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
    // Render
    // ---------------------------------------------------------------------------

    function render() {
        var container = $(CONTAINER_ID);
        if (!container) return;

        var node = _getNode();
        if (!node) {
            container.innerHTML = '<div style="padding:24px;text-align:center;color:#888;">请在「树」中选择一个派生组节点</div>';
            _activeId = null;
            return;
        }

        _activeId = node.id;
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
        GT.state.on('activeDerivedNodeChanged', _onDerivedNodeChanged);
        GT.state.on('derivedGraphChanged', _onDerivedGraphChanged);
        render();
    }

    function unmount() {
        _mounted = false;
        _activeId = null;
        GT.state.off('activeDerivedNodeChanged', _onDerivedNodeChanged);
        GT.state.off('derivedGraphChanged', _onDerivedGraphChanged);
    }

    function refresh() { if (_mounted) render(); }

    // ---------------------------------------------------------------------------
    // Export
    // ---------------------------------------------------------------------------

    GT.panels.derived.products = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
    };

    GT.log('panels.derived.products loaded');
})();
