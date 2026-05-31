/**
 * panels/list/index.js — Unified group list panel (category-1)
 *
 * Merges base groups, derived groups, and LS configs into a single panel
 * with two sections:
 *   Section 1 (top):    ⚡ LS 多空组 — flat table
 *   Section 2 (bottom): 🏗️ 基础组 + 派生组 — mixed list (batch rows + tree nodes)
 *
 * Selection / edit mode:
 *   - Click 1 base-group row → edit mode: show "创建派生组" + "创建 Long-Short" in tab actions
 *   - Click 2 base-group rows → edit mode: show "创建 Long-Short 组" in tab actions
 *   - Click derived node → edit mode: show config tabs (fee/rebalance/close_today)
 *
 * Data shape:
 *   GT.datamodel.base_groups     — base groups CRUD
 *   GT.datamodel.derived_graph   — derived tree CRUD + getTree()
 *   GT.datamodel.ls_configs      — LS configs CRUD
 *   GT.datamodel.fee_strategy    — resolveFee / resolveRebalance / resolveCloseToday
 *   GT.state                     — events + active IDs
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }

    // =========================================================================
    // Common helpers
    // =========================================================================

    var _containerId = 'unified-group-list';

    var _mounted = false;

    /** Multi-select: set of selected base-group IDs */
    var _selectedIds = {};

    /** Batch expand/collapse */
    var _expandedBatches = {};

    /** Batch lookup by key (populated on render) */
    var _batchMap = {};

    /** Derived tree collapse state */
    var _collapsedIds = {};

    /** Active derived node id (for highlight) */
    var _activeDerivedId = null;

    /** Active LS config id (for highlight) */
    var _activeLSId = null;

    // ── Expand caches ──
    var _testerProductsCache = {};
    var _nodeFeeCache = {};

    function _invalidateExpandCaches() {
        _testerProductsCache = {};
        _nodeFeeCache = {};
    }

    function $(id) { return document.getElementById(id); }

    function escapeHTML(str) {
        if (str === null || str === undefined) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    // ── Chip badge style (shared by tester, factor, fee chips) ──
    var CHIP_STYLE = 'display:inline-block;cursor:pointer;background:#c7d2fe;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;color:#312e81;';
    var CHIP_STYLE_PLAIN = 'display:inline-block;background:#e5e7eb;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;color:#374151;';

    /** Get products list for a tester from window.submissions (cached) */
    function _testerProducts(testerId) {
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
    function _testerLabel(testerId) {
        var subs = window.submissions || [];
        for (var i = 0; i < subs.length; i++) {
            if (String(subs[i].id) === String(testerId)) {
                return subs[i].product_group || subs[i].label || ('测试器 #' + subs[i].id);
            }
        }
        return testerId || '—';
    }

    // =========================================================================
    // LS (Long-Short) section helpers
    // =========================================================================

    function _dgName(id) {
        if (!id) return '—';
        if (GT.datamodel.derived_graph && GT.datamodel.derived_graph.get) {
            var dg = GT.datamodel.derived_graph.get(id);
            if (dg) return dg.name || id;
        }
        return id;
    }

    function _lsTesterLabel(dgId) {
        if (!dgId) return '—';
        var dg = GT.datamodel.derived_graph && GT.datamodel.derived_graph.get(dgId);
        if (!dg || !dg.baseGroupId) return '—';
        var bg = GT.datamodel.base_groups && GT.datamodel.base_groups.get(dg.baseGroupId);
        if (!bg || !bg.testerId) return '—';
        return _testerLabel(bg.testerId);
    }

    // =========================================================================
    // Section 1: LS (Long-Short) 多空组 — flat table
    // =========================================================================

    /** LS modal form (add/edit) */
    var _lsModalId = 'unified-ls-form-modal';
    var _lsFormId = 'unified-ls-form';

    function _lsShowModal(editData) {
        var existing = $(_lsModalId);
        if (existing) existing.remove();

        var isEdit = !!editData;
        var title = isEdit ? '编辑多空配置' : '新增多空配置';

        var dgOptions = [];
        if (GT.datamodel.derived_graph && GT.datamodel.derived_graph.list) {
            dgOptions = GT.datamodel.derived_graph.list();
        }

        var html = '<div id="' + _lsModalId + '" style="position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);display:flex;align-items:center;justify-content:center;z-index:10000;">';
        html += '<div style="background:#fff;border-radius:8px;padding:24px;min-width:460px;max-width:560px;box-shadow:0 8px 32px rgba(0,0,0,0.2);">';
        html += '<h3 style="margin:0 0 16px 0;">' + title + '</h3>';
        html += '<form id="' + _lsFormId + '" onsubmit="return false;">';

        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">名称 <span style="color:red;">*</span></span>';
        html += '<input type="text" id="lsf_name" value="' + escapeHTML(isEdit ? editData.name : '') + '" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;" required>';
        html += '</label>';

        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">多头组 <span style="color:red;">*</span></span>';
        html += '<select id="lsf_longGroupId" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;" required>';
        html += '<option value="">— 选择派生组 —</option>';
        var longSel = isEdit ? editData.longGroupId : '';
        for (var i = 0; i < dgOptions.length; i++) {
            var sel = dgOptions[i].id === longSel ? ' selected' : '';
            html += '<option value="' + escapeHTML(dgOptions[i].id) + '"' + sel + '>' + escapeHTML(dgOptions[i].name || dgOptions[i].id) + '</option>';
        }
        html += '</select></label>';

        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">空头组 <span style="color:red;">*</span></span>';
        html += '<select id="lsf_shortGroupId" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;" required>';
        html += '<option value="">— 选择派生组 —</option>';
        var shortSel = isEdit ? editData.shortGroupId : '';
        for (var j = 0; j < dgOptions.length; j++) {
            var sel2 = dgOptions[j].id === shortSel ? ' selected' : '';
            html += '<option value="' + escapeHTML(dgOptions[j].id) + '"' + sel2 + '>' + escapeHTML(dgOptions[j].name || dgOptions[j].id) + '</option>';
        }
        html += '</select></label>';

        html += '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;">';
        html += '<button type="button" id="lsf-cancel" style="padding:6px 16px;border:1px solid #ddd;border-radius:4px;background:#f6f8fa;cursor:pointer;">取消</button>';
        html += '<button type="submit" id="lsf-save" style="padding:6px 16px;border:none;border-radius:4px;background:#0078d4;color:#fff;cursor:pointer;">' + (isEdit ? '保存' : '新增') + '</button>';
        html += '</div>';
        html += '</form></div></div>';

        document.body.insertAdjacentHTML('beforeend', html);
        $(_lsModalId)._editId = isEdit ? editData.id : null;

        $('lsf-cancel').addEventListener('click', _lsCloseModal);
        $(_lsFormId).addEventListener('submit', _lsHandleFormSubmit);
        $(_lsModalId).addEventListener('click', function(e) { if (e.target === this) _lsCloseModal(); });
    }

    function _lsCloseModal() {
        var m = $(_lsModalId);
        if (m) m.remove();
    }

    function _lsHandleFormSubmit(e) {
        e.preventDefault();
        var editId = $(_lsModalId)._editId;
        var data = {
            name: $('lsf_name').value.trim(),
            longGroupId: $('lsf_longGroupId').value,
            shortGroupId: $('lsf_shortGroupId').value,
        };
        try {
            if (editId) { GT.datamodel.ls_configs.update(editId, data); }
            else { GT.datamodel.ls_configs.add(data); }
            _lsCloseModal();
        } catch (err) { alert('操作失败: ' + err.message); }
    }

    /** Render LS section */
    function _renderLSSection() {
        var items = GT.datamodel.ls_configs.getAll();
        // Hide entire section when there are no LS configs
        if (items.length === 0) return '';
        var h = '';

        // Section header
        h += '<div class="unified-section-header" style="display:flex;align-items:center;justify-content:space-between;padding:8px 4px;margin-bottom:8px;border-bottom:2px solid #e0e7ff;">';
        h += '<span style="font-size:14px;font-weight:700;color:#3730a3;">⚡ LS 多空组</span>';
        h += '</div>';

        h += '<table style="width:100%;border-collapse:collapse;font-size:13px;">';
        h += '<thead><tr style="background:#f6f8fa;border-bottom:1px solid #d0d5dd;">';
        h += '<th style="padding:6px 8px;text-align:left;">名称</th>';
        h += '<th style="padding:6px 8px;text-align:left;">多头</th>';
        h += '<th style="padding:6px 8px;text-align:left;">空头</th>';
        h += '<th style="padding:6px 8px;text-align:left;">测试器</th>';
        h += '<th style="padding:6px 8px;text-align:center;">状态</th>';
        h += '<th style="padding:6px 8px;text-align:center;width:90px;">操作</th>';
        h += '</tr></thead><tbody>';

        for (var i = 0; i < items.length; i++) {
            var item = items[i];
                var isActive = item.id === (GT.state && GT.state.getActiveLsConfigId && GT.state.getActiveLsConfigId());
                var rowStyle = isActive ? 'background:#eef2ff;' : '';
                var testerText = _lsTesterLabel(item.longGroupId);
                var staleTag = item.needsRegenerate
                    ? '<span style="' + CHIP_STYLE + 'background:#fef3c7;color:#d97706;">待更新</span>'
                    : '<span style="' + CHIP_STYLE + 'background:#d1fae5;color:#059669;">就绪</span>';

                h += '<tr class="unified-ls-row" data-ls-id="' + escapeHTML(item.id) + '" style="cursor:pointer;border-bottom:1px solid #e8eaed;' + rowStyle + '">';
                h += '<td style="padding:6px 8px;"><span style="' + CHIP_STYLE_PLAIN + '">' + escapeHTML(item.name) + '</span></td>';
                h += '<td style="padding:6px 8px;font-size:12px;">' + escapeHTML(_dgName(item.longGroupId)) + '</td>';
                h += '<td style="padding:6px 8px;font-size:12px;">' + escapeHTML(_dgName(item.shortGroupId)) + '</td>';
                h += '<td style="padding:6px 8px;font-size:12px;color:#555;">' + escapeHTML(testerText) + '</td>';
                h += '<td style="padding:6px 8px;text-align:center;">' + staleTag + '</td>';
                h += '<td style="padding:6px 8px;text-align:center;white-space:nowrap;">';
                h += '<button class="unified-ls-edit-btn" data-ls-id="' + escapeHTML(item.id) + '" style="padding:2px 6px;font-size:11px;border:1px solid #d0d5dd;border-radius:3px;background:#fff;cursor:pointer;">✏️</button> ';
                h += '<button class="unified-ls-del-btn" data-ls-id="' + escapeHTML(item.id) + '" style="padding:2px 6px;font-size:11px;border:1px solid #d0d5dd;border-radius:3px;background:#fff;cursor:pointer;">🗑️</button>';
                h += '</td></tr>';
        }
        h += '</tbody></table>';
        return h;
    }

    // =========================================================================
    // Section 2: 基础组 + 派生组 — mixed list
    // =========================================================================

    /** Get batchKey from datamodel */
    function _batchKey(testerId, factorAlias, groupCount) {
        return GT.datamodel.base_groups.batchKey(testerId, factorAlias, groupCount);
    }

    /** Group base items into batches */
    function _buildBatches(items) {
        _batchMap = {};
        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            var key = _batchKey(item.testerId, item.factorAlias, item.groupCount);
            if (!_batchMap[key]) {
                _batchMap[key] = { key: key, testerId: item.testerId, factorAlias: item.factorAlias, groupCount: item.groupCount, items: [] };
            }
            _batchMap[key].items.push(item);
        }
        var keys = Object.keys(_batchMap).sort();
        var result = [];
        for (var k = 0; k < keys.length; k++) { result.push(_batchMap[keys[k]]); }
        return result;
    }

    function _batchGroupIds(batchKey) {
        var items = GT.datamodel.base_groups.getAll();
        var ids = [];
        for (var i = 0; i < items.length; i++) {
            if (_batchKey(items[i].testerId, items[i].factorAlias, items[i].groupCount) === batchKey) {
                ids.push(items[i].id);
            }
        }
        return ids;
    }

    /**
     * Toggle all items in a batch: if all selected → deselect all; otherwise → select all.
     * Syncs edit mode and emits baseGroupsChanged.
     */
    function _toggleBatchSelection(batch) {
        if (!batch || !batch.items || batch.items.length === 0) return;
        var allSelected = true;
        for (var i = 0; i < batch.items.length; i++) {
            if (!_selectedIds[batch.items[i].id]) { allSelected = false; break; }
        }
        var newSelect = !allSelected;
        for (var i = 0; i < batch.items.length; i++) {
            if (newSelect) { _selectedIds[batch.items[i].id] = true; }
            else { delete _selectedIds[batch.items[i].id]; }
        }
        _syncEditMode();
        GT.state.emit('baseGroupsChanged');
    }

    /** Enter or exit edit mode based on current _selectedIds count. */
    function _syncEditMode() {
        var selCount = Object.keys(_selectedIds).length;
        if (selCount > 0) {
            if (GT.ui && GT.ui.enterEditMode) GT.ui.enterEditMode(_selectedIds);
        } else {
            if (GT.ui && GT.ui.exitEditMode) GT.ui.exitEditMode();
        }
    }

    /** Short fee display */
    function _feeCellDisplay(group) {
        if (!group) return '—';
        var mode = group.feeMode;
        if (mode === 'none' || !mode) return '—';
        if (mode === 'uniform' || mode === 'fixed') return (group.feeRate != null) ? Number(group.feeRate).toFixed(6) : '—';
        if (mode === 'per_product') { var m1 = group.feeMap || {}; return '按品种(' + Object.keys(m1).length + ')'; }
        if (mode === 'custom') { var m2 = group.feeMap || {}; return '自定义(' + Object.keys(m2).length + ')'; }
        return mode;
    }

    // ── Derived node helpers ──

    function _nodeTesterId(node) {
        if (!node.baseGroupId || node.baseGroupId === '__batch__') return null;
        var bg = GT.datamodel.base_groups && GT.datamodel.base_groups.get(node.baseGroupId);
        return bg ? bg.testerId : null;
    }

    function _nodeProducts(node) {
        var testerId = _nodeTesterId(node);
        var allProds = testerId ? _testerProducts(testerId) : [];
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

    function _derivedFeeDisplay(node) {
        var resolved;
        try { resolved = GT.datamodel.fee_strategy.resolveFee(node.id); } catch (e) { return '—'; }
        var mode = resolved.mode;
        if (mode === 'none' || !mode) return '—';
        if (mode === 'uniform' || mode === 'fixed') return (resolved.rate != null) ? Number(resolved.rate).toFixed(6) : '—';
        if (mode === 'per_product') { var m1 = resolved.feeMap || {}; return '按品种(' + Object.keys(m1).length + ')'; }
        if (mode === 'custom') { var m2 = resolved.feeMap || {}; return '自定义(' + Object.keys(m2).length + ')'; }
        return mode;
    }

    function _derivedRebalanceLabel(node) {
        var mode;
        try { mode = GT.datamodel.fee_strategy.resolveRebalance(node.id); } catch (e) { mode = null; }
        var map = { 'each_period': '每期', 'buy_and_hold': '持仓不动', 'recycle': '退出补新' };
        return map[mode] || (mode || '—');
    }

    function _derivedCloseTodayLabel(node) {
        var resolved;
        try { resolved = GT.datamodel.fee_strategy.resolveFee(node.id); } catch (e) { return '—'; }
        if (resolved.mode === 'none' || resolved.mode === 'fixed') return '—';
        var useCT;
        try { useCT = GT.datamodel.fee_strategy.resolveCloseToday(node.id); } catch (e) { useCT = false; }
        return useCT ? '平今' : '平昨';
    }

    function _derivedTesterLabel(node) {
        if (!node.baseGroupId) return '—';
        if (node.baseGroupId === '__batch__') return '批次分组';
        var bg = GT.datamodel.base_groups && GT.datamodel.base_groups.get(node.baseGroupId);
        if (!bg || !bg.testerId) return '—';
        return _testerLabel(bg.testerId);
    }

    function _countRegistrations(nodeId) {
        if (!GT.state._registrations) return 0;
        var regs = GT.state._registrations;
        var count = 0;
        Object.keys(regs).forEach(function(key) {
            var entries = regs[key];
            if (entries && Array.isArray(entries)) {
                for (var i = 0; i < entries.length; i++) {
                    if (entries[i].derivedGroupId === nodeId) count++;
                }
            }
        });
        return count;
    }

    function _nodeBadge(node) {
        var parts = [];
        parts.push(node.isAutoGenerated ? '🤖 自动' : '✏️ 手动');
        var rc = _countRegistrations(node.id);
        if (rc > 0) parts.push('已登记x' + rc);
        return parts.join(' · ');
    }

    function _rebalanceLabel(mode) {
        var map = { 'each_period': '每期', 'weekly': '每周', 'monthly': '每月', 'none': '无' };
        return map[mode] || (mode || '—');
    }

    function _closeTodayLabel(feeMode, useCloseToday) {
        if (feeMode === 'none' || feeMode === 'fixed') return '—';
        return useCloseToday ? '平今' : '平昨';
    }

    /** Check batch common value */
    function _batchCommon(batch, field) {
        if (batch.items.length === 0) return null;
        var val = batch.items[0][field];
        for (var i = 1; i < batch.items.length; i++) { if (batch.items[i][field] !== val) return null; }
        return val;
    }

    // ── Render: base groups section ──

    function _renderBaseSection() {
        var items = GT.datamodel.base_groups.getAll();
        if (items.length === 0) {
            return '<div class="unified-section-header" style="display:flex;align-items:center;justify-content:space-between;padding:8px 4px;margin-bottom:4px;border-bottom:2px solid #e2e8f0;">'
                + '<span style="font-size:14px;font-weight:700;color:#1e293b;">📦 分组组合</span></div>'
                + '<div style="padding:16px;text-align:center;color:#888;font-size:12px;">暂无分组组合</div>';
        }
        var batches = _buildBatches(items);
        var h = '';
        h += '<div class="unified-section-header" style="display:flex;align-items:center;justify-content:space-between;padding:8px 4px;margin-bottom:4px;border-bottom:2px solid #e2e8f0;">';
        h += '<span style="font-size:14px;font-weight:700;color:#1e293b;">📦 分组组合</span>';
        h += '<span style="font-size:11px;color:#666;">' + items.length + ' 个组 / ' + batches.length + ' 批</span>';
        h += '</div>';

        for (var bi = 0; bi < batches.length; bi++) {
            var batch = batches[bi];
            var batchId = batch.key;
            var isExpanded = _expandedBatches[batchId] !== false;
            var isCollapsed = _collapsedIds[batchId];

            // Compute batch letter prefix from items' shortAliases
            var batchLetter = '';
            if (batch.items.length > 0) {
                var extractLetter = GT.datamodel.base_groups && GT.datamodel.base_groups.extractLetter;
                if (extractLetter) {
                    batchLetter = extractLetter(batch.items[0].shortAlias) || '';
                }
            }

            // Batch header
            var testerLabel = _testerLabel(batch.testerId);
            var batchAllSelected = batch.items.every(function(bg) { return _selectedIds[bg.id]; });
            var batchHeaderStyle = 'display:flex;align-items:center;padding:6px 8px;margin-top:4px;border-radius:6px;cursor:pointer;font-size:13px;';
            if (batchAllSelected && batch.items.length > 0) {
                batchHeaderStyle += 'background:#eef2ff;box-shadow:inset 3px 0 0 #6366f1;';
            } else {
                batchHeaderStyle += 'background:#f1f5f9;';
            }
            h += '<div class="unified-batch-header' + (batchAllSelected && batch.items.length > 0 ? ' gt-row-selected' : '') + '" data-batch-key="' + escapeHTML(batchId) + '" data-selected="' + (batchAllSelected ? '1' : '0') + '" style="' + batchHeaderStyle + '">';
            h += '<span class="unified-batch-expand" style="margin-right:6px;width:20px;text-align:center;cursor:pointer;font-size:18px;line-height:1;">' + (isExpanded ? '▾' : '▸') + '</span>';
            h += '<span class="unified-batch-selector" style="display:inline-flex;align-items:center;gap:6px;flex:1;">';
            if (batchLetter) {
                h += '<span style="font-weight:700;color:#4338ca;min-width:24px;">' + escapeHTML(batchLetter) + '</span>';
            }
            h += '<span style="font-weight:600;">' + escapeHTML(batch.factorAlias) + '</span>';
            h += '<span style="color:#555;">' + escapeHTML(testerLabel) + '</span>';
            h += '<span style="color:#888;font-size:11px;">' + batch.groupCount + '组</span>';
            h += '</span>';
            h += '<button class="unified-batch-del-btn" data-batch-key="' + escapeHTML(batchId) + '" style="margin-left:auto;padding:1px 5px;font-size:11px;border:1px solid #fca5a5;border-radius:3px;background:#fef2f2;color:#dc2626;cursor:pointer;flex-shrink:0;">✕</button>';
            h += '</div>';

            if (isExpanded && !isCollapsed) {
                // Batch body gets a highlight border when all items are selected
                var batchBodyStyle = 'margin-left:16px;border-left:2px solid #e2e8f0;padding-left:8px;';
                if (batchAllSelected && batch.items.length > 0) {
                    batchBodyStyle += 'background:rgba(238,242,255,0.5);border-left-color:#a5b4fc;border-radius:0 6px 6px 0;';
                }
                h += '<div class="unified-batch-body" style="' + batchBodyStyle + '">';
                for (var ri = 0; ri < batch.items.length; ri++) {
                    var bg = batch.items[ri];
                    var bgSelected = !!_selectedIds[bg.id];
                    var bgActive = bg.id === (GT.state && GT.state.getActiveBaseGroupId && GT.state.getActiveBaseGroupId());

                    h += '<div class="unified-bg-row" data-bg-id="' + escapeHTML(bg.id) + '" style="display:flex;align-items:center;padding:4px 6px;border-radius:6px;border-bottom:1px solid #f0f0f0;font-size:12px;' + (bgActive ? 'background:#eef2ff;' : '') + (bgSelected ? 'background:#eef2ff;box-shadow:inset 3px 0 0 #6366f1;' : '') + '">';
                    h += '<span style="width:6px;height:6px;border-radius:50%;background:#6366f1;margin-right:8px;flex-shrink:0;"></span>';
                    // Short alias like "A1" — first
                    if (bg.shortAlias) {
                        h += '<span style="font-weight:600;color:#4338ca;min-width:32px;font-size:13px;margin-right:8px;">' + escapeHTML(bg.shortAlias) + '</span>';
                    }
                    // Factor alias (chip)
                    h += '<span style="' + CHIP_STYLE_PLAIN + ';margin-right:8px;">' + escapeHTML(bg.factorAlias) + '</span>';
                    // Tester label (chip)
                    h += '<span class="unified-tester-chip" data-tester-id="' + escapeHTML(bg.testerId) + '" style="' + CHIP_STYLE + ';margin-right:8px;">' + _testerLabel(bg.testerId) + '</span>';
                    // Group index: "1/5"
                    h += '<span style="font-size:11px;color:#888;">' + (ri + 1) + '/' + batch.items.length + '</span>';
                    h += '<span style="flex:1;"></span>';
                    // Config chips — only show non-empty/non-none values
                    var bgRebalance = _rebalanceLabel(bg.rebalanceMode);
                    if (bgRebalance && bgRebalance !== '—' && bgRebalance !== '无') {
                        h += '<span style="' + CHIP_STYLE_PLAIN + ';margin-right:4px;">🔄 ' + escapeHTML(bgRebalance) + '</span>';
                    }
                    var bgCloseToday = _closeTodayLabel(bg.feeMode, bg.useCloseToday);
                    if (bgCloseToday && bgCloseToday !== '—') {
                        h += '<span style="' + CHIP_STYLE_PLAIN + ';margin-right:4px;">🗓️ ' + escapeHTML(bgCloseToday) + '</span>';
                    }
                    // Fee chip: hide when none, show value as plain when fixed/uniform, otherwise clickable
                    if (bg.feeMode && bg.feeMode !== 'none') {
                        if (bg.feeMode === 'fixed' || bg.feeMode === 'uniform') {
                            h += '<span style="' + CHIP_STYLE_PLAIN + ';margin-right:4px;">💰 ' + _feeCellDisplay(bg) + '</span>';
                        } else {
                            h += '<span class="unified-fee-chip" data-gid="' + escapeHTML(bg.id) + '" data-fee-mode="' + escapeHTML(bg.feeMode || '') + '" style="' + CHIP_STYLE + ';cursor:pointer;margin-right:4px;">💰 ' + _feeCellDisplay(bg) + '</span>';
                        }
                    }
                    // Delete button (red X, always last)
                    h += '<button class="unified-bg-del-btn" data-bg-id="' + escapeHTML(bg.id) + '" style="margin-left:4px;padding:1px 5px;font-size:11px;border:1px solid #fca5a5;border-radius:3px;background:#fef2f2;color:#dc2626;cursor:pointer;">✕</button>';
                    h += '</div>';
                    // ── Derived tree rooted at this base group ──
                    h += _renderDerivedTreeForBase(bg.id);
                }
                h += '</div>';
            }
        }
        return h;
    }

    /**
     * Render derived nodes whose baseGroupId matches the given base group id.
     *
     * A derived node attaches to a base group via baseGroupId. Its tree position
     * is determined by parentId — a node can be a child of another derived node
     * (sharing the same baseGroupId). Root-level nodes have parentId that is
     * either null or references a node belonging to a different base group.
     *
     * The rendered tree is indented under the base group row.
     */
    function _renderDerivedTreeForBase(baseGroupId) {
        if (!GT.datamodel.derived_graph) return '';
        var allNodes = GT.datamodel.derived_graph.getAll();
        // Filter nodes belonging to this base group
        var myNodes = [];
        for (var i = 0; i < allNodes.length; i++) {
            if (allNodes[i].baseGroupId === baseGroupId) {
                myNodes.push(allNodes[i]);
            }
        }
        if (myNodes.length === 0) return '';

        // Build complete trees from the full graph so _renderNode gets children
        var treeRoots = GT.datamodel.derived_graph.getTree();
        var treeById = {};
        (function indexTree(nodes) {
            for (var i = 0; i < nodes.length; i++) {
                treeById[nodes[i].id] = nodes[i];
                if (nodes[i].children && nodes[i].children.length > 0) indexTree(nodes[i].children);
            }
        })(treeRoots);

        // Collect ids of all nodes in this base group for fast lookup
        var myIds = {};
        for (var j = 0; j < myNodes.length; j++) { myIds[myNodes[j].id] = true; }

        // Find root-level nodes: those whose parentId is NOT in this base group's set
        // (null parentId or parentId belongs to another base group / unknown)
        var roots = [];
        for (var k = 0; k < myNodes.length; k++) {
            var pid = myNodes[k].parentId;
            if (!pid || !myIds[pid]) {
                var treeNode = treeById[myNodes[k].id];
                if (treeNode) roots.push(treeNode);
            }
        }

        if (roots.length === 0) return '';

        var h = '<div class="unified-derived-subtree" style="margin-left:16px;border-left:2px solid #c7d2fe;padding-left:8px;">';
        for (var r = 0; r < roots.length; r++) {
            h += _renderNode(roots[r], 0);
        }
        h += '</div>';
        return h;
    }

    // ── Render: derived tree section (DEPRECATED — now embedded in _renderBaseSection) ──

    function _renderDerivedSection() {
        // Derived nodes are now rendered inline under their base groups.
        // This function kept for API compatibility; returns empty string.
        return '';
    }

    function _renderNode(node, depth) {
        if (!node) return '';
        var indent = depth * 18;
        var isExp = (node._expanded !== false);
        var isActive = node.id === (GT.state && GT.state.getActiveDerivedNodeId && GT.state.getActiveDerivedNodeId());
        var hasKids = node.children && node.children.length > 0;
        var feeLabel = _derivedFeeDisplay(node);
        var rebalanceLabel = _derivedRebalanceLabel(node);
        var closeTodayLabel = _derivedCloseTodayLabel(node);
        var testerLabel = _derivedTesterLabel(node);
        var badge = _nodeBadge(node);
        var products = _nodeProducts(node);
        var derivedFeeMode = 'none';
        try { derivedFeeMode = GT.datamodel.fee_strategy.resolveFee(node.id).mode; } catch(e) {}

        var rowStyle = isActive ? 'background:#eef2ff;' : (depth % 2 === 0 ? 'background:#fafafa;' : '');

        var h = '';
        h += '<div class="unified-tree-node" data-node-id="' + escapeHTML(node.id) + '" style="padding:4px 0;">';

        // Node header row
        h += '<div class="unified-node-header" style="display:flex;align-items:center;padding:3px 4px;margin-left:' + indent + 'px;border-radius:4px;cursor:pointer;' + rowStyle + '">';
        if (hasKids) {
            h += '<span style="width:20px;text-align:center;margin-right:2px;font-size:14px;line-height:1;">' + (isExp ? '▾' : '▸') + '</span>';
        } else {
            h += '<span style="width:20px;margin-right:2px;"></span>';
        }
        h += '<span style="font-weight:600;font-size:13px;color:#4338ca;">' + escapeHTML(node.name) + '</span>';
        if (node.shortName) {
            h += '<span style="font-weight:600;color:#6366f1;font-size:12px;margin-left:4px;">' + escapeHTML(node.shortName) + '</span>';
        }
        h += '<span style="' + CHIP_STYLE_PLAIN + 'margin-left:8px;">' + escapeHTML(badge) + '</span>';
        if (node.baseGroupId && node.baseGroupId !== '__batch__') {
            var bg = GT.datamodel.base_groups && GT.datamodel.base_groups.get(node.baseGroupId);
            h += '<span style="' + CHIP_STYLE_PLAIN + 'margin-left:4px;">📦 ' + (bg ? escapeHTML(bg.shortAlias || bg.label) : node.baseGroupId) + '</span>';
        }
        h += '<span style="flex:1;"></span>';
        h += '<span class="unified-tester-chip" data-tester-id="' + escapeHTML(node.testerId) + '" style="' + CHIP_STYLE + 'margin-right:8px;">' + escapeHTML(testerLabel) + '</span>';
        if (derivedFeeMode && derivedFeeMode !== 'none') {
            if (derivedFeeMode === 'fixed' || derivedFeeMode === 'uniform') {
                h += '<span style="' + CHIP_STYLE_PLAIN + ';margin-right:4px;">💰 ' + escapeHTML(feeLabel) + '</span>';
            } else {
                h += '<span class="unified-fee-chip" data-dgid="' + escapeHTML(node.id) + '" data-fee-mode="' + escapeHTML(derivedFeeMode || '') + '" style="' + CHIP_STYLE + ';cursor:pointer;margin-right:4px;">💰 ' + escapeHTML(feeLabel) + '</span>';
            }
        }
        if (rebalanceLabel && rebalanceLabel !== '—' && rebalanceLabel !== '无') {
            h += '<span style="' + CHIP_STYLE_PLAIN + ';margin-right:4px;">🔄 ' + escapeHTML(rebalanceLabel) + '</span>';
        }
        if (closeTodayLabel && closeTodayLabel !== '—') {
            h += '<span style="' + CHIP_STYLE_PLAIN + ';margin-right:4px;">🗓️ ' + escapeHTML(closeTodayLabel) + '</span>';
        }
        h += '<button class="unified-dg-add-child-btn" data-dg-id="' + escapeHTML(node.id) + '" style="padding:1px 5px;font-size:10px;border:1px solid #c7d2fe;border-radius:3px;background:#eef2ff;color:#4338ca;cursor:pointer;">＋子</button>';
        h += '<button class="unified-dg-edit-btn" data-dg-id="' + escapeHTML(node.id) + '" style="margin-left:2px;padding:1px 5px;font-size:10px;border:1px solid #d0d5dd;border-radius:3px;background:#fff;cursor:pointer;">✏️</button>';
        h += '<button class="unified-dg-del-btn" data-dg-id="' + escapeHTML(node.id) + '" style="margin-left:2px;padding:1px 5px;font-size:10px;border:1px solid #d0d5dd;border-radius:3px;background:#fff;cursor:pointer;">🗑️</button>';
        h += '</div>';

        // product sub-row (clickable product names)
        h += '<div style="margin-left:' + (indent + 16) + 'px;font-size:11px;color:#6b7280;padding:2px 4px;">品种：';
        for (var pi = 0; pi < products.length; pi++) {
            if (pi > 0) h += ', ';
            var pn = products[pi].name;
            h += '<a href="/products?product=' + encodeURIComponent(pn) + '" target="_blank" style="color:#0078d4;text-decoration:none;font-weight:600;" onclick="event.stopPropagation();">' + escapeHTML(pn) + '</a>';
        }
        if (products.length === 0) h += '—';
        h += '</div>';

        // children
        if (isExp && hasKids) {
            for (var ci = 0; ci < node.children.length; ci++) {
                h += _renderNode(node.children[ci], depth + 1);
            }
        }
        h += '</div>';
        return h;
    }

    // =========================================================================
    // Derived add-child / edit / delete modals
    // =========================================================================

    var _dgModalId = 'unified-dg-form-modal';
    var _dgFormId = 'unified-dg-form';

    function _dgShowModal(editData, parentNodeId) {
        var existing = $(_dgModalId);
        if (existing) existing.remove();

        var isEdit = !!editData;
        var isAddChild = !isEdit && !!parentNodeId;
        var title = isEdit ? '编辑派生组' : (isAddChild ? '新增子派生组' : '新增派生组');

        var bgs = GT.datamodel.base_groups.getAll();
        var html = '<div id="' + _dgModalId + '" style="position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);display:flex;align-items:center;justify-content:center;z-index:10000;">';
        html += '<div style="background:#fff;border-radius:8px;padding:24px;min-width:480px;max-width:600px;box-shadow:0 8px 32px rgba(0,0,0,0.2);">';
        html += '<h3 style="margin:0 0 16px 0;">' + title + '</h3>';
        html += '<form id="' + _dgFormId + '" onsubmit="return false;">';

        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">名称 <span style="color:red;">*</span></span>';
        html += '<input type="text" id="dg-f-name" value="' + escapeHTML(isEdit ? editData.name : '') + '" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;" required>';
        html += '</label>';

        if (!isEdit) {
            // base group for add
            html += '<label style="display:block;margin-bottom:12px;">';
            html += '<span style="display:block;font-size:13px;margin-bottom:4px;">基础组 <span style="color:red;">*</span></span>';
            html += '<select id="dg-f-baseGroupId" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;">';
            html += '<option value="">— 选择 —</option>';
            for (var i = 0; i < bgs.length; i++) {
                html += '<option value="' + escapeHTML(bgs[i].id) + '">' + escapeHTML(bgs[i].label) + ' (' + escapeHTML(bgs[i].factorAlias) + ')</option>';
            }
            html += '</select></label>';
        }

        // product mask
        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">品种筛选（留空=全选）</span>';
        html += '<div id="dg-f-product-mask" style="max-height:120px;overflow-y:auto;border:1px solid #ddd;border-radius:4px;padding:4px 8px;">';
        var testerProds = [];
        if (isEdit) { testerProds = _nodeProducts(editData); }
        else if (parentNodeId) { var pn = GT.datamodel.derived_graph && GT.datamodel.derived_graph.get(parentNodeId); testerProds = pn ? _nodeProducts(pn) : []; }
        else {
            var allPs = {};
            for (var bi = 0; bi < bgs.length; bi++) {
                var pp = _testerProducts(bgs[bi].testerId);
                for (var pi = 0; pi < pp.length; pi++) { allPs[pp[pi].name] = pp[pi]; }
            }
            testerProds = Object.keys(allPs).map(function(k) { return allPs[k]; });
        }
        var existingMask = (editData && editData.productMask) ? editData.productMask : {};
        for (var ti = 0; ti < testerProds.length; ti++) {
            var pName = testerProds[ti].name;
            var checked = Object.keys(existingMask).length === 0 ? ' checked' : (existingMask[pName] ? ' checked' : '');
            html += '<label style="display:inline-block;margin-right:12px;font-size:12px;"><input type="checkbox" class="dg-f-prod" value="' + escapeHTML(pName) + '"' + checked + '> ' + escapeHTML(pName) + '</label>';
        }
        html += '</div></label>';

        html += '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;">';
        html += '<button type="button" id="dg-f-cancel" style="padding:6px 16px;border:1px solid #ddd;border-radius:4px;background:#f6f8fa;cursor:pointer;">取消</button>';
        html += '<button type="submit" id="dg-f-save" style="padding:6px 16px;border:none;border-radius:4px;background:#0078d4;color:#fff;cursor:pointer;">' + (isEdit ? '保存' : '新增') + '</button>';
        html += '</div>';
        html += '</form></div></div>';

        document.body.insertAdjacentHTML('beforeend', html);
        $(_dgModalId)._editId = isEdit ? editData.id : null;
        $(_dgModalId)._parentId = parentNodeId || null;

        $('dg-f-cancel').addEventListener('click', _dgCloseModal);
        $(_dgFormId).addEventListener('submit', _dgHandleSubmit);
        $(_dgModalId).addEventListener('click', function(e) { if (e.target === this) _dgCloseModal(); });
    }

    function _dgCloseModal() {
        var m = $(_dgModalId);
        if (m) m.remove();
    }

    function _dgHandleSubmit(e) {
        e.preventDefault();
        var modal = $(_dgModalId);
        var editId = modal._editId;
        var parentId = modal._parentId;
        var data = { name: $('dg-f-name').value.trim() };
        if (!editId) {
            data.baseGroupId = $('dg-f-baseGroupId').value;
            if (!data.baseGroupId) { alert('请选择基础组'); return; }
        }
        // product mask
        var cbs = document.querySelectorAll('#dg-f-product-mask .dg-f-prod');
        var mask = {};
        if (cbs.length > 0) { for (var i = 0; i < cbs.length; i++) { mask[cbs[i].value] = cbs[i].checked; } }
        data.productMask = mask;

        try {
            if (editId) { GT.datamodel.derived_graph.update(editId, data); }
            else { GT.datamodel.derived_graph.add(data, parentId); }
            _dgCloseModal();
        } catch (err) { alert('操作失败: ' + err.message); }
    }

    // =========================================================================
    // Mount / unmount / export
    // =========================================================================

    var _self = {};

    _self._unbind = function() {};

    _self._stateListener = function() {
        _invalidateExpandCaches();
    };

    _self.mount = function(containerEl) {
        var container = typeof containerEl === 'string' ? $(containerEl) : containerEl;

        function fullRender() {
            _invalidateExpandCaches();
            var h = '<div id="unified-list-container">';
            var lsHtml = _renderLSSection();
            if (lsHtml) {
                h += lsHtml;
                h += '<div style="margin-top:16px;">';
                h += _renderBaseSection();
                h += '</div>';
            } else {
                h += _renderBaseSection();
            }
            h += '</div>';
            container.innerHTML = h;
            _bindEvents(container);
        }

        // ── Batch header click (delegated once, survives fullRender) ──
        container.addEventListener('click', function(e) {
            // Triangle expand/collapse
            var expandEl = e.target.closest('.unified-batch-expand');
            if (expandEl) {
                e.stopPropagation();
                var header = expandEl.closest('.unified-batch-header');
                if (!header) return;
                var key = header.getAttribute('data-batch-key');
                _expandedBatches[key] = !_expandedBatches[key];
                fullRender();
                return;
            }
            // Batch header row → toggle selection
            var header = e.target.closest('.unified-batch-header');
            if (header && !e.target.closest('button')) {
                var key = header.getAttribute('data-batch-key');
                _toggleBatchSelection(_batchMap[key]);
            }
        });

        fullRender();

        // Re-render on state changes
        function rerender() { fullRender(); }
        GT.state.on('lsConfigsChanged', rerender);
        GT.state.on('baseGroupsChanged', rerender);
        GT.state.on('derivedGraphChanged', rerender);
        GT.state.on('activeBaseGroupChanged', rerender);
        GT.state.on('activeDerivedNodeChanged', rerender);
        GT.state.on('activeLSConfigChanged', rerender);
        GT.state.on('feeStrategyChanged', rerender);
        GT.state.on('editModeExited', function() { _selectedIds = {}; rerender(); });

        _self._unbind = function() {
            GT.state.off('lsConfigsChanged', rerender);
            GT.state.off('baseGroupsChanged', rerender);
            GT.state.off('derivedGraphChanged', rerender);
            GT.state.off('activeBaseGroupChanged', rerender);
            GT.state.off('activeDerivedNodeChanged', rerender);
            GT.state.off('activeLSConfigChanged', rerender);
            GT.state.off('feeStrategyChanged', rerender);
            GT.state.off('editModeExited', rerender);
        };
    };

    _self.unmount = function() {
        if (_self._unbind) _self._unbind();
        _self._unbind = function() {};
    };

    // =========================================================================
    // Event binding
    // =========================================================================

    function _bindEvents(container) {
        // ── LS section ──

        container.querySelectorAll('.unified-ls-row').forEach(function(row) {
            row.addEventListener('click', function(e) {
                if (e.target.closest('button')) return;
                var id = this.getAttribute('data-ls-id');
                GT.state.setActiveLsConfigId(id);
            });
        });

        container.querySelectorAll('.unified-ls-edit-btn').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var id = this.getAttribute('data-ls-id');
                var data = GT.datamodel.ls_configs && GT.datamodel.ls_configs.get(id);
                if (data) _lsShowModal(data);
            });
        });

        container.querySelectorAll('.unified-ls-del-btn').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var id = this.getAttribute('data-ls-id');
                if (!confirm('确定删除此多空配置？')) return;
                try { GT.datamodel.ls_configs.remove(id); } catch (err) { alert('删除失败: ' + err.message); }
            });
        });

        // ── Batch delete buttons ──
        container.querySelectorAll('.unified-batch-del-btn').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var batchKey = this.getAttribute('data-batch-key');
                var ids = _batchGroupIds(batchKey);
                if (ids.length === 0) return;
                if (!confirm('确定删除此批次（共 ' + ids.length + ' 组）？')) return;
                try {
                    for (var i = 0; i < ids.length; i++) {
                        GT.datamodel.base_groups.remove(ids[i]);
                    }
                } catch (err) { alert('删除失败: ' + err.message); }
            });
        });

        // ── Base group delete buttons ──
        container.querySelectorAll('.unified-bg-del-btn').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var bgId = this.getAttribute('data-bg-id');
                if (!confirm('确定删除此基础组？')) return;
                try { GT.datamodel.base_groups.remove(bgId); } catch (err) { alert('删除失败: ' + err.message); }
            });
        });

        // ── Base group rows ──
        container.querySelectorAll('.unified-bg-row').forEach(function(row) {
            row.addEventListener('click', function(e) {
                if (e.target.closest('button') || e.target.closest('.unified-fee-chip') || e.target.closest('.unified-tester-chip')) return;
                var id = this.getAttribute('data-bg-id');
                // multi-select: toggle
                if (_selectedIds[id]) { delete _selectedIds[id]; }
                else { _selectedIds[id] = true; }
                _syncEditMode();
                GT.state.emit('activeBaseGroupChanged', id);
            });
        });

        // ── Fee chips (base) ──
        container.querySelectorAll('.unified-fee-chip[data-gid]').forEach(function(chip) {
            chip.addEventListener('click', function(e) {
                e.stopPropagation();
                var gid = this.getAttribute('data-gid');
                var feeMode = this.getAttribute('data-fee-mode') || '';
                GT.state.setActiveBaseGroupId(gid);
                // Per-product or custom: show fee table overlay filtered by tester products
                if ((feeMode === 'per_product' || feeMode === 'custom') && GT.overlays && GT.overlays.feeTable) {
                    var group = GT.datamodel.base_groups.get(gid);
                    var groupName = (group && group.name) ? group.name : ('#' + gid);
                    // Collect product codes for this group's tester
                    var testerId = group ? group.testerId : null;
                    var products = testerId ? _testerProducts(testerId) : [];
                    var productCodes = products.map(function(p) { return p.name; });
                    GT.overlays.feeTable.open(groupName, productCodes);
                } else {
                    // Uniform or fixed: navigate to fee tab
                    if (GT.ui && GT.ui.mountTab) GT.ui.mountTab('fee');
                }
            });
        });

        // ── Fee chips (derived) ──
        container.querySelectorAll('.unified-fee-chip[data-dgid]').forEach(function(chip) {
            chip.addEventListener('click', function(e) {
                e.stopPropagation();
                var dgid = this.getAttribute('data-dgid');
                var feeMode = this.getAttribute('data-fee-mode') || '';
                GT.state.setActiveDerivedNodeId(dgid);
                if ((feeMode === 'per_product' || feeMode === 'custom') && GT.overlays && GT.overlays.feeTable) {
                    var nodeDesc = dgid;
                    if (GT.datamodel.derived_graph && GT.datamodel.derived_graph.get) {
                        var node = GT.datamodel.derived_graph.get(dgid);
                        if (node && node.label) nodeDesc = node.label;
                    }
                    var nodeProducts = _nodeProducts(GT.datamodel.derived_graph.get(dgid));
                    var productCodes = nodeProducts.map(function(p) { return p.name; });
                    GT.overlays.feeTable.open(nodeDesc, productCodes);
                } else {
                    if (GT.ui && GT.ui.mountTab) GT.ui.mountTab('fee');
                }
            });
        });

        // ── Tester chips (open products overlay) ──
        container.querySelectorAll('.unified-tester-chip').forEach(function(chip) {
            chip.addEventListener('click', function(e) {
                e.stopPropagation();
                var testerId = this.getAttribute('data-tester-id');
                if (GT.overlays && GT.overlays.testerProducts) {
                    var products = _testerProducts(testerId);
                    var label = _testerLabel(testerId);
                    GT.overlays.testerProducts.open(label, products);
                }
            });
        });

        // ── Tree nodes ──
        container.querySelectorAll('.unified-node-header').forEach(function(header) {
            header.addEventListener('click', function(e) {
                if (e.target.closest('button') || e.target.closest('.unified-fee-chip') || e.target.closest('.unified-tester-chip')) return;
                var nodeId = this.parentElement.getAttribute('data-node-id');
                // toggle expand
                if (GT.datamodel.derived_graph && GT.datamodel.derived_graph.get) {
                    var node = GT.datamodel.derived_graph.get(nodeId);
                    if (node) { node._expanded = !node._expanded; }
                }
                GT.state.setActiveDerivedNodeId(nodeId);
            });
        });

        // ── Derived add-child ──
        container.querySelectorAll('.unified-dg-add-child-btn').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var dgId = this.getAttribute('data-dg-id');
                _dgShowModal(null, dgId);
            });
        });

        // ── Derived edit ──
        container.querySelectorAll('.unified-dg-edit-btn').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var dgId = this.getAttribute('data-dg-id');
                var node = GT.datamodel.derived_graph && GT.datamodel.derived_graph.get(dgId);
                if (node) _dgShowModal(node, null);
            });
        });

        // ── Derived delete ──
        container.querySelectorAll('.unified-dg-del-btn').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var dgId = this.getAttribute('data-dg-id');
                if (!confirm('确定删除此派生组及其所有子节点？')) return;
                try { GT.datamodel.derived_graph.remove(dgId); } catch (err) { alert('删除失败: ' + err.message); }
            });
        });
    }

    // =========================================================================
    // Export
    // =========================================================================

    window.GroupTest = window.GroupTest || {};
    window.GroupTest.panels = window.GroupTest.panels || {};
    window.GroupTest.panels.list = { index: _self };
})();
