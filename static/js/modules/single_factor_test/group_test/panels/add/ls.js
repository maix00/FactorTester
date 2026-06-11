/**
 * panels/add/ls.js — Add-flow panel: "创建 Long-Short 组" (category-2)
 *
 * Simplified display: two cards (long | short) with swap button.
 * Preselected groups from GT.tabs.getAddDraft().preselectedBaseGroupIds.
 * Tabs-row submit button delegates to panel.handleSave().
 *
 * Contract:
 *   GT.groupSettings.lsConfigs — CRUD (add)
 *   GT.groupSettings.groups     — for reading group config
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

    // ── Short alias for display (dynamic for children, like list panel) ──
    function _displayAlias(g) {
        if (!g) return '—';
        if (!g.parentId) return g.shortAlias || g.name || '—';
        return _deriveShortAlias(g);
    }

    /** Same logic as list panel's _deriveShortAlias */
    function _deriveShortAlias(node) {
        if (!node || !node.parentId) return node ? (node.shortAlias || node.name || '?') : '?';
        // Walk up to root
        var root = node;
        while (root && root.parentId) {
            root = _getGroup(root.parentId);
            if (!root) break;
        }
        var bgAlias = root ? (root.shortAlias || root.name || root.id) : (node.parentId || '?');
        var allNodes = (GT.groupSettings.groups && GT.groupSettings.groups.getAll) ? GT.groupSettings.groups.getAll() : [];
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
        if (node.parentId) {
            var parentNode = _getGroup(node.parentId);
            if (parentNode && parentNode.parentId === node.parentId) {
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

        var draft = (GT.tabs && typeof GT.tabs.getAddDraft === 'function') ? GT.tabs.getAddDraft() : null;
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
        if (g && g.parentId) html += ' <span style="font-size:11px;font-weight:400;color:#6b7280;">[子组]</span>';
        html += '</div>';

        // ── Config chips ──
        html += '<div style="display:flex;flex-wrap:wrap;gap:6px;justify-content:center;">';
        html += _chipsHTML(g);
        html += '</div>';

        html += '</div>';
        return html;
    }

    // ── Chips: unified via GT_CONFIG_REGISTRY.getAllChips ──

    function _chipsHTML(g) {
        if (!g) return '';
        var REG = window.GT_CONFIG_REGISTRY;
        if (!REG || typeof REG.getAllChips !== 'function') return '';

        var allChips = REG.getAllChips(g);
        var html = '';
        for (var i = 0; i < allChips.length; i++) {
            var c = allChips[i];
            html += '<span style="' + (c.style || '') + '">' + c.html + '</span>';
        }
        return html;
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
        if (!_shortId) return { success: false, error: '请先选择空头组' };

        try {
            var gLong  = _getGroup(_longId);
            var gShort = _getGroup(_shortId);

            var saLong  = _displayAlias(gLong) || 'L';
            var saShort = _displayAlias(gShort) || 'S';
            var name = saLong + '/' + saShort;

            GT.groupSettings.lsConfigs.add({
                name: name,
                longGroupId: _longId,
                shortGroupId: _shortId,
            });
            return { success: true, error: null };
        } catch (err) {
            return { success: false, error: (err && err.message) || String(err) };
        }
    }

    // =========================================================================
    // Helpers
    // =========================================================================

    function _getGroup(id) {
        return (GT.groupSettings.groups && GT.groupSettings.groups.get) ? GT.groupSettings.groups.get(id) : null;
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

    // ── Register edit action：「⚡ 创建 LS 组合」（选中 2 组时直接创建，无 tab 面板）(refs #109)
    if (GT.modes) {
        GT.modes.registerEditAction({
            name: 'create-ls',
            label: '⚡ 创建 LS 组合',
            priority: 20,
            condition: function(ctx) {
                return ctx && ctx.count === 2;
            },
            action: function(ctx, helpers) {
                if (!ctx || ctx.ids.length !== 2) { alert('请选择 2 个组来创建 LS 组合'); return; }
                var gLong  = _getGroup(ctx.ids[0]);
                var gShort = _getGroup(ctx.ids[1]);
                var saLong  = _displayAlias(gLong) || 'L';
                var saShort = _displayAlias(gShort) || 'S';
                var name = saLong + '/' + saShort;

                try {
                    GT.groupSettings.lsConfigs.add({
                        name: name,
                        longGroupId: ctx.ids[0],
                        shortGroupId: ctx.ids[1],
                    });
                    helpers.exitEdit();
                } catch (err) {
                    alert('创建失败: ' + ((err && err.message) || String(err)));
                }
            },
            standalone: false
        });
    }
})();
