/**
 * panels/list/helpers.js — 公共辅助函数
 *
 * 挂载到 GT.panels.list._helpers（内部用）。
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    GT.panels = GT.panels || {};
    GT.panels.list = GT.panels.list || {};

    // ── Expand caches ──
    var _productSelectionProductsCache = {};
    var _nodeFeeCache = {};

    function invalidateExpandCaches() {
        _productSelectionProductsCache = {};
        _nodeFeeCache = {};
    }

    function $(id) { return document.getElementById(id); }

    function escapeHTML(str) { return GT.escapeHTML(str); }

    // ── Chip badge class marker; visual styling is centralized in CSS. ──
    var CHIP_STYLE = '';
    var CHIP_STYLE_PLAIN = '';

    function renderChipHtml(labelOrText, value) {
        if (window.ChipRenderer && typeof window.ChipRenderer.chipHtml === 'function') {
            if (value !== undefined && value !== null && value !== '') {
                return window.ChipRenderer.chipHtml(
                    { chip_template: '{label}: {value}' },
                    { valueOf: function(k) { return k === 'label' ? String(labelOrText || '') : String(value); },
                      escapeHTML: escapeHTML,
                      renderChipHtml: GT.backendSettings && typeof GT.backendSettings.renderChipHtml === 'function'
                          ? GT.backendSettings.renderChipHtml : undefined }
                );
            }
            return window.ChipRenderer.chipHtml(
                { chip_template: '{label}: {value}' },
                { escapeHTML: escapeHTML,
                  resolve: function() { return ''; },
                  valueOf: function(k) { return k === 'value' ? String(labelOrText == null ? '' : labelOrText) : ''; },
                  renderChipHtml: GT.backendSettings && typeof GT.backendSettings.renderChipHtml === 'function'
                      ? GT.backendSettings.renderChipHtml : undefined }
            );
        }
        return escapeHTML(value === undefined ? labelOrText : (labelOrText + ': ' + value));
    }

    function selectionId(selection) {
        var utils = window.ProductPathSelectionUtils;
        return utils && utils.selectionId ? utils.selectionId(selection)
            : (selection ? String(selection.product_path_selection_id || selection.selection_id || selection.id || '') : '');
    }

    function resolveProductPathSelection(selectionOrId) {
        var selection = (typeof selectionOrId === 'object' && selectionOrId) ? selectionOrId : null;
        var sid = selection ? selectionId(selection) : String(selectionOrId || '');
        var loaded = GT.backendSettings && typeof GT.backendSettings.getProductPathSelections === 'function'
            ? GT.backendSettings.getProductPathSelections()
            : [];
        if (!sid && !selection) return selection;
        for (var i = 0; i < loaded.length; i++) {
            if (selectionId(loaded[i]) === sid) return loaded[i];
        }
        if (selection) {
            var templateId = String(selection.product_group_template_id || selection.path_id || '').trim();
            var productGroup = String(selection.product_group || selection.product_group_name || selection.label || selection.name || '').trim();
            var paths = selection.paths || selection.selected_paths || [];
            var pathKey = Array.isArray(paths) ? paths.map(function(path) { return String(path || '').trim(); }).filter(Boolean).sort().join('|') : '';
            for (var j = 0; j < loaded.length; j++) {
                var candidate = loaded[j] || {};
                if (templateId && String(candidate.product_group_template_id || candidate.path_id || candidate.id || candidate.product_path_selection_id || '') === templateId) return candidate;
                if (productGroup && String(candidate.product_group || candidate.product_group_name || candidate.label || candidate.name || '') === productGroup) return candidate;
                var candidatePaths = candidate.paths || candidate.selected_paths || [];
                var candidatePathKey = Array.isArray(candidatePaths) ? candidatePaths.map(function(path) { return String(path || '').trim(); }).filter(Boolean).sort().join('|') : '';
                if (pathKey && candidatePathKey && pathKey === candidatePathKey) return candidate;
            }
        }
        return selection;
    }

    function nodeProductPathSelection(node) {
        if (!node) return null;
        if (node.parentId) {
            return (GT.groupSettings.groups && GT.groupSettings.groups.resolveRootField)
                ? GT.groupSettings.groups.resolveRootField(node, 'product_path_selection') : null;
        }
        return node.product_path_selection || null;
    }

    /** Get products list from a product path selection (cached) */
    function productPathSelectionProducts(selectionOrId) {
        var selection = resolveProductPathSelection(selectionOrId);
        var sid = selection ? selectionId(selection) : String(selectionOrId || '');
        if (_productSelectionProductsCache[sid]) return _productSelectionProductsCache[sid];
        var utils = window.ProductPathSelectionUtils;
        var result = utils && utils.selectionProducts ? utils.selectionProducts(selection) : [];
        _productSelectionProductsCache[sid] = result;
        return result;
    }

    function productPathSelectionLabel(selectionOrId) {
        var selection = resolveProductPathSelection(selectionOrId);
        var sid = selection ? selectionId(selection) : String(selectionOrId || '');
        var utils = window.ProductPathSelectionUtils;
        if (selection && utils && utils.selectionDisplayLabel) return utils.selectionDisplayLabel(selection) || '—';
        if (selection && utils && utils.selectionLabel) return utils.selectionLabel(selection) || '—';
        if (selection) {
            var label = selection.product_group || selection.label || selection.name || sid;
            if (selection.product_group_template_id || selection.product_group || selection.product_group_name) return label + ' · 产品组';
            if (selection.path_id) return label + ' · 路径组';
            return label || '—';
        }
        return sid || '—';
    }

    function dgName(id) {
        if (!id) return '—';
        if (GT.groupSettings.groups && GT.groupSettings.groups.get) {
            var dg = GT.groupSettings.groups.get(id);
            if (dg) return dg.name || id;
        }
        return id;
    }

    function getGroup(id) {
        return (GT.groupSettings.groups && GT.groupSettings.groups.get) ? GT.groupSettings.groups.get(id) : null;
    }

    function nodeProductPathSelectionId(node) {
        return selectionId(nodeProductPathSelection(node)) || null;
    }

    function nodeProducts(node) {
        var selection = nodeProductPathSelection(node);
        var allProds = selection ? productPathSelectionProducts(selection) : [];
        if (allProds.length === 0) return [];
        if (node.productMask && Object.keys(node.productMask).length > 0) {
            var filtered = [];
            for (var i = 0; i < allProds.length; i++) {
                if (node.productMask[allProds[i].name]) filtered.push(allProds[i]);
            }
            return filtered;
        }
        return allProds;
    }

    /**
     * Resolve group fields by walking parentId chain for null values.
     * Traverses all own keys on the node and fills null/undefined from
     * the nearest ancestor that has a non-null value, falling back to
     * GT.groupSettings.getFieldDefault as a last resort.
     */
    function synthGroupResolved(node) {
        if (!node) return null;
        var GS = GT.groupSettings;
        var groups = GS.groups;
        var resolved = {};
        var keys = Object.keys(node);
        for (var i = 0; i < keys.length; i++) {
            var k = keys[i];
            var v = node[k];
            if (v != null) {
                resolved[k] = v;
                continue;
            }
            // walk parentId chain
            var cur = node;
            var visited = {};
            var found = false;
            while (cur && cur.parentId) {
                if (visited[cur.id]) break;
                visited[cur.id] = true;
                var parent = groups && groups.get(cur.parentId);
                if (!parent) break;
                if (parent[k] != null) {
                    resolved[k] = parent[k];
                    found = true;
                    break;
                }
                cur = parent;
            }
            if (!found) {
                resolved[k] = GS.getFieldDefault(k);
            }
        }
        return resolved;
    }

    function derivedFeeDisplay(node) {
        var values = GT.backendSettings && GT.backendSettings.groupOverrideValues
            ? GT.backendSettings.groupOverrideValues(node && node.id)
            : null;
        var mode = values && values.fee_mode;
        if (mode === 'none' || !mode) return '—';
        if (mode === 'market') return '市场规则';
        if (mode === 'custom') return values.custom_fee_rate != null ? Number(values.custom_fee_rate).toFixed(6) : '自定义';
        return mode;
    }

    function derivedRebalanceLabel(node) {
        var values = GT.backendSettings && GT.backendSettings.groupOverrideValues
            ? GT.backendSettings.groupOverrideValues(node && node.id)
            : null;
        var mode = values && values.rebalance_trigger;
        var map = { 'on_factor_signal': '因子信号事件', 'membership_change': '成员变化事件', 'scheduled': '日历计划事件' };
        return map[mode] || (mode || '—');
    }

    function derivedCloseTodayLabel(node) {
        return '—';
    }

    function rebalanceLabel(mode) {
        var map = { 'each_period': '每期', 'weekly': '每周', 'monthly': '每月', 'none': '无' };
        return map[mode] || (mode || '—');
    }

    function closeTodayLabel(feeMode, useCloseToday) {
        if (feeMode === 'none' || feeMode === 'fixed') return '—';
        return useCloseToday ? '平今' : '平昨';
    }

    function deriveShortAlias(node) {
        if (!node) return '?';
        if (!node.parentId) return node.shortAlias || node.name || node.id || '?';
        // Find this node's index among siblings (same parentId)
        var allNodes = GT.groupSettings.groups && GT.groupSettings.groups.getAll();
        if (!allNodes) return node.name || '?';
        var siblings = [];
        for (var i = 0; i < allNodes.length; i++) {
            if (allNodes[i].parentId === node.parentId) {
                siblings.push(allNodes[i]);
            }
        }
        var idx = -1;
        for (var j = 0; j < siblings.length; j++) {
            if (siblings[j].id === node.id) { idx = j; break; }
        }
        var num = idx >= 0 ? (idx + 1) : '?';
        // Build alias from parent chain
        var parentNode = GT.groupSettings.groups.get(node.parentId);
        var parentAlias = parentNode ? deriveShortAlias(parentNode) : (node.parentId || '?');
        return parentAlias + ':' + num;
    }

    /** Get addGroupBatchKey from addGroupBatch registry */
    function addGroupBatchKey(selectionOrId, factorAlias, splitCount) {
        return GT.groupSettings.addGroupBatch.key(
            typeof selectionOrId === 'object' ? selectionId(selectionOrId) : selectionOrId,
            factorAlias,
            splitCount
        );
    }

    /** Group base items into addGroupBatches (UI list display groups) */
    var _addGroupBatchMap = {};
    function buildAddGroupBatches(items) {
        _addGroupBatchMap = {};
        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            if (item.parentId) continue;
            var key = addGroupBatchKey(item.product_path_selection, item.factorAlias, item.splitCount);
            if (!_addGroupBatchMap[key]) {
                _addGroupBatchMap[key] = {
                    key: key,
                    product_path_selection: item.product_path_selection,
                    product_path_selection_id: selectionId(item.product_path_selection),
                    factorAlias: item.factorAlias,
                    splitCount: item.splitCount,
                    items: []
                };
            }
            _addGroupBatchMap[key].items.push(item);
        }
        var keys = Object.keys(_addGroupBatchMap);
        keys.sort(function(a, b) {
            var aliasA = _addGroupBatchMap[a].items[0].shortAlias || '';
            var aliasB = _addGroupBatchMap[b].items[0].shortAlias || '';
            if (aliasA < aliasB) return -1;
            if (aliasA > aliasB) return 1;
            return 0;
        });
        var result = [];
        for (var k = 0; k < keys.length; k++) { result.push(_addGroupBatchMap[keys[k]]); }
        return result;
    }

    function getAddGroupBatchMap() { return _addGroupBatchMap; }

    function addGroupBatchGroupIds(addGroupBatchKeyVal) {
        var items = GT.groupSettings.groups.getAll();
        var ids = [];
        for (var i = 0; i < items.length; i++) {
            if (items[i].parentId) continue;
            if (addGroupBatchKey(items[i].product_path_selection, items[i].factorAlias, items[i].splitCount) === addGroupBatchKeyVal) {
                ids.push(items[i].id);
            }
        }
        return ids;
    }

    function addGroupBatchCommon(batch, field) {
        if (batch.items.length === 0) return null;
        var val = batch.items[0][field];
        for (var i = 1; i < batch.items.length; i++) { if (batch.items[i][field] !== val) return null; }
        return val;
    }

    /**
     * Get backend-registered config/derived chips for a child node, diffed against parent.
     * Only shows chips where the resolved value differs from the root.
     */
    function deriveOverrideChips(node) {
        if (!node || !node.parentId) return [];
        return GT.backendSettings && typeof GT.backendSettings.getOverrideChips === 'function'
            ? GT.backendSettings.getOverrideChips(node)
            : [];
    }

    /** Render all chips for a group */
    function renderAllChipsForGroup(g) {
        if (!g) return '';
        var allChips = GT.backendSettings && typeof GT.backendSettings.getAllChips === 'function'
            ? GT.backendSettings.getAllChips(g)
            : [];
        var html = '<span style="display:inline-flex;flex-wrap:wrap;align-items:center;gap:4px;">';
        for (var i = 0; i < allChips.length; i++) {
            var chip = allChips[i];
            var s = chip.style || CHIP_STYLE_PLAIN;
            if (chip.clickable) {
                html += '<span class="gt-backend-chip unified-backend-chip" data-chip-action="' + escapeHTML(chip.action || '') + '" data-gid="' + escapeHTML(g.id) + '" data-chip-label="' + escapeHTML(chip.label) + '" style="' + s + '">' + chip.html + '</span>';
            } else {
                html += '<span class="gt-backend-chip" style="' + s + '">' + chip.html + '</span>';
            }
        }
        html += '</span>';
        return html;
    }

    function lsProductPathSelectionLabel(dgId) {
        if (!dgId) return '—';
        var dg = GT.groupSettings.groups && GT.groupSettings.groups.get(dgId);
        if (!dg) return '—';
        // Walk parentId to root
        var root = dg;
        while (root && root.parentId) {
            root = GT.groupSettings.groups.get(root.parentId);
            if (!root) break;
        }
        var selection = root && nodeProductPathSelection(root);
        return selection ? productPathSelectionLabel(selection) : '—';
    }

    // -- 挂载 --
    GT.panels.list._helpers = {
        $: $,
        escapeHTML: escapeHTML,
        CHIP_STYLE: CHIP_STYLE,
        CHIP_STYLE_PLAIN: CHIP_STYLE_PLAIN,
        renderChipHtml: renderChipHtml,
        selectionId: selectionId,
        productPathSelectionProducts: productPathSelectionProducts,
        productPathSelectionLabel: productPathSelectionLabel,
        dgName: dgName,
        getGroup: getGroup,
        nodeProductPathSelectionId: nodeProductPathSelectionId,
        nodeProductPathSelection: nodeProductPathSelection,
        nodeProducts: nodeProducts,
        synthGroupForChildNode: synthGroupResolved,
        synthGroupForDerivedNode: synthGroupResolved,
        derivedFeeDisplay: derivedFeeDisplay,
        derivedRebalanceLabel: derivedRebalanceLabel,
        derivedCloseTodayLabel: derivedCloseTodayLabel,
        rebalanceLabel: rebalanceLabel,
        closeTodayLabel: closeTodayLabel,
        deriveShortAlias: deriveShortAlias,
        addGroupBatchKey: addGroupBatchKey,
        buildAddGroupBatches: buildAddGroupBatches,
        getAddGroupBatchMap: getAddGroupBatchMap,
        addGroupBatchGroupIds: addGroupBatchGroupIds,
        addGroupBatchCommon: addGroupBatchCommon,
        deriveOverrideChips: deriveOverrideChips,
        renderAllChipsForGroup: renderAllChipsForGroup,
        lsProductPathSelectionLabel: lsProductPathSelectionLabel,
        invalidateExpandCaches: invalidateExpandCaches,
    };
})();
