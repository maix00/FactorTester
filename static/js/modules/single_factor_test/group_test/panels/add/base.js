/**
 * panels/add/base.js — Add-flow panel: "新建基础组" (category-2)
 *
 * Renders tester selector → groupIndex/groupCount (side-by-side) → allGroups
 * checkbox → factor selector → submit handled by app.js
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.add) { GT.panels.add = {}; }

    var _containerId = 'add-base';
    var _mounted = false;

    function $(id) { return document.getElementById(id); }

    function escapeHTML(str) { return GT.escapeHTML(str); }

    // ── Delegated utilities ──

    var _batchKey = GT.datamodel.groups.batchKey;

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

    function _preComputeComboLetters(testerId, factorAliases, groupCount) {
        var comboMap = {};
        var existing = GT.datamodel.groups.getAll();
        var subs = window.submissions || [];

        for (var i = 0; i < factorAliases.length; i++) {
            var alias = factorAliases[i];
            var comboKey = _batchKey(testerId, alias, groupCount);
            if (comboMap[comboKey] !== undefined) continue;

            // Check existing groups for this combo
            var hasExisting = false;
            for (var j = 0; j < existing.length; j++) {
                var k = _batchKey(existing[j].testerId, existing[j].factorAlias, existing[j].groupCount);
                if (k === comboKey) { hasExisting = true; break; }
            }
            if (hasExisting) {
                for (var ej = 0; ej < existing.length; ej++) {
                    var ek = _batchKey(existing[ej].testerId, existing[ej].factorAlias, existing[ej].groupCount);
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
                    var ek2 = _batchKey(existing[ej2].testerId, existing[ej2].factorAlias, existing[ej2].groupCount);
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

    function _makeNames(testerId, factorAlias, groupCount, groupIndex, letter) {
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
        var shortAlias = letter + groupIndex;

        var allGroups = GT.datamodel.groups.getAll();
        var comboKey = String(testerId) + '|' + factorAlias + '|' + groupCount;
        var sameIndexCount = 0;
        var usedSuffixes = {};
        for (var ai = 0; ai < allGroups.length; ai++) {
            var g = allGroups[ai];
            var gk = String(g.testerId) + '|' + g.factorAlias + '|' + g.groupCount;
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

    // ── Render ──
    //
    // Master-inspired two-column layout:
    //   Left column  — tester navigation (vertical buttons, like .group-nav-column)
    //   Right column — group params + multi-select factor list

    function render() {
        var container = $(_containerId);
        if (!container) return;

        var subs = window.submissions || [];
        var factors = window.factorList || [];
        var draft = GT.ui.getAddDraft();
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
        html += '<div style="font-size:12px;font-weight:700;color:#475467;padding:4px 6px 8px;">产品组 / 测试器</div>';
        if (subs.length === 0) {
            html += '<div style="color:#888;font-size:12px;padding:8px;">暂无提交记录</div>';
        } else {
            for (var i = 0; i < subs.length; i++) {
                var sub = subs[i];
                var subId = String(sub.id);
                var isPg = !!sub.product_group;
                var label = isPg ? (sub.product_group || sub.label) : (sub.label || ('测试器 #' + subId));
                var subMeta = isPg ? '产品组' : (sub.factor_tester_serial || 'FactorTester');
                var isActive = (String(draft.testerId) === subId);
                html += '<button type="button" class="add-tester-nav-btn" data-tester-id="' + escapeHTML(subId) + '"'
                    + ' style="width:100%;display:flex;align-items:center;justify-content:space-between;gap:8px;'
                    + 'border:1px solid ' + (isActive ? '#9cc7f2' : 'transparent') + ';'
                    + 'background:' + (isActive ? '#e7f1ff' : 'transparent') + ';'
                    + 'border-radius:6px;padding:7px 8px;margin-bottom:4px;'
                    + 'text-align:left;cursor:pointer;font-size:12px;color:#1f2937;">'
                    + '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + (isPg ? '📦 ' : '') + escapeHTML(label) + '</span>'
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
        html += '<input type="number" id="add-group-count" value="' + (draft.groupCount || 5) + '" min="1" step="1"'
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
        if (draft.testerId) {
            var testerLabel = '';
            for (var ti = 0; ti < subs.length; ti++) {
                if (String(subs[ti].id) === String(draft.testerId)) {
                    testerLabel = subs[ti].product_group || subs[ti].label || ('测试器 #' + draft.testerId);
                    break;
                }
            }
            html += '<div style="margin-bottom:12px;padding:8px 12px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:4px;font-size:12px;color:#0369a1;">';
            html += '已选：<b>' + escapeHTML(testerLabel || draft.testerId) + '</b> · ' + (draft.groupCount || 5) + '组';
            if (draft.allGroups) html += ' · 所有分组';
            else html += ' · 第 <b>' + (draft.groupIndex || 1) + '</b> 组';
            html += '</div>';
        } else {
            html += '<div style="margin-bottom:12px;padding:8px 12px;background:#fff7ed;border:1px solid #fed7aa;border-radius:4px;font-size:12px;color:#c2410c;">';
            html += '⚠️ 请先在左侧选择测试器';
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

        // Tester nav buttons
        var testerBtns = container.querySelectorAll('.add-tester-nav-btn');
        for (var tb = 0; tb < testerBtns.length; tb++) {
            testerBtns[tb].addEventListener('click', function() {
                var tid = this.getAttribute('data-tester-id');
                GT.ui.updateAddDraft({ testerId: tid });
                render();
            });
        }

        // Group count
        var gcInput = $('add-group-count');
        if (gcInput) {
            gcInput.addEventListener('input', function() {
                var v = parseInt(this.value, 10);
                if (v >= 1) GT.ui.updateAddDraft({ groupCount: v });
            });
            gcInput.addEventListener('blur', function() {
                var v = parseInt(this.value, 10);
                if (isNaN(v) || v < 1) { this.value = 2; GT.ui.updateAddDraft({ groupCount: 2 }); }
            });
        }

        // Group index
        var giInput = $('add-group-index');
        if (giInput) {
            giInput.addEventListener('input', function() {
                var v = parseInt(this.value, 10);
                if (v >= 1) GT.ui.updateAddDraft({ groupIndex: v });
            });
        }

        // All groups checkbox
        var agCheck = $('add-all-groups');
        if (agCheck) {
            agCheck.addEventListener('change', function() {
                GT.ui.updateAddDraft({ allGroups: this.checked });
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
                GT.ui.updateAddDraft({ selectedFactors: allAliases });
                render();
            });
        }

        // Deselect all
        var deselectAllBtn = $('add-deselect-all');
        if (deselectAllBtn) {
            deselectAllBtn.addEventListener('click', function() {
                GT.ui.updateAddDraft({ selectedFactors: [] });
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
        GT.ui.updateAddDraft({ selectedFactors: selected });
        render();
    }

    // ── Submit ──

    function submitAddBatches(draft) {
        if (!draft || !draft.testerId) { alert('请先选择测试器'); return; }
        var testerId = draft.testerId;
        var groupCount = draft.groupCount;
        var allGroups = draft.allGroups;
        var groupIndex = draft.groupIndex;
        var factors = draft.selectedFactors || [];

        if (factors.length === 0) { alert('请至少选择一个因子'); return; }

        var comboLetters = _preComputeComboLetters(testerId, factors, groupCount);

        var added = 0;

        // Resolve tester label once for batch naming
        var subs = window.submissions || [];
        var testerLabel = '';
        for (var si = 0; si < subs.length; si++) {
            if (String(subs[si].id) === String(testerId)) {
                testerLabel = subs[si].product_group || subs[si].label || ('测试器' + testerId);
                break;
            }
        }
        if (!testerLabel) testerLabel = '测试器' + testerId;

        for (var fi = 0; fi < factors.length; fi++) {
            var alias = factors[fi];
            var comboKey = _batchKey(testerId, alias, groupCount);
            var letter = comboLetters[comboKey] || 'A';

            var REG = window.GT_CONFIG_REGISTRY;
            var feeMode = (REG && REG.hasDirty()) ? REG.getDirty('feeMode', draft.feeMode || 'none') : (draft.feeMode || 'none');
            // Read dirty workspace for feeMap (populated by overlay's "写入暂存")
            var dirtyFeeMap = (REG && REG.hasDirty()) ? REG.getDirty('feeMap') : null;
            var feeMap = null;
            if (feeMode === 'per_product' || feeMode === 'custom') {
                feeMap = (dirtyFeeMap && Object.keys(dirtyFeeMap).length > 0) ? dirtyFeeMap : null;
            }
            var feeRate = (REG && REG.hasDirty()) ? REG.getDirty('feeRate', draft.feeRate) : draft.feeRate;
            var feeSensitivity = (REG && REG.hasDirty()) ? REG.getDirty('feeSensitivity', draft.feeSensitivity) : draft.feeSensitivity;
            var useCloseToday = (REG && REG.hasDirty()) ? REG.getDirty('useCloseToday', draft.useCloseToday) : draft.useCloseToday;
            if (allGroups) {
                for (var gi = 1; gi <= groupCount; gi++) {
                    var names = _makeNames(testerId, alias, groupCount, gi, letter);
                    try {
                        GT.datamodel.groups.add({
                            name: names.name,
                            shortAlias: names.shortAlias,
                            testerId: testerId,
                            factorAlias: alias,
                            groupCount: groupCount,
                            groupIndex: gi,
                            isAllGroups: false,
                            feeMode: feeMode,
                            feeRate: feeRate,
                            feeMap: feeMap,
                            feeSensitivity: feeSensitivity,
                            useCloseToday: useCloseToday,
                            rebalanceMode: draft.rebalanceMode || 'each_period',
                        });
                        added++;
                    } catch (err) { /* skip dup */ }
                }
            } else {
                var names2 = _makeNames(testerId, alias, groupCount, groupIndex, letter);
                try {
                    GT.datamodel.groups.add({
                        name: names2.name,
                        shortAlias: names2.shortAlias,
                        testerId: testerId,
                        factorAlias: alias,
                        groupCount: groupCount,
                        groupIndex: groupIndex,
                        isAllGroups: false,
                        feeMode: feeMode,
                        feeRate: feeRate,
                        feeMap: feeMap,
                        feeSensitivity: feeSensitivity,
                        useCloseToday: useCloseToday,
                        rebalanceMode: draft.rebalanceMode || 'each_period',
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
    }

    function unmount() {
        _mounted = false;
    }

    function refresh() {
        if (_mounted) render();
    }

    // ── Export ──

    GT.panels.add = GT.panels.add || {};
    GT.panels.add.base = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
        submitAddBatches: submitAddBatches,
    };

    GT.log('panels.base.add loaded');
})();
