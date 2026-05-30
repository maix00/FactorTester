/**
 * panels/base/list.js — Base group list panel (Tab 1, sub-tab "列表")
 *
 * Phase 3 UI panel. Renders base group table, handles CRUD via modal forms,
 * row selection/highlight. All data access through datamodel + state.
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

    // Cache current active batch key for highlight tracking
    // Batch key format: "testerId|factorAlias|groupCount"
    var _activeBatchKey = null;

    // Edit state for sub-tab-based edit mode
    var _editSelection = null;  // { batchKey, groupIds:[id,...] }

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

        var html = '';
        html += '<table style="width:100%;border-collapse:collapse;font-size:13px;">';
        html += '<thead><tr style="background:#f6f8fa;border-bottom:2px solid #d0d5dd;">';
        html += '<th style="padding:8px 12px;text-align:left;">简称</th>';
        html += '<th style="padding:8px 12px;text-align:left;">名称</th>';
        html += '<th style="padding:8px 12px;text-align:left;">测试器</th>';
        html += '<th style="padding:8px 12px;text-align:left;">因子</th>';
        html += '<th style="padding:8px 12px;text-align:center;">分组数</th>';
        html += '<th style="padding:8px 12px;text-align:center;">索引</th>';
        html += '<th style="padding:8px 12px;text-align:center;">操作</th>';
        html += '</tr></thead><tbody>';

        for (var b = 0; b < batches.length; b++) {
            var batch = batches[b];
            var isBatchActive = (batch.key === _activeBatchKey);

            // ── Batch header row ──
            var batchRowStyle = isBatchActive
                ? 'background:#e8f4fd;border-left:3px solid #0078d4;'
                : 'background:#f9fafb;border-left:3px solid transparent;';
            html += '<tr class="grouptest-batch-header" data-batch-key="' + escapeHTML(batch.key) + '"'
                + ' style="cursor:pointer;' + batchRowStyle + 'border-bottom:1px solid #d0d5dd;">';
            html += '<td style="padding:6px 12px;font-weight:700;color:' + (isBatchActive ? '#0078d4' : '#333') + ';">'
                + '📋 ' + escapeHTML(batch.factorAlias) + '</td>';
            html += '<td style="padding:6px 12px;font-size:11px;color:#555;" colspan="2">'
                + escapeHTML(_testerLabel(batch.testerId)) + ' — ' + batch.groupCount + ' 组</td>';
            html += '<td style="padding:6px 12px;"></td>';
            html += '<td style="padding:6px 12px;text-align:center;"></td>';
            html += '<td style="padding:6px 12px;text-align:center;"></td>';
            html += '<td style="padding:6px 12px;text-align:center;white-space:nowrap;">';
            html += '<button class="grouptest-batch-del-btn" data-batch-key="' + escapeHTML(batch.key) + '"'
                + ' style="padding:2px 8px;font-size:11px;border:1px solid #d0d5dd;border-radius:3px;background:#fff;cursor:pointer;"'
                + ' title="删除整个批次">🗑️ 删除批次</button>';
            html += '</td>';
            html += '</tr>';

            // ── Child rows (hidden when batch collapsed? No — always show) ──
            for (var r = 0; r < batch.items.length; r++) {
                var item = batch.items[r];
                var isItemActive = (item.id === GT.state.getActiveBaseGroupId());
                var itemRowStyle = isItemActive ? 'background:#eef6ff;' : '';
                html += '<tr class="grouptest-base-row" data-bg-id="' + escapeHTML(item.id) + '"'
                    + ' data-batch-key="' + escapeHTML(batch.key) + '"'
                    + ' style="cursor:pointer;border-bottom:1px solid #e8eaed;' + itemRowStyle + '">';
                html += '<td style="padding:6px 12px;font-weight:600;color:#0078d4;">' + escapeHTML(item.shortAlias || item.name) + '</td>';
                html += '<td style="padding:6px 12px;font-size:11px;color:#555;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escapeHTML(item.name) + '</td>';
                html += '<td style="padding:6px 12px;">' + escapeHTML(_testerLabel(item.testerId)) + '</td>';
                html += '<td style="padding:6px 12px;">' + escapeHTML(item.factorAlias) + '</td>';
                html += '<td style="padding:6px 12px;text-align:center;">' + item.groupCount + '</td>';
                html += '<td style="padding:6px 12px;text-align:center;">' + item.groupIndex + '</td>';
                html += '<td style="padding:6px 12px;text-align:center;white-space:nowrap;">';
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
        // ── Batch header click → select batch, enter edit mode ──
        var batchHeaders = container.querySelectorAll('.grouptest-batch-header');
        for (var i = 0; i < batchHeaders.length; i++) {
            batchHeaders[i].addEventListener('click', function(e) {
                if (e.target.tagName === 'BUTTON') return; // don't select when clicking delete button
                var batchKey = this.getAttribute('data-batch-key');
                _selectBatch(batchKey);
            });
        }

        // ── Child row click → also select the parent batch (edit mode) ──
        var rows = container.querySelectorAll('.grouptest-base-row');
        for (var j = 0; j < rows.length; j++) {
            rows[j].addEventListener('click', function(e) {
                if (e.target.tagName === 'BUTTON') return;
                var batchKey = this.getAttribute('data-batch-key');
                var bgId = this.getAttribute('data-bg-id');
                // Select the batch AND the individual group as active
                _selectBatch(batchKey);
                GT.state.setActiveBaseGroupId(bgId);
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
                }
                // Clear selection if we deleted the active batch
                if (_activeBatchKey === batchKey) { _clearSelection(); }
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
                // Refresh edit selection if needed
                if (_editSelection && _editSelection.groupIds.indexOf(id) >= 0) {
                    _editSelection = null;
                }
            });
        }
    }

    /** Select a batch → enter list-level edit state */
    function _selectBatch(batchKey) {
        _activeBatchKey = batchKey;
        var groupIds = _batchGroupIds(batchKey);
        _editSelection = { batchKey: batchKey, groupIds: groupIds };
        // Set the first group as active so sub-tab panels can edit it
        if (groupIds.length > 0) {
            GT.state.setActiveBaseGroupId(groupIds[0]);
        }
        // Notify app.js to enter edit mode
        if (GT.ui && typeof GT.ui.enterEditMode === 'function') {
            GT.ui.enterEditMode({ batchKey: batchKey, groupIds: groupIds });
        }
        // Re-render to update highlights
        render();
    }

    /** Clear selection/exit edit */
    function _clearSelection() {
        _activeBatchKey = null;
        _editSelection = null;
        // Notify app.js to exit edit mode
        if (GT.ui && typeof GT.ui.exitEditMode === 'function') {
            GT.ui.exitEditMode();
        }
        render();
    }

    /** Save edits: apply current batch state to all groups in the batch */
    function saveEditChanges() {
        if (!_editSelection || !_editSelection.groupIds.length) {
            alert('未选中任何批次');
            return;
        }
        // The actual save happens in the sub-tab panels (groups/fee/close_today/rebalance)
        // which write via GT.datamodel.base_groups.update(). This function is called
        // when user clicks "保存修改" — it just exits edit mode.
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

    /** Get current edit selection */
    function getEditSelection() {
        return _editSelection;
    }

    /** Get active batch key */
    function getActiveBatchKey() {
        return _activeBatchKey;
    }

    // ---------------------------------------------------------------------------
    // Export
    // ---------------------------------------------------------------------------

    GT.panels.base.list = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
        // Batch operations
        selectBatch: _selectBatch,
        clearSelection: _clearSelection,
        saveEditChanges: saveEditChanges,
        getEditSelection: getEditSelection,
        getActiveBatchKey: getActiveBatchKey,
    };

    GT.log('panels.base.list loaded');
})();
