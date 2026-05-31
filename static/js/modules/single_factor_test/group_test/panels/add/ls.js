/**
 * panels/add/ls.js — Add-flow panel: "创建 Long-Short 组" (category-2)
 *
 * Simplified display: two cards (long | short) with swap button.
 * Preselected groups from GT.ui.getAddDraft().preselectedBaseGroupIds.
 * Tabs-row submit button delegates to panel.handleSave().
 *
 * Contract:
 *   GT.datamodel.ls_configs — CRUD (add)
 *   GT.datamodel.groups     — for reading group config
 *   GT.ui                   — getAddDraft(), exitAddMode()
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }

    var CONTAINER_ID = 'add-ls';

    var _mounted = false;
    var _longId = null;
    var _shortId = null;

    function $(id) { return document.getElementById(id); }

    function escapeHTML(str) { return GT.escapeHTML(str); }

    // ── Colors ──
    var COL_LONG  = { border: '3b82f6', bg: 'f0f7ff', text: '1e40af', chipBg: 'dbeafe', chipText: '1e3a8a' };
    var COL_SHORT = { border: '8b5cf6', bg: 'f5f3ff', text: '5b21b6', chipBg: 'ede9fe', chipText: '4c1d95' };

    // ── Short alias for display (dynamic for derived, like list panel) ──
    function _displayAlias(g) {
        if (!g) return '—';
        if (!g.isDerived) return g.shortAlias || g.name || '—';
        return _deriveShortAlias(g);
    }

    /** Same logic as list panel's _deriveShortAlias */
    function _deriveShortAlias(node) {
        if (!node || !node.baseGroupId) return node ? (node.shortAlias || node.name || '?') : '?';
        var bg = _getGroup(node.baseGroupId);
        var bgAlias = bg ? (bg.shortAlias || bg.name || bg.id) : node.baseGroupId;
        var allNodes = (GT.datamodel.groups && GT.datamodel.groups.getAll) ? GT.datamodel.groups.getAll() : [];
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
        if (node.parentId) {
            var parentNode = _getGroup(node.parentId);
            if (parentNode && parentNode.baseGroupId === node.baseGroupId) {
                var parentAlias = _deriveShortAlias(parentNode);
                return parentAlias + ':' + num;
            }
        }
        return bgAlias + ':' + num;
    }

    // =========================================================================
    // Render
    // =========================================================================

    function render() {
        var container = $(CONTAINER_ID);
        if (!container) return;

        var draft = (GT.ui && typeof GT.ui.getAddDraft === 'function') ? GT.ui.getAddDraft() : null;
        var preselected = (draft && draft.preselectedBaseGroupIds) ? draft.preselectedBaseGroupIds : [];

        _longId  = preselected[0] || null;
        _shortId = preselected[1] || null;

        var gLong  = _longId  ? _getGroup(_longId)  : null;
        var gShort = _shortId ? _getGroup(_shortId) : null;

        var saLong  = _displayAlias(gLong);
        var saShort = _displayAlias(gShort);

        var html = '';

        // ── Title ──
        html += '<div style="font-size:14px;font-weight:600;color:#111827;margin-bottom:16px;">';
        html += escapeHTML(saLong) + ' / ' + escapeHTML(saShort);
        html += '</div>';

        // ── Two-column cards ──
        html += '<div style="display:flex;align-items:stretch;gap:0;">';

        // LEFT: Long
        html += _cardHTML(gLong, '📈 多头', COL_LONG);

        // CENTER: Swap
        html += '<div style="display:flex;align-items:center;padding:0 12px;">';
        html += '<button id="lsed-swap" title="交换多头/空头" style="width:36px;height:36px;border:1px solid #d0d5dd;border-radius:50%;background:#374151;color:#fff;cursor:pointer;font-size:16px;line-height:1;">↹</button>';
        html += '</div>';

        // RIGHT: Short
        html += _cardHTML(gShort, '📉 空头', COL_SHORT);

        html += '</div>'; // end two-column

        container.innerHTML = html;

        _bindEvents();
    }

    /**
     * Build a group card with name + config chips.
     */
    function _cardHTML(g, header, col) {
        var name = _displayAlias(g);

        var html = '';
        html += '<div style="flex:1;min-width:200px;padding:14px;border:2px solid #' + col.border + ';border-radius:10px;background:#' + col.bg + ';">';
        html += '<div style="font-size:14px;font-weight:700;color:#' + col.text + ';margin-bottom:6px;text-align:center;">' + header + '</div>';
        html += '<div style="font-size:18px;font-weight:700;color:#111827;text-align:center;margin-bottom:10px;">' + name;
        if (g && g.isDerived) html += ' <span style="font-size:11px;font-weight:400;color:#6b7280;">[派生]</span>';
        html += '</div>';

        // ── Config chips ──
        html += '<div style="display:flex;flex-wrap:wrap;gap:6px;justify-content:center;">';
        html += _chipsHTML(g);
        html += '</div>';

        html += '</div>';
        return html;
    }

    // ── Chip styles (match list panel) ──
    var CHIP_PLAIN    = 'display:inline-block;background:#e5e7eb;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;color:#374151;';
    var CHIP_CLICKABLE = 'display:inline-block;cursor:pointer;background:#c7d2fe;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;color:#312e81;';

    /**
     * Build config chip tags for a group.
     * For derived groups: inherit fee fields from base so REG.getChips can show them.
     * Uses REG.getChips (same as list panel) + tester/factor/group info.
     */
    function _chipsHTML(g) {
        var chips = [];
        var REG = window.GT_CONFIG_REGISTRY;

        // 1) factorAlias
        if (g.factorAlias) {
            chips.push('<span style="' + CHIP_PLAIN + '">' + escapeHTML(g.factorAlias) + '</span>');
        }

        // 2) testerId — resolve label through list panel's _testerLabel
        var testerLabel = _testerLabelForGroup(g);
        if (testerLabel) {
            chips.push('<span style="' + CHIP_CLICKABLE + '">' + escapeHTML(testerLabel) + '</span>');
        }

        // 3) groupIndex / groupCount
        if (!g.isDerived && g.groupCount) {
            var gi = g.groupIndex || 1;
            chips.push('<span style="' + CHIP_PLAIN + '">' + gi + '/' + g.groupCount + '</span>');
        }

        // 4) Config chips from REG (fee, rebalance, etc.)
        //    For derived groups: inherit all config from base group (derived defaults are 'none' etc.)
        //    For base groups: pass through directly
        var synthGroup;
        if (g && g.isDerived) {
            // Derived group — always use base group's config (derived doesn't have independent fee/rebalance)
            var bg = g.baseGroupId ? _getGroup(g.baseGroupId) : null;
            synthGroup = bg || {
                feeMode: 'none',
                feeRate: null,
                feeMap: null,
                feeSensitivity: null,
                useCloseToday: false,
                rebalanceMode: 'buy_and_hold',
            };
        } else {
            synthGroup = g;
        }

        if (REG && typeof REG.getChips === 'function') {
            var regChips = REG.getChips(synthGroup);
            for (var i = 0; i < regChips.length; i++) {
                var chip = regChips[i];
                var s = chip.style || CHIP_PLAIN;
                chips.push('<span style="' + s + '">' + chip.html + '</span>');
            }
        }

        return chips.join('');
    }

    /**
     * Resolve tester label for a group.
     * For derived groups, get tester from base group.
     */
    function _testerLabelForGroup(g) {
        if (!g) return '';
        var testerId = g.testerId;
        // For derived groups, get tester from base
        if (!testerId && g.isDerived && g.baseGroupId) {
            var bg = _getGroup(g.baseGroupId);
            if (bg) testerId = bg.testerId;
        }
        if (!testerId) return '';
        // Use the same resolution as list panel
        return _resolveTesterLabel(testerId);
    }

    /** Resolve tester label from window.submissions (same as list panel's _testerLabel) */
    function _resolveTesterLabel(testerId) {
        if (!testerId) return '';
        var subs = window.submissions || [];
        for (var i = 0; i < subs.length; i++) {
            if (String(subs[i].id) === String(testerId)) {
                return subs[i].product_group || subs[i].label || ('测试器 #' + subs[i].id);
            }
        }
        return testerId;
    }

    // =========================================================================
    // Events
    // =========================================================================

    function _bindEvents() {
        var swapBtn = $('lsed-swap');
        if (swapBtn) {
            swapBtn.addEventListener('click', function() {
                var tmp = _longId;
                _longId = _shortId;
                _shortId = tmp;
                render();
            });
        }
    }

    // =========================================================================
    // Save (called by tabs-row submit button)
    // =========================================================================

    /**
     * Called by app.js _submitAddLSGroup().
     * @returns {{success: boolean, error: string|null}}
     */
    function handleSave() {
        if (!_longId) return { success: false, error: '请先选择多头组' };

        try {
            var longDgId  = _resolveToDerived(_longId);
            var shortDgId = _shortId ? _resolveToDerived(_shortId) : null;

            var gLong  = _getGroup(_longId);
            var gShort = _shortId ? _getGroup(_shortId) : null;

            // Build name from short aliases (dynamic, like display)
            var saLong  = _displayAlias(gLong) || 'L';
            var saShort = gShort ? (_displayAlias(gShort) || 'S') : '';
            var name = saShort ? (saLong + '/' + saShort) : saLong;

            var data = { name: name, longGroupId: longDgId };
            if (shortDgId) data.shortGroupId = shortDgId;

            GT.datamodel.ls_configs.add(data);
            return { success: true, error: null };
        } catch (err) {
            return { success: false, error: (err && err.message) || String(err) };
        }
    }

    // =========================================================================
    // Helpers
    // =========================================================================

    function _getGroup(id) {
        return (GT.datamodel.groups && GT.datamodel.groups.get) ? GT.datamodel.groups.get(id) : null;
    }

    function _resolveToDerived(groupId) {
        var g = _getGroup(groupId);
        if (!g) throw new Error('分组不存在: ' + groupId);
        if (g.isDerived) return groupId;

        // Base group: find or create derived
        var all = (GT.datamodel.groups && GT.datamodel.groups.getAll) ? GT.datamodel.groups.getAll() : [];
        for (var i = 0; i < all.length; i++) {
            if (all[i].isDerived && all[i].baseGroupId === groupId) return all[i].id;
        }

        // Compute derived shortAlias: baseGroupAlias:1 (each base has one derived in LS context)
        var bgAlias = g.shortAlias || g.name || groupId;
        var dgShortAlias = bgAlias + ':1';
        var dgName = dgShortAlias;

        var dg = GT.datamodel.groups.add({
            name: dgName,
            shortAlias: dgShortAlias,
            baseGroupId: groupId,
            isDerived: true,
        });
        return dg.id;
    }

    // =========================================================================
    // Public API
    // =========================================================================

    function mount()   { _mounted = true;  render(); }
    function unmount() { _mounted = false; }
    function refresh() { if (_mounted) render(); }

    GT.panels.add = GT.panels.add || {};
    GT.panels.add.ls = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
        handleSave: handleSave
    };
})();
