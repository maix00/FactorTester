/**
 * panels/base/list.js — Base group list panel (Tab 1, sub-tab "列表")
 *
 * Phase 3 UI panel. Renders base group table, handles CRUD via modal forms,
 * row selection/highlight. All data access through datamodel + state.
 *
 * Multi-select across batches: click batch header to toggle all groups in batch,
 * click individual row to toggle single group. Selection stored as groupIds set.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.base) { GT.panels.base = {}; }

    // ---------------------------------------------------------------------------
    // Internal state
    // ---------------------------------------------------------------------------

    var _containerId = 'base-groups-list';

    // Track whether panel is currently mounted (sub-tab visible)
    var _mounted = false;

    // Multi-select: set of selected group IDs (cross-batch)
    var _selectedIds = {};  // { id1: true, id2: true, ... }

    /** Compute the current edit selection from _selectedIds */
    function _getEditSelection() {
        var ids = Object.keys(_selectedIds);
        return ids.length > 0 ? { groupIds: ids } : null;
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

    // ---------------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------------

    function $(id) { return document.getElementById(id); }

    function escapeHTML(str) {
        if (str === null || str === undefined) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    /** Column-letter name: 1→A, 2→B, ... 26→Z, 27→AA, 28→AB, ... */
    function _colLetter(n) {
        var s = '';
        while (n > 0) {
            var rem = (n - 1) % 26;
            s = String.fromCharCode(65 + rem) + s;
            n = Math.floor((n - 1) / 26);
        }
        return s;
    }

    /** Generate default name & short alias for a base group.
     *  Letters are assigned per (testerId, factorAlias, groupCount) combo across ALL existing groups.
     *  Accepts optional `_letter` to override the auto-count (for batch-add correctness). */
    function _makeNames(testerId, factorAlias, groupCount, groupIndex, _letter) {
        var subs = window.submissions || [];
        var testerLabel = '';
        for (var i = 0; i < subs.length; i++) {
            if (String(subs[i].id) === String(testerId)) {
                testerLabel = subs[i].product_group || subs[i].label || ('测试器' + subs[i].id);
                break;
            }
        }
        if (!testerLabel) testerLabel = '测试器' + testerId;

        var fullName = testerLabel + '_' + factorAlias + '_' + groupCount + '组_' + '第' + groupIndex + '组';

        var letter;
        if (_letter !== undefined) {
            letter = _letter;
        } else {
            // Determine alias letter: count existing groups with same combo
            var comboKey = String(testerId) + '|' + factorAlias + '|' + groupCount;
            var existing = GT.datamodel.base_groups.getAll();
            var comboCount = 0;
            for (var j = 0; j < existing.length; j++) {
                var k = String(existing[j].testerId) + '|' + existing[j].factorAlias + '|' + existing[j].groupCount;
                if (k === comboKey) comboCount++;
            }
            letter = _colLetter(comboCount + 1);
        }

        var shortAlias = letter + groupIndex;
        return { name: fullName, shortAlias: shortAlias };
    }

    /** Pre-compute the next letter for each (testerId, factorAlias, groupCount) combo
     *  across ALL existing groups. Returns a Map: "testerId|alias|groupCount" → "A"/"B"/... */
    function _preComputeComboLetters(testerId, factorAliases, groupCount) {
        var comboMap = {};
        var existing = GT.datamodel.base_groups.getAll();

        for (var i = 0; i < factorAliases.length; i++) {
            var alias = factorAliases[i];
            var comboKey = String(testerId) + '|' + alias + '|' + groupCount;
            if (comboMap[comboKey] !== undefined) continue; // already counted for this alias

            var comboCount = 0;
            for (var j = 0; j < existing.length; j++) {
                var k = String(existing[j].testerId) + '|' + existing[j].factorAlias + '|' + existing[j].groupCount;
                if (k === comboKey) comboCount++;
            }
            // Plus any combos we've already assigned within this batch call
            comboCount += Object.keys(comboMap).filter(function(key) { return key === comboKey; }).length;

            comboMap[comboKey] = _colLetter(comboCount + 1);
        }
        return comboMap;
    }

    // ---------------------------------------------------------------------------
    // Batch helpers
    // ---------------------------------------------------------------------------

    /** Build a batch key from (testerId, factorAlias, groupCount) */
    function _batchKey(testerId, factorAlias, groupCount) {
        return String(testerId) + '|' + factorAlias + '|' + groupCount;
    }

    /** Group items into batches { key, testerId, factorAlias, groupCount, items:[...] } sorted by key */
    function _buildBatches(items) {
        var batchMap = {};
        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            var key = _batchKey(item.testerId, item.factorAlias, item.groupCount);
            if (!batchMap[key]) {
                batchMap[key] = {
                    key: key,
                    testerId: item.testerId,
                    factorAlias: item.factorAlias,
                    groupCount: item.groupCount,
                    items: []
                };
            }
            batchMap[key].items.push(item);
        }
        // Sort batches by key for stable display
        var keys = Object.keys(batchMap).sort();
        var result = [];
        for (var k = 0; k < keys.length; k++) {
            result.push(batchMap[keys[k]]);
        }
        return result;
    }

    /** Get all group IDs belonging to a batch key */
    function _batchGroupIds(batchKey) {
        var items = GT.datamodel.base_groups.getAll();
        var ids = [];
        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            if (_batchKey(item.testerId, item.factorAlias, item.groupCount) === batchKey) {
                ids.push(item.id);
            }
        }
        return ids;
    }

    // ---------------------------------------------------------------------------
    // Render table
    // ---------------------------------------------------------------------------

    /** Look up label for fee mode */
    function _feeLabel(mode) {
        var map = { 'none': '无', 'percent': '百分比', 'fixed': '固定', 'table': '费率表', 'strategy': '策略' };
        return map[mode] || (mode || '—');
    }

    /** Look up label for close-today mode */
    function _closeTodayLabel(val) {
        return val ? '✅ 平今' : '次日';
    }

    /** Look up label for rebalance mode */
    function _rebalanceLabel(mode) {
        var map = { 'each_period': '每期', 'weekly': '每周', 'monthly': '每月', 'none': '无' };
        return map[mode] || (mode || '—');
    }

    function render() {
        var container = $(_containerId);
        if (!container) return;

        var items = GT.datamodel.base_groups.getAll();
        var batches = _buildBatches(items);

        // --- Empty state ---
        if (batches.length === 0) {
            container.innerHTML = '<div class="group-test-empty-state" style="padding:32px;text-align:center;color:#888;">'
                + '<div style="margin-bottom:12px;">暂无基础组</div>'
                + '<div style="font-size:12px;color:#aaa;">点击上方 sub-tabs 的 ＋ 按钮新增</div>'
                + '</div>';
            return;
        }

        var anySelected = Object.keys(_selectedIds).length > 0;
        var activeBgId = GT.state.getActiveBaseGroupId();

        // Assign letters to multi-group batches (sorted by key), single-group batches get no letter
        var letterIdx = 0;
        var batchLetter = {};  // batchKey → letter (A,B,C) or null for single-group
        for (var b = 0; b < batches.length; b++) {
            if (batches[b].items.length > 1) {
                batchLetter[batches[b].key] = _colLetter(letterIdx + 1);
                letterIdx++;
            } else {
                batchLetter[batches[b].key] = null;
            }
        }
        // Assign numeric aliases to single-group batches
        var soloIdx = 0;
        var soloNumber = {};  // batchKey → "1","2","3"...
        for (var b2 = 0; b2 < batches.length; b2++) {
            if (batchLetter[batches[b2].key] === null) {
                soloIdx++;
                soloNumber[batches[b2].key] = String(soloIdx);
            }
        }

        // Build alias for a row: "A1" or "3"
        function _rowAlias(batchKeyVal, groupIndex) {
            var letter = batchLetter[batchKeyVal];
            if (letter) {
                return letter + groupIndex;
            } else {
                return soloNumber[batchKeyVal];
            }
        }

        var html = '';
        html += '<table style="width:100%;border-collapse:collapse;font-size:13px;">';
        html += '<thead><tr style="background:#f6f8fa;border-bottom:2px solid #d0d5dd;">';
        html += '<th style="padding:6px 10px;text-align:left;width:56px;">简称</th>';
        html += '<th style="padding:6px 10px;text-align:left;">测试器</th>';
        html += '<th style="padding:6px 10px;text-align:left;">因子</th>';
        html += '<th style="padding:6px 8px;text-align:center;">分组</th>';
        html += '<th style="padding:6px 8px;text-align:center;">手续费</th>';
        html += '<th style="padding:6px 8px;text-align:center;">平今</th>';
        html += '<th style="padding:6px 8px;text-align:center;">再平衡</th>';
        html += '<th style="padding:6px 8px;text-align:center;width:50px;">操作</th>';
        html += '</tr></thead><tbody>';

        for (var b3 = 0; b3 < batches.length; b3++) {
            var batch = batches[b3];
            var isMulti = batch.items.length > 1;
            var letter = batchLetter[batch.key];

            // Check if all groups in batch are selected
            var batchAllSelected = batch.items.length > 0;
            for (var bi = 0; bi < batch.items.length; bi++) {
                if (!_selectedIds[batch.items[bi].id]) { batchAllSelected = false; break; }
            }
            var isBatchSelected = batchAllSelected;

            // ── Batch header row (only for multi-group batches) ──
            if (isMulti) {
                var batchRowStyle = isBatchSelected
                    ? 'background:#e8f4fd;border-left:3px solid #0078d4;'
                    : 'background:#f9fafb;border-left:3px solid transparent;';
                html += '<tr class="grouptest-batch-header gt-row' + (isBatchSelected ? ' gt-row-selected' : '') + '" data-batch-key="' + escapeHTML(batch.key) + '"'
                    + ' data-selected="' + (isBatchSelected ? '1' : '0') + '"'
                    + ' style="cursor:pointer;' + batchRowStyle + 'border-bottom:1px solid #d0d5dd;">';
                html += '<td style="padding:6px 10px;font-weight:700;color:' + (isBatchSelected ? '#0078d4' : '#333') + ';">'
                    + '📋 ' + (letter || '') + '</td>';
                html += '<td style="padding:6px 10px;font-size:11px;color:#555;" colspan="2">'
                    + escapeHTML(_testerLabel(batch.testerId)) + ' · ' + escapeHTML(batch.factorAlias) + ' — ' + batch.groupCount + ' 组</td>';
                html += '<td style="padding:6px 8px;text-align:center;"></td>';
                html += '<td style="padding:6px 8px;text-align:center;"></td>';
                html += '<td style="padding:6px 8px;text-align:center;"></td>';
                html += '<td style="padding:6px 8px;text-align:center;"></td>';
                html += '<td style="padding:6px 8px;text-align:center;white-space:nowrap;">';
                html += '<button class="grouptest-batch-del-btn" data-batch-key="' + escapeHTML(batch.key) + '"'
                    + ' style="padding:2px 8px;font-size:11px;border:1px solid #d0d5dd;border-radius:3px;background:#fff;cursor:pointer;"'
                    + ' title="删除整个批次">🗑️</button>';
                html += '</td>';
                html += '</tr>';
            }

            // ── Child rows ──
            for (var r = 0; r < batch.items.length; r++) {
                var item = batch.items[r];
                var isSelected = !!_selectedIds[item.id];
                var isActive = (item.id === activeBgId);
                var rowClass = 'grouptest-base-row gt-row';
                var rowStyle = '';
                if (isSelected) {
                    rowClass += ' gt-row-selected';
                    rowStyle = 'background:#e8f4fd;';
                } else if (isActive && !anySelected) {
                    rowStyle = 'background:#eef6ff;';
                }
                html += '<tr class="' + rowClass + '" data-bg-id="' + escapeHTML(item.id) + '"'
                    + ' data-batch-key="' + escapeHTML(batch.key) + '"'
                    + ' data-selected="' + (isSelected ? '1' : '0') + '"'
                    + ' style="cursor:pointer;border-bottom:1px solid #e8eaed;' + rowStyle + '">';
                // Alias: "A1" for batch groups, "5" for solo groups
                html += '<td style="padding:6px 10px;font-weight:600;color:#0078d4;white-space:nowrap;">'
                    + escapeHTML(_rowAlias(batch.key, item.groupIndex)) + '</td>';
                html += '<td style="padding:6px 10px;font-size:12px;">' + escapeHTML(_testerLabel(item.testerId)) + '</td>';
                html += '<td style="padding:6px 10px;">' + escapeHTML(item.factorAlias) + '</td>';
                html += '<td style="padding:6px 8px;text-align:center;">' + item.groupIndex + '/' + item.groupCount + '</td>';
                html += '<td style="padding:6px 8px;text-align:center;font-size:11px;">' + escapeHTML(_feeLabel(item.feeMode)) + '</td>';
                html += '<td style="padding:6px 8px;text-align:center;font-size:11px;">' + escapeHTML(_closeTodayLabel(item.useCloseToday)) + '</td>';
                html += '<td style="padding:6px 8px;text-align:center;font-size:11px;">' + escapeHTML(_rebalanceLabel(item.rebalanceMode)) + '</td>';
                html += '<td style="padding:6px 8px;text-align:center;white-space:nowrap;">';
                html += '<button class="grouptest-del-btn" data-bg-id="' + escapeHTML(item.id) + '"'
                    + ' style="padding:2px 8px;font-size:11px;border:1px solid #d0d5dd;border-radius:3px;background:#fff;cursor:pointer;">🗑️</button>';
                html += '</td>';
                html += '</tr>';
            }
        }

        html += '</tbody></table>';
        container.innerHTML = html;

        // Bind events
        _bindRowEvents(container);
    }

    function _bindRowEvents(container) {
        // ── Batch header click → toggle all groups in batch ──
        var batchHeaders = container.querySelectorAll('.grouptest-batch-header');
        for (var i = 0; i < batchHeaders.length; i++) {
            batchHeaders[i].addEventListener('click', function(e) {
                if (e.target.tagName === 'BUTTON') return;
                var batchKey = this.getAttribute('data-batch-key');
                var isSelected = this.getAttribute('data-selected') === '1';
                _toggleBatch(batchKey, !isSelected);
            });
        }

        // ── Child row click → toggle single group ──
        var rows = container.querySelectorAll('.grouptest-base-row');
        for (var j = 0; j < rows.length; j++) {
            rows[j].addEventListener('click', function(e) {
                if (e.target.tagName === 'BUTTON') return;
                var bgId = this.getAttribute('data-bg-id');
                var isSelected = this.getAttribute('data-selected') === '1';
                _toggleGroup(bgId, !isSelected);
            });
        }

        // ── Batch delete ──
        var batchDelBtns = container.querySelectorAll('.grouptest-batch-del-btn');
        for (var k = 0; k < batchDelBtns.length; k++) {
            batchDelBtns[k].addEventListener('click', function(e) {
                e.stopPropagation();
                var batchKey = this.getAttribute('data-batch-key');
                var groupIds = _batchGroupIds(batchKey);
                if (groupIds.length === 0) return;
                if (!confirm('确定删除整个批次（共 ' + groupIds.length + ' 个基础组）吗？此操作不可撤销。')) return;
                for (var gi = 0; gi < groupIds.length; gi++) {
                    try { GT.datamodel.base_groups.remove(groupIds[gi]); } catch (err) { /* skip */ }
                    delete _selectedIds[groupIds[gi]];
                }
                _syncSelectionToApp();
            });
        }

        // ── Individual delete ──
        var delBtns = container.querySelectorAll('.grouptest-del-btn');
        for (var d = 0; d < delBtns.length; d++) {
            delBtns[d].addEventListener('click', function(e) {
                e.stopPropagation();
                var id = this.getAttribute('data-bg-id');
                var item = GT.datamodel.base_groups.get(id);
                if (!item) return;
                if (!confirm('确定删除基础组 "' + (item.shortAlias || item.name) + '" 吗？')) return;
                try { GT.datamodel.base_groups.remove(id); } catch (err) { alert('删除失败: ' + err.message); }
                delete _selectedIds[id];
                _syncSelectionToApp();
            });
        }
    }

    /** Toggle a batch: add/remove all its group IDs from selection */
    function _toggleBatch(batchKey, select) {
        var groupIds = _batchGroupIds(batchKey);
        for (var i = 0; i < groupIds.length; i++) {
            if (select) {
                _selectedIds[groupIds[i]] = true;
            } else {
                delete _selectedIds[groupIds[i]];
            }
        }
        _syncSelectionToApp();
        render();
    }

    /** Toggle a single group ID */
    function _toggleGroup(bgId, select) {
        if (select) {
            _selectedIds[bgId] = true;
        } else {
            delete _selectedIds[bgId];
        }
        _syncSelectionToApp();
        render();
    }

    /** Sync _selectedIds state to app.js (enter/exit edit mode) */
    function _syncSelectionToApp() {
        var sel = _getEditSelection();
        if (sel && sel.groupIds.length > 0) {
            // Set first selected group as active for sub-tab panels
            GT.state.setActiveBaseGroupId(sel.groupIds[0]);
            if (GT.ui && typeof GT.ui.enterEditMode === 'function') {
                GT.ui.enterEditMode(sel);
            }
        } else {
            if (GT.ui && typeof GT.ui.exitEditMode === 'function') {
                GT.ui.exitEditMode();
            }
        }
    }

    /** Select a batch — replaced by _toggleBatch; kept for API compat */
    function _selectBatch(batchKey) {
        _toggleBatch(batchKey, true);
    }

    /** Clear all selection */
    function _clearSelection() {
        _selectedIds = {};
        _syncSelectionToApp();
        render();
    }

    /** Save edits: apply reference group params to all selected groups */
    function saveEditChanges() {
        var sel = _getEditSelection();
        if (!sel || !sel.groupIds.length) {
            alert('未选中任何基础组');
            return;
        }
        // Use first selected group as reference
        var refGroup = GT.datamodel.base_groups.get(sel.groupIds[0]);
        if (!refGroup) { _clearSelection(); return; }
        // Batch-sync shared settings
        var sharedKeys = ['feeMode', 'feeRate', 'useCloseToday', 'rebalanceMode', 'isAllGroups'];
        for (var i = 0; i < sel.groupIds.length; i++) {
            var patch = {};
            for (var k = 0; k < sharedKeys.length; k++) {
                var key = sharedKeys[k];
                if (refGroup[key] !== undefined) {
                    patch[key] = refGroup[key];
                }
            }
            try {
                GT.datamodel.base_groups.update(sel.groupIds[i], patch);
            } catch (err) { /* skip */ }
        }
        _clearSelection();
    }

    function _onBaseGroupsChanged(data) {
        if (_mounted) { render(); }
    }

    function _onActiveBaseGroupChanged(data) {
        if (_mounted) {
            // Re-render to update child row highlight
            render();
        }
    }

    // ---------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------

    function mount() {
        _mounted = true;
        var container = $(_containerId);
        if (!container) {
            GT.log('panels.base.list: container #' + _containerId + ' not found');
            return;
        }
        GT.state.on('baseGroupsChanged', _onBaseGroupsChanged);
        GT.state.on('activeBaseGroupChanged', _onActiveBaseGroupChanged);
        render();
    }

    function unmount() {
        _mounted = false;
        GT.state.off('baseGroupsChanged', _onBaseGroupsChanged);
        GT.state.off('activeBaseGroupChanged', _onActiveBaseGroupChanged);
    }

    function refresh() {
        if (_mounted) { render(); }
    }

    /** Get current edit selection (computed from _selectedIds) */
    function getEditSelection() {
        return _getEditSelection();
    }

    /** Get whether any group is selected */
    function hasSelection() {
        return Object.keys(_selectedIds).length > 0;
    }

    // ---------------------------------------------------------------------------
    // Export
    // ---------------------------------------------------------------------------

    GT.panels.base.list = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
        // Batch / multi-select operations
        toggleBatch: _toggleBatch,
        toggleGroup: _toggleGroup,
        clearSelection: _clearSelection,
        saveEditChanges: saveEditChanges,
        getEditSelection: getEditSelection,
        hasSelection: hasSelection,
    };

    GT.log('panels.base.list loaded');
})();
