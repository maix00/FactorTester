/**
 * panels/base/add_factors.js — Add-flow sub-tab: "因子选择"
 *
 * Renders a row-based factor list (master-branch style) for multi-select.
 * Each selected factor = one batch. State is stored in GT.ui.getAddDraft()
 * / GT.ui.updateAddDraft().
 * Also provides a "添加全部因子" shortcut button and a submit action.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.base) { GT.panels.base = {}; }

    var _containerId = 'base-add-factors';
    var _mounted = false;

    function $(id) { return document.getElementById(id); }

    function escapeHTML(str) {
        if (str === null || str === undefined) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    /** Build a batch key from (testerId, factorAlias, groupCount) */
    function _batchKey(testerId, factorAlias, groupCount) {
        return String(testerId) + '|' + factorAlias + '|' + groupCount;
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

    /** Pre-compute the next letter for each combo across existing groups */
    function _preComputeComboLetters(testerId, factorAliases, groupCount) {
        var comboMap = {};
        var existing = GT.datamodel.base_groups.getAll();

        for (var i = 0; i < factorAliases.length; i++) {
            var alias = factorAliases[i];
            var comboKey = _batchKey(testerId, alias, groupCount);
            if (comboMap[comboKey] !== undefined) continue;

            var comboCount = 0;
            for (var j = 0; j < existing.length; j++) {
                var k = _batchKey(existing[j].testerId, existing[j].factorAlias, existing[j].groupCount);
                if (k === comboKey) comboCount++;
            }
            comboCount += Object.keys(comboMap).filter(function(key) { return key === comboKey; }).length;
            comboMap[comboKey] = _colLetter(comboCount + 1);
        }
        return comboMap;
    }

    /** Generate default name & short alias */
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
        return { name: fullName, shortAlias: shortAlias };
    }

    function render() {
        var container = $(_containerId);
        if (!container) return;

        var factors = window.factorList || [];
        var draft = GT.ui.getAddDraft();
        if (!draft) return;

        var html = '';

        // ── Info banner ──
        if (draft.testerId) {
            html += '<div style="margin-bottom:16px;padding:8px 12px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:4px;font-size:12px;color:#0369a1;">';
            html += '测试器已选 · 分组数: <b>' + (draft.groupCount || 2) + '</b>';
            if (draft.allGroups) {
                html += ' · 所有分组';
            } else {
                html += ' · 仅第 <b>' + (draft.groupIndex || 1) + '</b> 组';
            }
            html += '</div>';
        } else {
            html += '<div style="margin-bottom:16px;padding:8px 12px;background:#fff7ed;border:1px solid #fed7aa;border-radius:4px;font-size:12px;color:#c2410c;">';
            html += '⚠️ 请先在"测试器与分组数"中选择测试器';
            html += '</div>';
        }

        // ── "添加全部因子" button ──
        html += '<div style="margin-bottom:16px;">';
        html += '<button id="af-select-all" style="padding:8px 16px;border:none;border-radius:4px;background:#10b981;color:#fff;cursor:pointer;font-size:13px;font-weight:600;">＋ 全选所有因子</button>';
        html += '<button id="af-deselect-all" style="margin-left:8px;padding:8px 16px;border:1px solid #d0d5dd;border-radius:4px;background:#fff;cursor:pointer;font-size:13px;">清空选择</button>';
        html += '</div>';

        // ── Factor list (row-based) ──
        html += '<div style="margin-bottom:16px;">';
        html += '<div style="font-size:13px;font-weight:600;margin-bottom:8px;color:#333;">选择因子 <span style="color:red;">*</span></div>';
        if (factors.length === 0) {
            html += '<div style="color:#888;font-size:12px;padding:8px;">暂无因子数据</div>';
        } else {
            html += '<table style="width:100%;border-collapse:collapse;font-size:13px;">';
            html += '<thead><tr style="background:#f6f8fa;border-bottom:1px solid #d0d5dd;">';
            html += '<th style="padding:6px 10px;text-align:left;width:40px;"></th>';
            html += '<th style="padding:6px 10px;text-align:left;">因子别名</th>';
            html += '<th style="padding:6px 10px;text-align:right;">已选</th>';
            html += '</tr></thead><tbody>';
            for (var j = 0; j < factors.length; j++) {
                var alias = factors[j].alias || factors[j].name || '';
                var isSelected = (draft.selectedFactors || []).indexOf(alias) >= 0;
                var rowStyle = isSelected ? 'background:#e8f4fd;' : '';
                html += '<tr class="af-factor-row" data-factor-alias="' + escapeHTML(alias) + '"'
                    + ' style="cursor:pointer;border-bottom:1px solid #e8eaed;' + rowStyle + '">';
                html += '<td style="padding:6px 10px;">';
                html += '<span style="display:inline-block;width:16px;height:16px;border-radius:3px;border:2px solid ' + (isSelected ? '#0078d4' : '#ccc') + ';background:' + (isSelected ? '#0078d4' : '#fff') + ';vertical-align:middle;"></span>';
                html += '</td>';
                html += '<td style="padding:6px 10px;">' + escapeHTML(alias) + '</td>';
                html += '<td style="padding:6px 10px;text-align:right;font-size:11px;color:' + (isSelected ? '#0078d4' : '#ccc') + ';">' + (isSelected ? '✓' : '—') + '</td>';
                html += '</tr>';
            }
            html += '</tbody></table>';
        }
        html += '</div>';

        container.innerHTML = html;

        // ── Bind events ──
        var factorRows = container.querySelectorAll('.af-factor-row');
        for (var fi = 0; fi < factorRows.length; fi++) {
            factorRows[fi].addEventListener('click', function() {
                var alias = this.getAttribute('data-factor-alias');
                var selected = (draft.selectedFactors || []).slice();
                var idx = selected.indexOf(alias);
                if (idx >= 0) {
                    selected.splice(idx, 1);
                } else {
                    selected.push(alias);
                }
                GT.ui.updateAddDraft({ selectedFactors: selected });
                render();
            });
        }

        var selectAllBtn = $('af-select-all');
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

        var deselectAllBtn = $('af-deselect-all');
        if (deselectAllBtn) {
            deselectAllBtn.addEventListener('click', function() {
                GT.ui.updateAddDraft({ selectedFactors: [] });
                render();
            });
        }
    }

    /** Execute batch add — called from app.js when user clicks "提交基础组" */
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
        for (var fi = 0; fi < factors.length; fi++) {
            var alias = factors[fi];
            var comboKey = _batchKey(testerId, alias, groupCount);
            var letter = comboLetters[comboKey] || 'A';

            if (allGroups) {
                for (var gi = 1; gi <= groupCount; gi++) {
                    var names = _makeNames(testerId, alias, groupCount, gi, letter);
                    try {
                        GT.datamodel.base_groups.add({
                            name: names.name,
                            shortAlias: names.shortAlias,
                            testerId: testerId,
                            factorAlias: alias,
                            groupCount: groupCount,
                            groupIndex: gi,
                            isAllGroups: false,
                        });
                        added++;
                    } catch (err) { /* skip dup */ }
                }
            } else {
                var names2 = _makeNames(testerId, alias, groupCount, groupIndex, letter);
                try {
                    GT.datamodel.base_groups.add({
                        name: names2.name,
                        shortAlias: names2.shortAlias,
                        testerId: testerId,
                        factorAlias: alias,
                        groupCount: groupCount,
                        groupIndex: groupIndex,
                        isAllGroups: false,
                    });
                    added++;
                } catch (err) { /* skip dup */ }
            }
        }
        return { added: added };
    }

    function mount() {
        _mounted = true;
        var container = $(_containerId);
        if (!container) {
            GT.log('panels.base.add_factors: container #' + _containerId + ' not found');
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

    GT.panels.base.add_factors = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
        submitAddBatches: submitAddBatches,
    };

    GT.log('panels.base.add_factors loaded');
})();
