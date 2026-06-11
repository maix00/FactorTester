/**
 * registry/chips.js — Unified Chip System
 *
 * Chips are small badge-like elements that display group metadata.
 * Three categories:
 *   'info'    — tester label, factor alias, group index/count (built-in)
 *   'config'  — fee, rebalance, etc. (from registered config panels, bridged in registry.js)
 *   'derived' — product masks, overrides (for derived groups)
 *
 * This module is loaded AFTER registry/group-settings.js and attaches to GT_CONFIG_REGISTRY.
 * registry.js calls initChipSystem() to auto-register the built-in info provider and bridge helpers.
 *
 * Usage:
 *   GT_CONFIG_REGISTRY.registerChipProvider({ category: 'derived', name: 'products', getChips: fn })
 *   GT_CONFIG_REGISTRY.getAllChips(group)            → all chips
 *   GT_CONFIG_REGISTRY.getAllChips(group, 'info')    → only info chips
 *   GT_CONFIG_REGISTRY.getAllChips(group, ['info','config']) → info + config
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    // Ensure GT_CONFIG_REGISTRY exists (registry.js must be loaded first)
    var REG = window.GT_CONFIG_REGISTRY;
    if (!REG) throw new Error('GT_CONFIG_REGISTRY not loaded — load registry/group-settings.js first');

    // ── Chip providers ──
    var _chipProviders = []; // [{ category, name, getChips }]

    /** Chip category constants */
    var CHIP_CATEGORY = { INFO: 'info', CONFIG: 'config', DERIVED: 'derived' };

    /** Standard chip styles */
    var CHIP_STYLE_PLAIN    = 'display:inline-block;background:#e5e7eb;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;color:#374151;';
    var CHIP_STYLE_CLICKABLE = 'display:inline-block;cursor:pointer;background:#c7d2fe;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;color:#312e81;';

    // ── Public API ──

    /**
     * Register a chip provider.
     * @param {object} def — { category: 'info'|'config'|'derived', name: string, getChips: function(group) → chip[] }
     *   Each chip: { label, html, style?, onClick? }
     */
    function registerChipProvider(def) {
        if (!def || !def.category || !def.name || typeof def.getChips !== 'function') {
            GT.log('chips: invalid chip provider, skipping');
            return;
        }
        // Deduplicate by name
        for (var i = 0; i < _chipProviders.length; i++) {
            if (_chipProviders[i].name === def.name) {
                _chipProviders[i] = def;
                return;
            }
        }
        _chipProviders.push(def);
    }

    /**
     * Get all chips for a group, optionally filtered by category.
     * For derived groups: automatically resolves config from base group.
     *
     * @param {object} group — group settings object
     * @param {string|string[]} [categories] — optional filter: 'info', 'config', 'derived', or array thereof
     * @returns {{label, html, style, onClick, category}[]}
     */
    function getAllChips(group, categories) {
        if (!group) return [];

        // Normalize categories filter
        var filterSet = null;
        if (categories) {
            filterSet = {};
            var cats = Array.isArray(categories) ? categories : [categories];
            for (var ci = 0; ci < cats.length; ci++) { filterSet[cats[ci]] = true; }
        }

        var chips = [];
        var seen = {};

        for (var i = 0; i < _chipProviders.length; i++) {
            var prov = _chipProviders[i];
            if (filterSet && !filterSet[prov.category]) continue;

            // INFO chips inherit from root group for child groups
            var g = group;
            if (prov.category === CHIP_CATEGORY.INFO && group.parentId) {
                var GT2 = window.GroupTest;
                if (GT2 && GT2.groupSettings && GT2.groupSettings.groups && GT2.groupSettings.groups.resolveRootField) {
                    // Walk parentId chain to root for INFO chips
                    var root = group;
                    var visited = {};
                    while (root && root.parentId) {
                        if (visited[root.id]) break;
                        visited[root.id] = true;
                        root = GT2.groupSettings.groups.get(root.parentId);
                    }
                    if (root) g = root;
                }
            }
            var provChips = prov.getChips(g);
            if (provChips && provChips.length) {
                for (var j = 0; j < provChips.length; j++) {
                    var c = provChips[j];
                    if (c && c.label && !seen[c.label]) {
                        seen[c.label] = true;
                        c.category = prov.category;
                        if (!c.style) c.style = CHIP_STYLE_PLAIN;
                        chips.push(c);
                    }
                }
            }
        }

        return chips;
    }

    // ── Built-in info chip provider (tester, factor, group index) ──

    /**
     * Resolve a tester's display label from window.submissions.
     */
    function _resolveTesterLabel(testerId) {
        if (!testerId) return '';
        var subs = window.submissions || [];
        for (var i = 0; i < subs.length; i++) {
            if (String(subs[i].id) === String(testerId)) {
                return subs[i].product_group || subs[i].label || ('测试器 #' + subs[i].id);
            }
        }
        return String(testerId);
    }

    function _registerBuiltinInfoProvider() {
        registerChipProvider({
            category: CHIP_CATEGORY.INFO,
            name: 'builtin-info',
            getChips: function(g) {
                var chips = [];
                var isChild = !!(g.parentId);

                // Resolve root values via parentId chain
                var resolveRoot = (typeof resolveRootField === 'function')
                    ? function(field) { return resolveRootField(g, field); }
                    : function(field) { return g[field]; };

                // 1) Factor alias — child always inherits from root
                var factorAlias = isChild ? resolveRoot('factorAlias') : g.factorAlias;
                if (factorAlias) {
                    chips.push({ label: 'factor', html: factorAlias, style: CHIP_STYLE_PLAIN });
                }

                // 2) Tester label — child always inherits from root
                var testerId = isChild ? resolveRoot('testerId') : g.testerId;
                if (testerId) {
                    var label = _resolveTesterLabel(testerId);
                    if (label) {
                        chips.push({ label: 'tester', html: label, style: CHIP_STYLE_CLICKABLE });
                    }
                }

                // 3) Group index / count — child always inherits from root
                var groupCount, groupIndex;
                groupCount = isChild ? resolveRoot('groupCount') : g.groupCount;
                groupIndex = isChild ? resolveRoot('groupIndex') : g.groupIndex;
                if (groupCount) {
                    var gi = groupIndex || 1;
                    chips.push({ label: 'group-index', html: gi + '/' + groupCount, style: CHIP_STYLE_PLAIN });
                }

                return chips;
            }
        });
    }

    // ── Built-in derived chip provider (product mask for derived groups) ──

    /** Product expanded state — toggled by chip onClick, read by getChips to set triangle */
    var _expandedProducts = {};

    /**
     * Resolve the effective product list for a derived group node.
     */
    function _normalizeProduct(raw) {
        if (typeof raw === 'string') return { name: raw, desc: '' };
        if (raw && raw.name) return { name: raw.name, desc: raw.desc || '' };
        return null;
    }

    function _productsFromTester(testerId) {
        var subs = window.submissions || [];
        for (var si = 0; si < subs.length; si++) {
            if (String(subs[si].id) !== String(testerId)) continue;
            var raw = (Array.isArray(subs[si].products) && subs[si].products.length)
                ? subs[si].products
                : (subs[si].product_groups || []);
            var out = [];
            for (var pi = 0; pi < raw.length; pi++) {
                var item = _normalizeProduct(raw[pi]);
                if (item && item.name) out.push(item);
            }
            return out;
        }
        return [];
    }

    function _filterProducts(products, mask) {
        if (!mask || Object.keys(mask).length === 0) return products;
        return products.filter(function(p) { return p && mask[p.name]; });
    }

    function _getDerivedProducts(node, seen) {
        if (!node) return [];
        seen = seen || {};
        if (seen[node.id]) return [];
        seen[node.id] = true;

        var GT4 = window.GroupTest;
        var groups = GT4 && GT4.groupSettings && GT4.groupSettings.groups;
        if (!groups) return [];

        var inherited = [];
        if (node.parentId) {
            inherited = _getDerivedProducts(groups.get(node.parentId), seen);
        } else {
            // Root node: get products from its own testerId
            if (!node.testerId) return [];
            inherited = _productsFromTester(node.testerId);
        }

        return _filterProducts(inherited, node.productMask);
    }

    /**
     * Generate product list HTML for a derived group (expanded state).
     * Rendered as a sibling div after the chip row, controlled by chip onClick.
     */
    function _renderDerivedProductList(node, products) {
        var h = '<div class="gt-chip-derived-products" data-dg-id="' + escapeHTML(node.id) + '"';
        h += ' style="padding:4px 8px;border-left:2px solid #c7d2fe;font-size:11px;margin-top:2px;">';
        for (var pi = 0; pi < products.length; pi++) {
            var pn = products[pi].name;
            var pd = products[pi].desc || '';
            h += '<div style="padding:2px 0;display:flex;align-items:baseline;">';
            h += '<a href="/products?product=' + encodeURIComponent(pn) + '" target="_blank"';
            h += ' style="color:#0078d4;text-decoration:none;font-weight:600;margin-right:8px;"';
            h += ' onclick="event.stopPropagation();">' + escapeHTML(pn) + '</a>';
            if (pd) h += '<span style="color:#9ca3af;">' + escapeHTML(pd) + '</span>';
            h += '</div>';
        }
        h += '</div>';
        return h;
    }

    /** Escape HTML entities (lightweight, no external dep) */
    function escapeHTML(str) {
        if (!str) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function _registerBuiltinDerivedProvider() {
        registerChipProvider({
            category: CHIP_CATEGORY.DERIVED,
            name: 'builtin-derived-products',
            getChips: function(g) {
                if (!g || !g.parentId) return [];
                var products = _getDerivedProducts(g);
                if (products.length === 0) return [];
                var isExpanded = _expandedProducts[g.id] === true;
                var tri = isExpanded ? '▾' : '▸';
                return [{
                    label: 'derived-products',
                    html: '📋 ' + products.length + '品种 ' + tri,
                    style: CHIP_STYLE_CLICKABLE,
                    /**
                     * onClick is called by the rendering layer with (chipElement, group).
                     * Toggles expanded state and replaces DOM inline (no full re-render needed).
                     */
                    onClick: function(chipEl, group) {
                        if (!chipEl || !group) return;
                        var dgId = group.id;
                        var wasExpanded = _expandedProducts[dgId] === true;

                        // Remove any existing product list for this group
                        var existingList = chipEl.parentNode
                            ? chipEl.parentNode.querySelector('.gt-chip-derived-products[data-dg-id="' + dgId + '"]')
                            : null;
                        if (existingList) {
                            existingList.remove();
                        }

                        if (wasExpanded) {
                            // Collapse
                            _expandedProducts[dgId] = false;
                            chipEl.textContent = '📋 ' + _getDerivedProducts(group).length + '品种 ▸';
                        } else {
                            // Expand — inject product list after chip's parent row
                            _expandedProducts[dgId] = true;
                            chipEl.textContent = '📋 ' + _getDerivedProducts(group).length + '品种 ▾';
                            var products = _getDerivedProducts(group);
                            var listHTML = _renderDerivedProductList(group, products);
                            // Insert after the chip's parent (the flex container row)
                            chipEl.parentNode.insertAdjacentHTML('afterend', listHTML);
                        }
                    }
                }];
            }
        });
    }

    // ── Bridge: allow registry.js to auto-register config panel getChips as chip providers ──

    /**
     * If a config panel def has getChips, auto-register it as a 'config' chip provider.
     * Called by registry.js when a panel is registered.
     */
    function bridgeConfigPanel(def) {
        if (def.panel && typeof def.panel.getChips === 'function') {
            registerChipProvider({
                category: CHIP_CATEGORY.CONFIG,
                name: 'config-' + def.name,
                getChips: def.panel.getChips
            });
        }
    }

    // ── Attach to GT_CONFIG_REGISTRY ──

    REG.registerChipProvider = registerChipProvider;
    REG.getAllChips = getAllChips;
    REG.CHIP_CATEGORY = CHIP_CATEGORY;
    REG.CHIP_STYLE_PLAIN = CHIP_STYLE_PLAIN;
    REG.CHIP_STYLE_CLICKABLE = CHIP_STYLE_CLICKABLE;

    // Expose expanded products state so renderers (list/index.js) can read/use it
    REG._expandedProducts = _expandedProducts;

    // Export bridge function (not attached to REG, called internally by registry.js)
    REG._bridgeConfigToChipProvider = bridgeConfigPanel;

    // Register the built-in info provider immediately
    _registerBuiltinInfoProvider();

    // Register the built-in derived product provider
    _registerBuiltinDerivedProvider();

    GT.log('registry/chips loaded');
})();
