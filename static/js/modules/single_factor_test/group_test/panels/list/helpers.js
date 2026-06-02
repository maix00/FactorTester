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
        if (!node.baseGroupId || node.baseGroupId === '__batch__') return null;
        var bg = GT.groupSettings.groups && GT.groupSettings.groups.get(node.baseGroupId);
        return bg ? bg.testerId : null;
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
     * Build a shallow display object for a derived node.
     * Config fields are group fields; no global resolver is involved.
     */
    function synthGroupForDerivedNode(node) {
        if (!node || !node.baseGroupId || node.baseGroupId === '__batch__') return null;
        return {
            id: node.id,
            isDerived: true,
            baseGroupId: node.baseGroupId,
            feeMode: node.feeMode || 'none',
            feeRate: node.feeRate !== undefined ? node.feeRate : null,
            feeMap: node.feeMap !== undefined ? node.feeMap : null,
            feeSensitivity: node.feeSensitivity !== undefined ? node.feeSensitivity : 1,
            useCloseToday: !!node.useCloseToday,
            rebalanceMode: node.rebalanceMode || 'each_period',
            liquidityMode: node.liquidityMode || 'infinite',
            liquidityPercent: node.liquidityPercent !== undefined && node.liquidityPercent !== null ? node.liquidityPercent : 100
        };
    }

    function derivedFeeDisplay(node) {
        var mode = node.feeMode || 'none';
        if (mode === 'none' || !mode) return '—';
        if (mode === 'uniform' || mode === 'fixed') return (node.feeRate != null) ? Number(node.feeRate).toFixed(6) : '—';
        if (mode === 'per_product') { var m1 = node.feeMap || {}; return '按品种(' + Object.keys(m1).length + ')'; }
        if (mode === 'custom') { var m2 = node.feeMap || {}; return '自定义(' + Object.keys(m2).length + ')'; }
        return mode;
    }

    function derivedRebalanceLabel(node) {
        var mode = node.rebalanceMode || null;
        var map = { 'each_period': '每期', 'buy_and_hold': '持仓不动', 'recycle': '退出补新' };
        return map[mode] || (mode || '—');
    }

    function derivedCloseTodayLabel(node) {
        var mode = node.feeMode || 'none';
        if (mode === 'none' || mode === 'fixed') return '—';
        return node.useCloseToday ? '平今' : '平昨';
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
        if (!node || !node.baseGroupId) return node ? (node.name || '?') : '?';
        var bg = GT.groupSettings.groups && GT.groupSettings.groups.get(node.baseGroupId);
        var bgAlias = bg ? (bg.shortAlias || bg.label || bg.id) : node.baseGroupId;
        // Find this node's index among siblings (same parentId, same baseGroupId)
        var allNodes = GT.groupSettings.groups && GT.groupSettings.groups.getAll();
        if (!allNodes) return bgAlias + ':?';
        var siblings = [];
        for (var i = 0; i < allNodes.length; i++) {
            if (allNodes[i].baseGroupId === node.baseGroupId && allNodes[i].parentId === node.parentId) {
                siblings.push(allNodes[i]);
            }
        }
        var idx = -1;
        for (var j = 0; j < siblings.length; j++) {
            if (siblings[j].id === node.id) { idx = j; break; }
        }
        var num = idx >= 0 ? (idx + 1) : '?';
        // Build alias from parent chain: use parent's short alias as prefix if derived parent
        if (node.parentId) {
            var parentNode = GT.groupSettings.groups.get(node.parentId);
            if (parentNode && parentNode.baseGroupId === node.baseGroupId) {
                var parentAlias = deriveShortAlias(parentNode);
                return parentAlias + ':' + num;
            }
        }
        return bgAlias + ':' + num;
    }

    /** Get batchKey from group settings */
    function batchKey(testerId, factorAlias, groupCount) {
        return GT.groupSettings.groups.batchKey(testerId, factorAlias, groupCount);
    }

    /** Group base items into batches */
    var _batchMap = {};
    function buildBatches(items) {
        _batchMap = {};
        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            if (item.isDerived) continue;
            var key = batchKey(item.testerId, item.factorAlias, item.groupCount);
            if (!_batchMap[key]) {
                _batchMap[key] = { key: key, testerId: item.testerId, factorAlias: item.factorAlias, groupCount: item.groupCount, items: [] };
            }
            _batchMap[key].items.push(item);
        }
        var keys = Object.keys(_batchMap);
        keys.sort(function(a, b) {
            var aliasA = _batchMap[a].items[0].shortAlias || '';
            var aliasB = _batchMap[b].items[0].shortAlias || '';
            if (aliasA < aliasB) return -1;
            if (aliasA > aliasB) return 1;
            return 0;
        });
        var result = [];
        for (var k = 0; k < keys.length; k++) { result.push(_batchMap[keys[k]]); }
        return result;
    }

    function getBatchMap() { return _batchMap; }

    function batchGroupIds(batchKeyVal) {
        var items = GT.groupSettings.groups.getAll();
        var ids = [];
        for (var i = 0; i < items.length; i++) {
            if (items[i].isDerived) continue;
            if (batchKey(items[i].testerId, items[i].factorAlias, items[i].groupCount) === batchKeyVal) {
                ids.push(items[i].id);
            }
        }
        return ids;
    }

    function batchCommon(batch, field) {
        if (batch.items.length === 0) return null;
        var val = batch.items[0][field];
        for (var i = 1; i < batch.items.length; i++) { if (batch.items[i][field] !== val) return null; }
        return val;
    }

    /**
     * Get config chips for a derived node using REG.getChips, diffed against base group.
     * Only shows chips where the resolved value differs from the base group.
     */
    function deriveOverrideChips(node) {
        if (!node || !node.baseGroupId || node.baseGroupId === '__batch__') return [];
        var bg = GT.groupSettings.groups && GT.groupSettings.groups.get(node.baseGroupId);
        if (!bg) return [];
        if (!REG || typeof REG.getChips !== 'function') return [];

        var derivedSynth = synthGroupForDerivedNode(node);
        if (!derivedSynth) return [];

        var baseSynth = {
            feeMode: bg.feeMode || 'none',
            feeRate: bg.feeRate,
            feeMap: bg.feeMap,
            feeSensitivity: bg.feeSensitivity,
            useCloseToday: !!bg.useCloseToday,
            rebalanceMode: bg.rebalanceMode || 'each_period',
            liquidityMode: bg.liquidityMode || 'infinite',
            liquidityPercent: bg.liquidityPercent !== undefined && bg.liquidityPercent !== null ? bg.liquidityPercent : 100
        };

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
        var html = '';
        for (var i = 0; i < allChips.length; i++) {
            var chip = allChips[i];
            var s = chip.style || CHIP_STYLE_PLAIN;
            if (chip.onClick) {
                var attr = g.isDerived
                    ? ('data-dgid="' + escapeHTML(g.id) + '"')
                    : ('data-gid="' + escapeHTML(g.id) + '"');
                html += '<span class="unified-config-chip" ' + attr
                    + ' data-chip-label="' + escapeHTML(chip.label)
                    + '" style="' + s + ';margin-right:4px;">' + chip.html + '</span>';
            } else {
                html += '<span style="' + s + ';margin-right:4px;">' + chip.html + '</span>';
            }
        }
        return html;
    }

    function lsTesterLabel(dgId) {
        if (!dgId) return '—';
        var dg = GT.groupSettings.groups && GT.groupSettings.groups.get(dgId);
        if (!dg || !dg.baseGroupId) return '—';
        var bg = GT.groupSettings.groups && GT.groupSettings.groups.get(dg.baseGroupId);
        if (!bg || !bg.testerId) return '—';
        return testerLabel(bg.testerId);
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
        synthGroupForDerivedNode: synthGroupForDerivedNode,
        derivedFeeDisplay: derivedFeeDisplay,
        derivedRebalanceLabel: derivedRebalanceLabel,
        derivedCloseTodayLabel: derivedCloseTodayLabel,
        rebalanceLabel: rebalanceLabel,
        closeTodayLabel: closeTodayLabel,
        deriveShortAlias: deriveShortAlias,
        batchKey: batchKey,
        buildBatches: buildBatches,
        getBatchMap: getBatchMap,
        batchGroupIds: batchGroupIds,
        batchCommon: batchCommon,
        deriveOverrideChips: deriveOverrideChips,
        renderAllChipsForGroup: renderAllChipsForGroup,
        lsTesterLabel: lsTesterLabel,
        invalidateExpandCaches: invalidateExpandCaches,
    };
})();
