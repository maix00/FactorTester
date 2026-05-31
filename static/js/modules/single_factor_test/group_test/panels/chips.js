/**
 * panels/chips.js — Unified Chip System
 *
 * Chips are small badge-like elements that display group metadata.
 * Three categories:
 *   'info'    — tester label, factor alias, group index/count (built-in)
 *   'config'  — fee, rebalance, etc. (from registered config panels, bridged in registry.js)
 *   'derived' — product masks, overrides (for derived groups)
 *
 * This module is loaded AFTER panels/config/registry.js and attaches to GT_CONFIG_REGISTRY.
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
    if (!REG) throw new Error('GT_CONFIG_REGISTRY not loaded — load panels/config/registry.js first');

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
     * @param {object} group — group object from datamodel
     * @param {string|string[]} [categories] — optional filter: 'info', 'config', 'derived', or array thereof
     * @returns {{label, html, style, onClick, category}[]}
     */
    function getAllChips(group, categories) {
        if (!group) return [];

        // Resolve config group: for derived groups, use base group for config chips
        var configGroup = group;
        if (group.isDerived && group.baseGroupId) {
            var GT2 = window.GroupTest;
            if (GT2 && GT2.datamodel && GT2.datamodel.groups) {
                var bg = GT2.datamodel.groups.get(group.baseGroupId);
                if (bg) configGroup = bg;
            }
        }

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

            var g = (prov.category === CHIP_CATEGORY.CONFIG) ? configGroup : group;
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

                // Resolve base group for derived groups
                var bg = null;
                if (g.isDerived && g.baseGroupId) {
                    var GT3 = window.GroupTest;
                    if (GT3 && GT3.datamodel && GT3.datamodel.groups) {
                        bg = GT3.datamodel.groups.get(g.baseGroupId);
                    }
                }

                // 1) Factor alias — derived always inherits from base
                var factorAlias = g.isDerived && bg ? bg.factorAlias : g.factorAlias;
                if (factorAlias) {
                    chips.push({ label: 'factor', html: factorAlias, style: CHIP_STYLE_PLAIN });
                }

                // 2) Tester label — derived always inherits from base
                var testerId = g.isDerived && bg ? bg.testerId : g.testerId;
                if (testerId) {
                    var label = _resolveTesterLabel(testerId);
                    if (label) {
                        chips.push({ label: 'tester', html: label, style: CHIP_STYLE_CLICKABLE });
                    }
                }

                // 3) Group index / count — derived always inherits from base
                var groupCount, groupIndex;
                if (g.isDerived && bg) {
                    groupCount = bg.groupCount;
                    groupIndex = bg.groupIndex;
                } else {
                    groupCount = g.groupCount;
                    groupIndex = g.groupIndex;
                }
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
    function _getDerivedProducts(node) {
        if (!node || !node.baseGroupId || node.baseGroupId === '__batch__') return [];

        var GT4 = window.GroupTest;
        var groups = GT4 && GT4.datamodel && GT4.datamodel.groups;
        if (!groups) return [];

        var bg = groups.get(node.baseGroupId);
        if (!bg || !bg.testerId) return [];

        // Resolve tester's products
        var subs = window.submissions || [];
        var allProds = [];
        for (var si = 0; si < subs.length; si++) {
            if (String(subs[si].id) === String(bg.testerId)) {
                var pgs = subs[si].product_groups || [];
                for (var pgi = 0; pgi < pgs.length; pgi++) {
                    var pg = pgs[pgi];
                    if (pg && pg.name) {
                        allProds.push({ name: pg.name, desc: pg.desc || '' });
                    }
                }
                break;
            }
        }

        if (node.productMask && Object.keys(node.productMask).length > 0) {
            var filtered = [];
            for (var fi = 0; fi < allProds.length; fi++) {
                if (node.productMask[allProds[fi].name]) filtered.push(allProds[fi]);
            }
            return filtered;
        }
        return allProds;
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
                if (!g || !g.isDerived) return [];
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

    GT.log('panels/chips loaded');
})();
