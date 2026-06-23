/**
 * panels/add/group.js — Add-flow panel: "新建分组" (category-2)
 *
 * Renders tester selector → groupIndex/splitCount (side-by-side) → allGroups
 * checkbox → factor selector → submit handled by app.js
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.add) { GT.panels.add = {}; }

    var _containerId = 'add-group';
    var _mounted = false;

    function $(id) { return document.getElementById(id); }

    function escapeHTML(str) { return GT.escapeHTML(str); }

    // ── Delegated utilities ──

    var _addGroupBatchKey = GT.groupSettings.addGroupBatch.key;

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

    function _selectionId(selection) {
        var utils = window.ProductPathSelectionUtils;
        return utils && utils.selectionId ? utils.selectionId(selection)
            : (selection ? String(selection.product_path_selection_id || selection.id || selection.selection_id || '') : '');
    }

    function _currentSelections() {
        var utils = window.ProductPathSelectionUtils || {};
        var selections = [];
        var groups = GT.groupSettings && GT.groupSettings.groups && GT.groupSettings.groups.getAll
            ? GT.groupSettings.groups.getAll()
            : [];
        groups.forEach(function(group) {
            if (group && group.product_path_selection) selections.push(group.product_path_selection);
        });
        if (GT.backendSettings && typeof GT.backendSettings.getProductPathSelections === 'function') {
            selections = selections.concat(GT.backendSettings.getProductPathSelections());
        }
        var local = GT.backendSettings && GT.backendSettings._state && GT.backendSettings._state.localValues
            ? GT.backendSettings._state.localValues.product_path_selection
            : null;
        if (local) selections.push(local);
        return utils.dedupe ? utils.dedupe(selections) : selections;
    }

    function _findSelection(selectionId) {
        var selections = _currentSelections();
        for (var i = 0; i < selections.length; i++) {
            if (_selectionId(selections[i]) === String(selectionId || '')) return selections[i];
        }
        return null;
    }

    function _selectionLabel(selection) {
        var utils = window.ProductPathSelectionUtils;
        if (utils && utils.selectionLabel) return utils.selectionLabel(selection);
        return selection ? (selection.product_group || selection.label || selection.name || _selectionId(selection)) : '';
    }

    function _selectionSourceLabel(selection) {
        var utils = window.ProductPathSelectionUtils;
        if (utils && utils.selectionSourceLabel) return utils.selectionSourceLabel(selection);
        if (!selection) return '';
        if (selection.product_group_template_id || selection.product_group || selection.product_group_name) return '产品组';
        if (selection.path_id) return '路径组';
        return '现场';
    }

    function _selectionDisplayLabel(selection) {
        var utils = window.ProductPathSelectionUtils;
        if (utils && utils.selectionDisplayLabel) return utils.selectionDisplayLabel(selection);
        var label = _selectionLabel(selection);
        var source = _selectionSourceLabel(selection);
        return source ? label + ' · ' + source : label;
    }

    function _comboKeyForGroup(group) {
        return _addGroupBatchKey(_selectionId(group && group.product_path_selection), group && group.factorAlias, group && group.splitCount);
    }

    function _preComputeComboLetters(selectionId, factorAliases, splitCount) {
        var comboMap = {};
        var existing = GT.groupSettings.groups.getAll();

        for (var i = 0; i < factorAliases.length; i++) {
            var alias = factorAliases[i];
            var comboKey = _addGroupBatchKey(selectionId, alias, splitCount);
            if (comboMap[comboKey] !== undefined) continue;

            // Check existing groups for this combo
            var hasExisting = false;
            for (var j = 0; j < existing.length; j++) {
                var k = _comboKeyForGroup(existing[j]);
                if (k === comboKey) { hasExisting = true; break; }
            }
            if (hasExisting) {
                for (var ej = 0; ej < existing.length; ej++) {
                    var ek = _comboKeyForGroup(existing[ej]);
                    if (ek === comboKey && existing[ej].shortAlias) {
                        var letterMatch = existing[ej].shortAlias.match(/^([A-Z]+)/);
                        if (letterMatch) {
                            comboMap[comboKey] = letterMatch[1];
                            break;
                        }
                    }
                }
                if (!comboMap[comboKey]) {
                    comboMap[comboKey] = _colLetter(Object.keys(comboMap).length + 1);
                }
            } else {
                // New comboKey: assign a brand-new letter
                var usedLetters = {};
                for (var ej2 = 0; ej2 < existing.length; ej2++) {
                    var ek2 = _comboKeyForGroup(existing[ej2]);
                    if (ek2 && existing[ej2].shortAlias) {
                        var lm = existing[ej2].shortAlias.match(/^([A-Z]+)/);
                        if (lm) usedLetters[lm[1]] = true;
                    }
                }
                var comboKeysArr = Object.keys(comboMap);
                for (var ci = 0; ci < comboKeysArr.length; ci++) {
                    var assignedLetter = comboMap[comboKeysArr[ci]];
                    if (assignedLetter) usedLetters[assignedLetter] = true;
                }
                var nextIdx = 1;
                while (usedLetters[_colLetter(nextIdx)]) { nextIdx++; }
                comboMap[comboKey] = _colLetter(nextIdx);
            }
        }
        return comboMap;
    }

    function _makeNames(selection, factorAlias, splitCount, groupIndex, letter) {
        var selectionLabel = _selectionLabel(selection) || '产品路径选择';
        var fullName = selectionLabel + '_' + factorAlias + '_' + splitCount + '组_' + '第' + groupIndex + '组';
        var shortAlias = letter + groupIndex;

        var allGroups = GT.groupSettings.groups.getAll();
        var comboKey = _addGroupBatchKey(_selectionId(selection), factorAlias, splitCount);
        var sameIndexCount = 0;
        var usedSuffixes = {};
        for (var ai = 0; ai < allGroups.length; ai++) {
            var g = allGroups[ai];
            var gk = _comboKeyForGroup(g);
            if (gk !== comboKey) continue;
            if (g.groupIndex === groupIndex) { sameIndexCount++; }
            var sa = g.shortAlias;
            if (sa && sa.length > shortAlias.length && sa.lastIndexOf(shortAlias, 0) === 0) {
                var ch = sa.charAt(shortAlias.length);
                if (ch >= 'a' && ch <= 'z') usedSuffixes[ch] = true;
            }
        }
        if (sameIndexCount > 0 || Object.keys(usedSuffixes).length > 0) {
            var sfx = 'a'.charCodeAt(0);
            while (usedSuffixes[String.fromCharCode(sfx)]) { sfx++; }
            shortAlias = shortAlias + String.fromCharCode(sfx);
        }

        return { name: fullName, shortAlias: shortAlias };
    }

    function _comboLetterForEdit(groupId, selection, factorAlias, splitCount) {
        var selectionId = _selectionId(selection);
        var comboKey = _addGroupBatchKey(selectionId, factorAlias, splitCount);
        var existing = GT.groupSettings.groups.getAll();
        var extractLetter = GT.groupSettings.groups.extractLetter;
        for (var i = 0; i < existing.length; i++) {
            var group = existing[i];
            if (!group || group.id === groupId || group.parentId) continue;
            if (_comboKeyForGroup(group) === comboKey) {
                var existingLetter = extractLetter ? extractLetter(group.shortAlias) : null;
                if (existingLetter) return existingLetter;
            }
        }
        var usedLetters = {};
        for (var j = 0; j < existing.length; j++) {
            var other = existing[j];
            if (!other || other.id === groupId || other.parentId) continue;
            var letter = extractLetter ? extractLetter(other.shortAlias) : null;
            if (letter) usedLetters[letter] = true;
        }
        var nextIdx = 1;
        while (usedLetters[_colLetter(nextIdx)]) nextIdx++;
        return _colLetter(nextIdx);
    }

    function _makeEditNames(groupId, selection, factorAlias, splitCount, groupIndex) {
        var selectionLabel = _selectionLabel(selection) || '产品路径选择';
        var letter = _comboLetterForEdit(groupId, selection, factorAlias, splitCount);
        var fullName = selectionLabel + '_' + factorAlias + '_' + splitCount + '组_' + '第' + groupIndex + '组';
        var shortAlias = letter + groupIndex;
        var comboKey = _addGroupBatchKey(_selectionId(selection), factorAlias, splitCount);
        var existing = GT.groupSettings.groups.getAll();
        var usedSuffixes = {};
        var hasSameIndex = false;
        for (var i = 0; i < existing.length; i++) {
            var item = existing[i];
            if (!item || item.id === groupId || item.parentId) continue;
            if (_comboKeyForGroup(item) !== comboKey) continue;
            if (Number(item.groupIndex) === Number(groupIndex)) hasSameIndex = true;
            var sa = item.shortAlias || '';
            if (sa.length > shortAlias.length && sa.lastIndexOf(shortAlias, 0) === 0) {
                var ch = sa.charAt(shortAlias.length);
                if (ch >= 'a' && ch <= 'z') usedSuffixes[ch] = true;
            }
        }
        if (hasSameIndex || Object.keys(usedSuffixes).length > 0) {
            var sfx = 'a'.charCodeAt(0);
            while (usedSuffixes[String.fromCharCode(sfx)]) sfx++;
            shortAlias += String.fromCharCode(sfx);
        }
        return { name: fullName, shortAlias: shortAlias };
    }

    // ── Render ──
    //
    // Master-inspired two-column layout:
    //   Left column  — tester navigation (vertical buttons, like .group-nav-column)
    //   Right column — group params + multi-select factor list

    function render() {
        var container = $(_containerId);
        if (!container) return;

        var selections = _currentSelections();
        var factors = window.factorList || [];
        var draft = GT.tabs.getAddDraft();
        if (!draft) return;

        var html = '';

        // ═══════════════════════════════════════════════════════
        // Two-column shell
        // ═══════════════════════════════════════════════════════
        html += '<div style="display:grid;grid-template-columns:minmax(180px,220px) minmax(280px,1fr);gap:12px;align-items:start;">';

        // ─────────────────────────────────────────────────────────
        // LEFT COLUMN: Tester navigation (master-style)
        // ─────────────────────────────────────────────────────────
        html += '<div style="border:1px solid #e5e7eb;border-radius:8px;background:#fff;padding:6px;max-height:440px;overflow:auto;">';
        html += '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;padding:4px 6px 8px;">';
        html += '<span style="font-size:12px;font-weight:700;color:#475467;">产品路径</span>';
        html += '<button type="button" id="add-manage-product-paths" style="height:22px;padding:0 7px;border:1px solid #cbd5e1;border-radius:4px;background:#fff;color:#475569;font-size:11px;cursor:pointer;">管理</button>';
        html += '</div>';
        if (selections.length === 0) {
            html += '<div style="color:#888;font-size:12px;padding:8px;line-height:1.6;">暂无产品路径组。请先进入产品路径设置新增、导入或指定默认路径组。</div>';
        } else {
            for (var i = 0; i < selections.length; i++) {
                var selection = selections[i];
                var selectionId = _selectionId(selection);
                var label = _selectionDisplayLabel(selection) || ('产品路径 #' + selectionId);
                var paths = selection.selected_paths || selection.paths || [];
                var subMeta = _selectionSourceLabel(selection) || (paths.length + ' 路径');
                var activeId = _selectionId(draft.product_path_selection);
                var isActive = (activeId === selectionId);
                html += '<button type="button" class="add-product-path-selection-nav-btn" data-selection-id="' + escapeHTML(selectionId) + '"'
                    + ' style="width:100%;display:flex;align-items:center;justify-content:space-between;gap:8px;'
                    + 'border:1px solid ' + (isActive ? '#9cc7f2' : 'transparent') + ';'
                    + 'background:' + (isActive ? '#e7f1ff' : 'transparent') + ';'
                    + 'border-radius:6px;padding:7px 8px;margin-bottom:4px;'
                    + 'text-align:left;cursor:pointer;font-size:12px;color:#1f2937;">'
                    + '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escapeHTML(label) + '</span>'
                    + '<small style="color:#667085;font-size:11px;">' + escapeHTML(subMeta) + '</small>'
                    + '</button>';
            }
        }
        html += '</div>';

        // ─────────────────────────────────────────────────────────
        // RIGHT COLUMN: Group params + Factor multi-select
        // ─────────────────────────────────────────────────────────
        html += '<div style="border:1px solid #e5e7eb;border-radius:8px;background:#fff;padding:12px;">';

        // ── Group params (compact row) ──
        html += '<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px;">';
        html += '<span style="font-size:13px;font-weight:600;color:#333;">分组</span>';
        html += '<input type="number" id="add-group-count" value="' + (draft.splitCount || 5) + '" min="1" step="1"'
            + ' style="width:70px;padding:5px 8px;border:1px solid #d0d5dd;border-radius:4px;font-size:13px;text-align:center;"'
            + ' title="分组数量">';
        html += '<span style="font-size:13px;color:#555;">组，只建第</span>';
        html += '<input type="number" id="add-group-index" value="' + (draft.groupIndex || 1) + '" min="1" step="1"'
            + (draft.allGroups ? ' disabled style="width:70px;padding:5px 8px;border:1px solid #ddd;border-radius:4px;background:#f0f0f0;color:#999;text-align:center;"'
               : ' style="width:70px;padding:5px 8px;border:1px solid #d0d5dd;border-radius:4px;font-size:13px;text-align:center;"')
            + ' title="分组索引（从1开始）">';
        html += '<span style="font-size:13px;color:#555;">组</span>';
        html += '</div>';
        html += '<div style="margin-bottom:12px;">';
        html += '<label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px;">';
        html += '<input type="checkbox" id="add-all-groups" ' + (draft.allGroups ? 'checked' : '') + ' style="width:16px;height:16px;">';
        html += '<span>所有分组（为每个分组索引都创建一个基础组）</span>';
        html += '</label>';
        html += '</div>';

        // ── Separator ──
        html += '<div style="border-top:1px solid #eef2f7;margin:0 0 12px 0;"></div>';

        // ── Tester info banner ──
        if (draft.product_path_selection) {
            var selectedLabel = _selectionLabel(draft.product_path_selection);
            html += '<div style="margin-bottom:12px;padding:8px 12px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:4px;font-size:12px;color:#0369a1;">';
            html += '已选：<b>' + escapeHTML(selectedLabel || '产品路径选择') + '</b> · ' + (draft.splitCount || 5) + '组';
            if (draft.allGroups) html += ' · 所有分组';
            else html += ' · 第 <b>' + (draft.groupIndex || 1) + '</b> 组';
            html += '</div>';
        } else {
            html += '<div style="margin-bottom:12px;padding:8px 12px;background:#fff7ed;border:1px solid #fed7aa;border-radius:4px;font-size:12px;color:#c2410c;">';
            html += '请先在左侧选择产品路径';
            html += '</div>';
        }

        // ── Factor toolbar ──
        html += '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">';
        html += '<div style="font-size:13px;font-weight:600;color:#333;">选择因子 <span style="color:red;">*</span></div>';
        html += '<div style="display:flex;gap:6px;">';
        html += '<button id="add-select-all" style="padding:4px 10px;border:1px solid #10b981;border-radius:4px;background:#10b981;color:#fff;cursor:pointer;font-size:12px;font-weight:600;">全选</button>';
        html += '<button id="add-deselect-all" style="padding:4px 10px;border:1px solid #d0d5dd;border-radius:4px;background:#fff;color:#666;cursor:pointer;font-size:12px;">清空</button>';
        html += '</div>';
        html += '</div>';

        // ── Factor list (scrollable, checkbox style) ──
        html += '<div style="max-height:340px;overflow:auto;border:1px solid #e8eaed;border-radius:6px;">';
        if (factors.length === 0) {
            html += '<div style="color:#888;font-size:12px;padding:16px;text-align:center;">暂无因子数据</div>';
        } else {
            for (var j = 0; j < factors.length; j++) {
                var alias = factors[j].alias || factors[j].name || '';
                var isSelected = (draft.selectedFactors || []).indexOf(alias) >= 0;
                html += '<div class="add-factor-row" data-factor-alias="' + escapeHTML(alias) + '"'
                    + ' style="display:flex;align-items:center;gap:8px;padding:7px 10px;cursor:pointer;'
                    + (isSelected ? 'background:#e8f4fd;' : '')
                    + 'border-bottom:1px solid #f0f2f5;font-size:13px;'
                    + (j === factors.length - 1 ? '' : '') + '">';
                html += '<input type="checkbox" class="add-factor-cb" data-factor-alias="' + escapeHTML(alias) + '"'
                    + (isSelected ? ' checked' : '')
                    + ' style="width:15px;height:15px;cursor:pointer;flex-shrink:0;">';
                html += '<span style="flex:1;">' + escapeHTML(alias) + '</span>';
                html += '<span style="font-size:11px;color:' + (isSelected ? '#0078d4' : '#ccc') + ';">' + (isSelected ? '✓' : '') + '</span>';
                html += '</div>';
            }
        }
        html += '</div>';

        html += '</div>'; // close right column
        html += '</div>'; // close two-column shell

        container.innerHTML = html;

        // ── Bind events ──

        // Product-path selection nav buttons
        var selectionBtns = container.querySelectorAll('.add-product-path-selection-nav-btn');
        for (var tb = 0; tb < selectionBtns.length; tb++) {
            selectionBtns[tb].addEventListener('click', function() {
                var selectionId = this.getAttribute('data-selection-id');
                GT.tabs.updateAddDraft({ product_path_selection: _findSelection(selectionId) });
                render();
            });
        }
        var managePathsBtn = $('add-manage-product-paths');
        if (managePathsBtn) {
            managePathsBtn.addEventListener('click', function() {
                if (GT.backendSettings && typeof GT.backendSettings.openLocalTab === 'function') {
                    GT.backendSettings.openLocalTab('product_path_selection');
                }
            });
        }

        // Group count
        var gcInput = $('add-group-count');
        if (gcInput) {
            gcInput.addEventListener('input', function() {
                var v = parseInt(this.value, 10);
                if (v >= 1) GT.tabs.updateAddDraft({ splitCount: v });
            });
            gcInput.addEventListener('blur', function() {
                var v = parseInt(this.value, 10);
                if (isNaN(v) || v < 1) { this.value = 2; GT.tabs.updateAddDraft({ splitCount: 2 }); }
            });
        }

        // Group index
        var giInput = $('add-group-index');
        if (giInput) {
            giInput.addEventListener('input', function() {
                var v = parseInt(this.value, 10);
                if (v >= 1) GT.tabs.updateAddDraft({ groupIndex: v });
            });
        }

        // All groups checkbox
        var agCheck = $('add-all-groups');
        if (agCheck) {
            agCheck.addEventListener('change', function() {
                GT.tabs.updateAddDraft({ allGroups: this.checked });
                render();
            });
        }

        // Factor rows (click on row or checkbox toggles selection)
        var factorRows = container.querySelectorAll('.add-factor-row');
        for (var fi = 0; fi < factorRows.length; fi++) {
            factorRows[fi].addEventListener('click', function(e) {
                // Don't double-fire if clicking directly on the checkbox
                if (e.target.tagName === 'INPUT') return;
                var alias = this.getAttribute('data-factor-alias');
                _toggleFactor(alias, draft);
            });
        }
        // Factor checkboxes
        var factorCbs = container.querySelectorAll('.add-factor-cb');
        for (var fc = 0; fc < factorCbs.length; fc++) {
            factorCbs[fc].addEventListener('change', function() {
                var alias = this.getAttribute('data-factor-alias');
                _toggleFactor(alias, draft);
            });
        }

        // Select all
        var selectAllBtn = $('add-select-all');
        if (selectAllBtn) {
            selectAllBtn.addEventListener('click', function() {
                var allAliases = [];
                for (var fa = 0; fa < factors.length; fa++) {
                    var a = factors[fa].alias || factors[fa].name || '';
                    if (a) allAliases.push(a);
                }
                GT.tabs.updateAddDraft({ selectedFactors: allAliases });
                render();
            });
        }

        // Deselect all
        var deselectAllBtn = $('add-deselect-all');
        if (deselectAllBtn) {
            deselectAllBtn.addEventListener('click', function() {
                GT.tabs.updateAddDraft({ selectedFactors: [] });
                render();
            });
        }
    }

    /** Toggle a single factor in the draft selection */
    function _toggleFactor(alias, draft) {
        var selected = (draft.selectedFactors || []).slice();
        var idx = selected.indexOf(alias);
        if (idx >= 0) {
            selected.splice(idx, 1);
        } else {
            selected.push(alias);
        }
        GT.tabs.updateAddDraft({ selectedFactors: selected });
        render();
    }

    // ── Submit ──

    function submitAddBatches(draft) {
        if (!draft || !draft.product_path_selection) { alert('请先选择产品路径'); return; }
        var selection = draft.product_path_selection;
        var selectionId = _selectionId(selection);
        var splitCount = draft.splitCount;
        var allGroups = draft.allGroups;
        var groupIndex = draft.groupIndex;
        var factors = draft.selectedFactors || [];

        if (factors.length === 0) { alert('请至少选择一个因子'); return; }

        var comboLetters = _preComputeComboLetters(selectionId, factors, splitCount);

        var added = 0;

        var selectionLabel = _selectionLabel(selection) || ('产品路径' + selectionId);

        for (var fi = 0; fi < factors.length; fi++) {
            var alias = factors[fi];
            var comboKey = _addGroupBatchKey(selectionId, alias, splitCount);
            var letter = comboLetters[comboKey] || 'A';

            if (allGroups) {
                for (var gi = 1; gi <= splitCount; gi++) {
                    var names = _makeNames(selection, alias, splitCount, gi, letter);
                    try {
                        GT.groupSettings.groups.add({
                            name: names.name,
                            shortAlias: names.shortAlias,
                            product_path_selection: selection,
                            factorAlias: alias,
                            splitCount: splitCount,
                            groupIndex: gi,
                            isAllGroups: false,
                        });
                        added++;
                    } catch (err) { /* skip dup */ }
                }
            } else {
                var names2 = _makeNames(selection, alias, splitCount, groupIndex, letter);
                try {
                    GT.groupSettings.groups.add({
                        name: names2.name,
                        shortAlias: names2.shortAlias,
                        product_path_selection: selection,
                        factorAlias: alias,
                        splitCount: splitCount,
                        groupIndex: groupIndex,
                        isAllGroups: false,
                    });
                    added++;
                } catch (err) { /* skip dup */ }
            }
        }
        return { added: added };
    }

    // ── Lifecycle ──

    function _onDraftChanged() {
        if (_mounted) render();
    }

    function mount() {
        _mounted = true;
        var container = $(_containerId);
        if (!container) {
            GT.log('panels.base.add: container #' + _containerId + ' not found');
            return;
        }
        render();
        if (GT.backendSettings && typeof GT.backendSettings.loadProductPathSelections === 'function') {
            GT.backendSettings.loadProductPathSelections().then(function() {
                if (_mounted) render();
            }).catch(function(error) {
                console.error('[group add] load product paths failed:', error);
            });
        }
    }

    function unmount() {
        _mounted = false;
    }

    function refresh() {
        if (_mounted) render();
    }

    // ── Export ──

    GT.panels.add = GT.panels.add || {};
    GT.panels.add.group = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
        submitAddBatches: submitAddBatches,
    };

    function _selectedEditGroup() {
        var ctx = GT.modes && GT.modes.getEditContext ? GT.modes.getEditContext() : null;
        return ctx && ctx.groups && ctx.groups.length === 1 ? ctx.groups[0] : null;
    }

    function _selectedEditGroups() {
        var ctx = GT.modes && GT.modes.getEditContext ? GT.modes.getEditContext() : null;
        return ctx && ctx.groups ? ctx.groups.filter(function(group) { return !!group; }) : [];
    }

    function _selectedEditBaseGroups() {
        return _selectedEditGroups().filter(function(group) { return group && !group.parentId; });
    }

    function _commonEditValue(groups, key) {
        if (!groups.length) return null;
        var first = key === 'product_path_selection' ? _selectionId(groups[0][key]) : groups[0][key];
        for (var i = 1; i < groups.length; i++) {
            var value = key === 'product_path_selection' ? _selectionId(groups[i][key]) : groups[i][key];
            if (String(value || '') !== String(first || '')) return null;
        }
        return groups[0][key];
    }

    function _renderEditGroup(container) {
        var selectedGroups = _selectedEditGroups();
        var groups = _selectedEditBaseGroups();
        if (!groups.length) {
            container.innerHTML = '<div style="padding:16px;color:#64748b;font-size:12px;">请选择至少一个基础组进行修改。</div>';
            return;
        }
        var group = groups[0];
        var isSingle = groups.length === 1;
        var derivedSelectedCount = selectedGroups.length - groups.length;
        var selections = _currentSelections();
        var factors = window.factorList || [];
        var commonSelection = _commonEditValue(groups, 'product_path_selection');
        var currentSelectionId = commonSelection ? _selectionId(commonSelection) : '';
        var commonFactor = _commonEditValue(groups, 'factorAlias');
        var factorAlias = commonFactor || '';
        var groupIndex = Number(group.groupIndex || 1);
        var commonSplit = _commonEditValue(groups, 'splitCount');
        var splitCount = Number(commonSplit || groupIndex || 1);

        var html = '';
        html += '<div style="display:grid;grid-template-columns:minmax(180px,220px) minmax(280px,1fr);gap:12px;align-items:start;">';
        html += '<div style="border:1px solid #e5e7eb;border-radius:8px;background:#fff;padding:6px;max-height:440px;overflow:auto;">';
        html += '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;padding:4px 6px 8px;">';
        html += '<span style="font-size:12px;font-weight:700;color:#475467;">产品路径</span>';
        html += '<button type="button" id="edit-manage-product-paths" style="height:22px;padding:0 7px;border:1px solid #cbd5e1;border-radius:4px;background:#fff;color:#475569;font-size:11px;cursor:pointer;">管理</button>';
        html += '</div>';
        if (selections.length === 0) {
            html += '<div style="color:#888;font-size:12px;padding:8px;line-height:1.6;">暂无产品路径组。请先进入产品路径设置新增、导入或指定默认路径组。</div>';
        } else {
            for (var si = 0; si < selections.length; si++) {
                var selection = selections[si];
                var selectionId = _selectionId(selection);
                var label = _selectionDisplayLabel(selection) || ('产品路径 #' + selectionId);
                var paths = selection.selected_paths || selection.paths || [];
                var subMeta = _selectionSourceLabel(selection) || (paths.length + ' 路径');
                var isActive = !!currentSelectionId && selectionId === currentSelectionId;
                html += '<button type="button" class="edit-product-path-selection-nav-btn" data-selection-id="' + escapeHTML(selectionId) + '"'
                    + ' style="width:100%;display:flex;align-items:center;justify-content:space-between;gap:8px;'
                    + 'border:1px solid ' + (isActive ? '#9cc7f2' : 'transparent') + ';'
                    + 'background:' + (isActive ? '#e7f1ff' : 'transparent') + ';'
                    + 'border-radius:6px;padding:7px 8px;margin-bottom:4px;'
                    + 'text-align:left;cursor:pointer;font-size:12px;color:#1f2937;">'
                    + '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escapeHTML(label) + '</span>'
                    + '<small style="color:#667085;font-size:11px;">' + escapeHTML(subMeta) + '</small>'
                    + '</button>';
            }
        }
        html += '</div>';

        html += '<div style="border:1px solid #e5e7eb;border-radius:8px;background:#fff;padding:12px;">';
        html += '<div style="font-size:12px;font-weight:700;color:#475467;margin-bottom:10px;">分组参数' + (isSingle && !derivedSelectedCount ? '' : ' · 将修改 ' + groups.length + ' 个基础组') + '</div>';
        html += '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">';
        html += '<span style="font-size:13px;color:#333;">分组数</span>';
        html += '<input type="number" id="edit-group-count" value="' + splitCount + '" min="1" step="1"'
            + ' style="width:78px;padding:5px 8px;border:1px solid #d0d5dd;border-radius:4px;font-size:13px;text-align:center;"'
            + ' title="分组数量">';
        html += '<span style="font-size:13px;color:#555;">组</span>';
        if (isSingle) {
            html += '<span style="font-size:13px;color:#98a2b3;">/</span>';
            html += '<span style="font-size:13px;color:#555;">分组序号</span>';
            html += '<input type="number" id="edit-group-index" value="' + groupIndex + '" min="1" step="1"'
                + ' style="width:78px;padding:5px 8px;border:1px solid #d0d5dd;border-radius:4px;font-size:13px;text-align:center;"'
                + ' title="分组序号（从1开始）">';
            html += '<span style="font-size:13px;color:#555;">组</span>';
        } else {
            html += '<span style="font-size:12px;color:#98a2b3;">多选时不批量修改分组序号</span>';
        }
        html += '</div>';
        if (derivedSelectedCount > 0) {
            html += '<div style="margin-top:8px;font-size:12px;color:#64748b;line-height:1.5;">已同时选中 ' + derivedSelectedCount + ' 个派生组；结构修改会通过其所属基础组应用到派生子树。</div>';
        }

        html += '<div style="border-top:1px solid #eef2f7;margin:12px 0;"></div>';
        html += '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">';
        html += '<div style="font-size:13px;font-weight:600;color:#333;">选择因子 <span style="color:red;">*</span></div>';
        html += '<span style="font-size:11px;color:#667085;">单组选中修改一次只对应一个因子</span>';
        html += '</div>';
        html += '<div style="max-height:340px;overflow:auto;border:1px solid #e8eaed;border-radius:6px;">';
        if (factors.length === 0) {
            html += '<div style="color:#888;font-size:12px;padding:16px;text-align:center;">暂无因子数据</div>';
        } else {
            for (var fi = 0; fi < factors.length; fi++) {
                var alias = factors[fi].alias || factors[fi].name || '';
                var isSelected = !!factorAlias && alias === factorAlias;
                html += '<div class="edit-factor-row" data-factor-alias="' + escapeHTML(alias) + '"'
                    + ' style="display:flex;align-items:center;gap:8px;padding:7px 10px;cursor:pointer;'
                    + (isSelected ? 'background:#e8f4fd;' : '')
                    + 'border-bottom:1px solid #f0f2f5;font-size:13px;">';
                html += '<input type="radio" name="edit-factor-radio" class="edit-factor-radio" data-factor-alias="' + escapeHTML(alias) + '"'
                    + (isSelected ? ' checked' : '')
                    + ' style="width:15px;height:15px;cursor:pointer;flex-shrink:0;">';
                html += '<span style="flex:1;">' + escapeHTML(alias) + '</span>';
                html += '<span style="font-size:11px;color:' + (isSelected ? '#0078d4' : '#ccc') + ';">' + (isSelected ? '✓' : '') + '</span>';
                html += '</div>';
            }
        }
        html += '</div>';
        html += '</div>';
        html += '</div>';

        container.innerHTML = html;

        function applyEditPatch(rawPatch) {
            try {
                var structurePatchKeys = {
                    product_path_selection: rawPatch.product_path_selection !== undefined,
                    factorAlias: rawPatch.factorAlias !== undefined,
                    splitCount: rawPatch.splitCount !== undefined,
                    groupIndex: rawPatch.groupIndex !== undefined && isSingle,
                };
                for (var gi = 0; gi < groups.length; gi++) {
                    var target = GT.groupSettings.groups.get(groups[gi].id) || groups[gi];
                    var nextSelection = rawPatch.product_path_selection !== undefined ? rawPatch.product_path_selection : target.product_path_selection;
                    var nextFactor = rawPatch.factorAlias !== undefined ? rawPatch.factorAlias : target.factorAlias;
                    var nextSplit = rawPatch.splitCount !== undefined ? Number(rawPatch.splitCount) : Number(target.splitCount || 1);
                    var nextIndex = (rawPatch.groupIndex !== undefined && isSingle) ? Number(rawPatch.groupIndex) : Number(target.groupIndex || 1);
                    if (!nextSplit || nextSplit < 1) nextSplit = 1;
                    if (!nextIndex || nextIndex < 1) nextIndex = 1;
                    if (nextIndex > nextSplit) nextSplit = nextIndex;
                    var names = _makeEditNames(target.id, nextSelection, nextFactor, nextSplit, nextIndex);
                    GT.groupSettings.groups.update(target.id, {
                        product_path_selection: nextSelection,
                        factorAlias: nextFactor,
                        splitCount: nextSplit,
                        groupIndex: nextIndex,
                        name: names.name,
                        shortAlias: names.shortAlias,
                        needsRegenerate: true,
                    });
                    var descendants = GT.groupSettings.groups.getDescendants
                        ? GT.groupSettings.groups.getDescendants(target.id)
                        : [];
                    for (var di = 0; di < descendants.length; di++) {
                        if (descendants[di] === target.id) continue;
                        var childPatch = { needsRegenerate: true };
                        if (structurePatchKeys.product_path_selection) childPatch.product_path_selection = nextSelection;
                        if (structurePatchKeys.factorAlias) childPatch.factorAlias = nextFactor;
                        if (structurePatchKeys.splitCount) childPatch.splitCount = nextSplit;
                        if (structurePatchKeys.groupIndex) childPatch.groupIndex = nextIndex;
                        childPatch.shortAlias = '';
                        childPatch.name = '';
                        GT.groupSettings.groups.update(descendants[di], childPatch);
                    }
                }
                if (GT.groupSettings.addGroupBatch && GT.groupSettings.addGroupBatch.rebuildFromGroups) {
                    GT.groupSettings.addGroupBatch.rebuildFromGroups();
                } else if (GT.groupSettings.addGroupBatch && GT.groupSettings.addGroupBatch.ensure) {
                    var latest = GT.groupSettings.groups.get(groups[0].id) || groups[0];
                    GT.groupSettings.addGroupBatch.ensure(_selectionId(latest.product_path_selection), latest.factorAlias, latest.splitCount);
                }
                _renderEditGroup(container);
            } catch (error) {
                alert('修改失败: ' + error.message);
            }
        }

        container.querySelectorAll('.edit-product-path-selection-nav-btn').forEach(function(button) {
            button.addEventListener('click', function() {
                var selectionId = this.getAttribute('data-selection-id');
                applyEditPatch({ product_path_selection: _findSelection(selectionId) });
            });
        });
        var managePathsBtn = $('edit-manage-product-paths');
        if (managePathsBtn) {
            managePathsBtn.addEventListener('click', function() {
                if (GT.backendSettings && typeof GT.backendSettings.openLocalTab === 'function') {
                    GT.backendSettings.openLocalTab('product_path_selection');
                }
            });
        }

        var input = $('edit-group-count');
        if (input) {
            input.addEventListener('blur', function() {
                var value = parseInt(this.value, 10);
                if (isNaN(value) || value < 1) value = 1;
                applyEditPatch({ splitCount: value });
            });
            input.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') this.blur();
            });
        }
        var indexInput = $('edit-group-index');
        if (indexInput) {
            indexInput.addEventListener('blur', function() {
                var value = parseInt(this.value, 10);
                if (isNaN(value) || value < 1) value = 1;
                applyEditPatch({ groupIndex: value });
            });
            indexInput.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') this.blur();
            });
        }
        container.querySelectorAll('.edit-factor-row').forEach(function(row) {
            row.addEventListener('click', function(e) {
                var alias = this.getAttribute('data-factor-alias');
                if (!alias) return;
                applyEditPatch({ factorAlias: alias });
            });
        });
        container.querySelectorAll('.edit-factor-radio').forEach(function(radio) {
            radio.addEventListener('change', function() {
                var alias = this.getAttribute('data-factor-alias');
                if (!alias) return;
                applyEditPatch({ factorAlias: alias });
            });
        });
    }

    var _editMounted = false;
    function mountEdit() {
        _editMounted = true;
        var container = $('edit-group');
        if (!container) return;
        _renderEditGroup(container);
        if (GT.backendSettings && typeof GT.backendSettings.loadProductPathSelections === 'function') {
            GT.backendSettings.loadProductPathSelections().then(function() {
                if (_editMounted) _renderEditGroup(container);
            }).catch(function(error) {
                console.error('[group edit] load product paths failed:', error);
            });
        }
    }
    function unmountEdit() { _editMounted = false; }
    function refreshEdit() {
        if (_editMounted) {
            var container = $('edit-group');
            if (container) _renderEditGroup(container);
        }
    }

    GT.panels.edit = GT.panels.edit || {};
    GT.panels.edit.group = {
        mount: mountEdit,
        unmount: unmountEdit,
        refresh: refreshEdit,
        render: refreshEdit,
    };

    // ── Register add flow to GT.modes ──
    if (GT.modes) {
        GT.modes.registerAddFlow({
            flow: 'group',
            priority: 0,
            condition: function() { return true; },
            buildDraft: function() {
                var local = GT.backendSettings && GT.backendSettings._state && GT.backendSettings._state.localValues
                    ? GT.backendSettings._state.localValues.product_path_selection
                    : null;
                return {
                    addFlow: 'group',
                    product_path_selection: local || null,
                    splitCount: 5,
                    allGroups: true,
                    groupIndex: 1,
                    selectedFactors: [],
                };
            },
            onSubmit: function(draft, helpers) {
                submitAddBatches(draft);
                helpers.exitAdd();
            },
            defaultTab: 'add-group'
        });
    }

    document.addEventListener('groupTestProductPathSelectionsChanged', function() {
        var draft = GT.tabs && GT.tabs.getAddDraft ? GT.tabs.getAddDraft() : null;
        if (draft && draft.addFlow === 'group' && !draft.product_path_selection) {
            var local = GT.backendSettings && GT.backendSettings._state && GT.backendSettings._state.localValues
                ? GT.backendSettings._state.localValues.product_path_selection
                : null;
            if (local) GT.tabs.updateAddDraft({ product_path_selection: local });
        }
        if (_mounted) render();
    });

    GT.log('panels.add.group loaded');
})();
