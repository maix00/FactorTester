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

    var REG = window.GT_CONFIG_REGISTRY;

    // ── Expand caches ──
    var _testerProductsCache = {};
    var _nodeFeeCache = {};

    function invalidateExpandCaches() {
        _testerProductsCache = {};
        _nodeFeeCache = {};
    }

    function $(id) { return document.getElementById(id); }

    function escapeHTML(str) { return GT.escapeHTML(str); }

    // ── Chip badge style ──
    var CHIP_STYLE = 'display:inline-block;cursor:pointer;background:#c7d2fe;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;color:#312e81;';
    var CHIP_STYLE_PLAIN = 'display:inline-block;background:#e5e7eb;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;color:#374151;';

    /** Get products list for a tester from window.submissions (cached) */
    function testerProducts(testerId) {
        if (_testerProductsCache[testerId]) return _testerProductsCache[testerId];
        var subs = window.submissions || [];
        var result = [];
        for (var i = 0; i < subs.length; i++) {
            if (String(subs[i].id) === String(testerId)) {
                var products = subs[i].products;
                if (Array.isArray(products)) {
                    result = products.map(function(p) {
                        if (typeof p === 'string') return { name: p, desc: '' };
                        return { name: p.name || '', desc: p.desc || '' };
                    });
                }
                break;
            }
        }
        _testerProductsCache[testerId] = result;
        return result;
    }

    /** Look up a submission label by testerId */
    function testerLabel(testerId) {
        var subs = window.submissions || [];
        for (var i = 0; i < subs.length; i++) {
            if (String(subs[i].id) === String(testerId)) {
                return subs[i].product_group || subs[i].label || ('测试器 #' + subs[i].id);
            }
        }
        return testerId || '—';
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

    function nodeTesterId(node) {
        if (!node) return null;
        if (node.parentId) {
            return (GT.groupSettings.groups && GT.groupSettings.groups.resolveRootField) 
                ? GT.groupSettings.groups.resolveRootField(node, 'testerId') : null;
        }
        return node.testerId || null;
    }

    function nodeProducts(node) {
        var tid = nodeTesterId(node);
        var allProds = tid ? testerProducts(tid) : [];
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
        var map = { 'on_factor_signal': '因子信号事件', 'buy_and_hold': '买入持有', 'membership_change': '成员变化事件', 'scheduled': '日历计划事件' };
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
    function addGroupBatchKey(testerId, factorAlias, splitCount) {
        return GT.groupSettings.addGroupBatch.key(testerId, factorAlias, splitCount);
    }

    /** Group base items into addGroupBatches (UI list display groups) */
    var _addGroupBatchMap = {};
    function buildAddGroupBatches(items) {
        _addGroupBatchMap = {};
        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            if (item.parentId) continue;
            var key = addGroupBatchKey(item.testerId, item.factorAlias, item.splitCount);
            if (!_addGroupBatchMap[key]) {
                _addGroupBatchMap[key] = { key: key, testerId: item.testerId, factorAlias: item.factorAlias, splitCount: item.splitCount, items: [] };
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
            if (addGroupBatchKey(items[i].testerId, items[i].factorAlias, items[i].splitCount) === addGroupBatchKeyVal) {
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
     * Get config chips for a child node using REG.getChips, diffed against root.
     * Only shows chips where the resolved value differs from the root.
     */
    function deriveOverrideChips(node) {
        if (!node || !node.parentId) return [];
        // Walk parentId chain to root
        var cur = node;
        var visited = {};
        while (cur && cur.parentId) {
            if (visited[cur.id]) { cur = null; break; }
            visited[cur.id] = true;
            cur = GT.groupSettings.groups && GT.groupSettings.groups.get(cur.parentId);
        }
        var bg = cur;
        if (!bg) return [];
        if (!REG || typeof REG.getChips !== 'function') return [];

        var derivedSynth = synthGroupResolved(node);
        if (!derivedSynth) return [];

        var baseSynth = synthGroupResolved(bg);

        var baseChips = REG.getChips(baseSynth);
        var derivedChips = REG.getChips(derivedSynth);

        var baseLabels = {};
        for (var b = 0; b < baseChips.length; b++) {
            baseLabels[baseChips[b].label] = baseChips[b].html;
        }

        var diff = [];
        for (var d = 0; d < derivedChips.length; d++) {
            var dc = derivedChips[d];
            if (baseLabels[dc.label] !== dc.html) {
                diff.push(dc);
            }
        }

        return diff;
    }

    /** Render all chips for a group */
    function renderAllChipsForGroup(g) {
        if (!g) return '';
        if (!REG || typeof REG.getAllChips !== 'function') return '';
        var allChips = REG.getAllChips(g);
        var html = '<span style="display:inline-flex;flex-wrap:wrap;align-items:center;gap:4px;">';
        for (var i = 0; i < allChips.length; i++) {
            var chip = allChips[i];
            var s = (chip.style || CHIP_STYLE_PLAIN) + ';white-space:nowrap;';
            if (chip.onClick) {
                var attr = g.parentId
                    ? ('data-dgid="' + escapeHTML(g.id) + '"')
                    : ('data-gid="' + escapeHTML(g.id) + '"');
                html += '<span class="unified-config-chip" ' + attr
                    + ' data-chip-label="' + escapeHTML(chip.label)
                    + '" style="' + s + '">' + chip.html + '</span>';
            } else {
                html += '<span style="' + s + '">' + chip.html + '</span>';
            }
        }
        html += '</span>';
        return html;
    }

    function lsTesterLabel(dgId) {
        if (!dgId) return '—';
        var dg = GT.groupSettings.groups && GT.groupSettings.groups.get(dgId);
        if (!dg) return '—';
        // Walk parentId to root
        var root = dg;
        while (root && root.parentId) {
            root = GT.groupSettings.groups.get(root.parentId);
            if (!root) break;
        }
        if (!root || !root.testerId) return '—';
        return testerLabel(root.testerId);
    }

    // -- 挂载 --
    GT.panels.list._helpers = {
        $: $,
        escapeHTML: escapeHTML,
        CHIP_STYLE: CHIP_STYLE,
        CHIP_STYLE_PLAIN: CHIP_STYLE_PLAIN,
        testerProducts: testerProducts,
        testerLabel: testerLabel,
        dgName: dgName,
        getGroup: getGroup,
        nodeTesterId: nodeTesterId,
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
        lsTesterLabel: lsTesterLabel,
        invalidateExpandCaches: invalidateExpandCaches,
    };
})();
