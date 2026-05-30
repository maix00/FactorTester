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
    var _modalId = 'base-group-form-modal';
    var _formId = 'base-group-form';

    // Track whether panel is currently mounted (sub-tab visible)
    var _mounted = false;

    // Cache current active ID for highlight tracking
    var _activeId = null;

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
    // Modal management
    // ---------------------------------------------------------------------------

    /** Track state during Add modal (not used in Edit mode) */
    var _addState = null;  // { step:1|2, testerId, groupCount, selectedFactors:[alias], allGroups:bool, groupIndex }

    function _showModal(editData) {
        var existing = $(_modalId);
        if (existing) { existing.remove(); }

        var isEdit = !!editData;
        _addState = null;

        var title = isEdit ? '编辑基础组' : '新增基础组';
        var modalBody = isEdit ? _buildEditForm(editData) : _buildAddForm();

        var html = '<div id="' + _modalId + '" style="position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);display:flex;align-items:flex-start;justify-content:center;z-index:10000;overflow-y:auto;padding:40px 0;">';
        html += '<div style="background:#fff;border-radius:8px;padding:24px;min-width:520px;max-width:700px;box-shadow:0 8px 32px rgba(0,0,0,0.2);">';
        html += '<h3 style="margin:0 0 16px 0;">' + title + '</h3>';
        html += '<form id="' + _formId + '" onsubmit="return false;">';
        html += modalBody;
        html += '</form></div></div>';

        document.body.insertAdjacentHTML('beforeend', html);

        // Store editing ID
        $(_modalId)._editId = isEdit ? editData.id : null;

        // Bind cancel
        $('bgf-cancel').addEventListener('click', _closeModal);

        // Bind backdrop click
        $(_modalId).addEventListener('click', function(e) {
            if (e.target === this) _closeModal();
        });

        if (isEdit) {
            $(_formId).addEventListener('submit', _handleEditSubmit);
        } else {
            _initAddStep1();
        }
    }

    // ── Edit form (simplified, allows overriding name/fields) ──

    function _buildEditForm(editData) {
        var subs = window.submissions || [];

        var html = '';
        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">名称</span>';
        html += '<input type="text" id="bgf_name" value="' + escapeHTML(editData.name || '') + '" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;">';
        html += '</label>';

        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">测试器</span>';
        html += '<select id="bgf_testerId" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;">';
        for (var i = 0; i < subs.length; i++) {
            var subId = String(subs[i].id);
            var isPg = !!subs[i].product_group;
            var subLabel = isPg ? ('📦 ' + (subs[i].product_group || subs[i].label)) : (subs[i].label || ('测试器 #' + subId));
            var sel = (String(editData.testerId) === subId) ? ' selected' : '';
            html += '<option value="' + escapeHTML(subId) + '"' + sel + '>' + escapeHTML(subLabel) + '</option>';
        }
        html += '</select>';
        html += '</label>';

        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">因子别名</span>';
        html += '<input type="text" id="bgf_factorAlias" value="' + escapeHTML(editData.factorAlias || '') + '" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;">';
        html += '</label>';

        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">分组数</span>';
        html += '<input type="number" id="bgf_groupCount" value="' + (editData.groupCount || 2) + '" min="1" step="1" style="width:80px;padding:6px;border:1px solid #ddd;border-radius:4px;">';
        html += '</label>';

        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">分组索引 (1-based)</span>';
        html += '<input type="number" id="bgf_groupIndex" value="' + (editData.groupIndex || 1) + '" min="1" step="1" style="width:80px;padding:6px;border:1px solid #ddd;border-radius:4px;">';
        html += '</label>';

        html += '<label style="display:block;margin-bottom:16px;">';
        html += '<input type="checkbox" id="bgf_isAllGroups" ' + (editData.isAllGroups ? 'checked' : '') + '>';
        html += '<span style="font-size:13px;margin-left:4px;">所有分组</span>';
        html += '</label>';

        html += '<div style="display:flex;gap:8px;justify-content:flex-end;">';
        html += '<button type="button" id="bgf-cancel" style="padding:6px 16px;border:1px solid #ddd;border-radius:4px;background:#f6f8fa;cursor:pointer;">取消</button>';
        html += '<button type="submit" id="bgf-save" style="padding:6px 16px;border:none;border-radius:4px;background:#0078d4;color:#fff;cursor:pointer;">保存</button>';
        html += '</div>';

        return html;
    }

    function _handleEditSubmit(e) {
        e.preventDefault();
        var editId = $(_modalId)._editId;
        var data = {
            name: $('bgf_name').value.trim(),
            testerId: $('bgf_testerId').value,
            factorAlias: $('bgf_factorAlias').value.trim(),
            groupCount: parseInt($('bgf_groupCount').value, 10) || 2,
            groupIndex: parseInt($('bgf_groupIndex').value, 10) || 1,
            isAllGroups: $('bgf_isAllGroups').checked,
        };
        try {
            if (editId) {
                GT.datamodel.base_groups.update(editId, data);
            }
            _closeModal();
        } catch (err) {
            alert('操作失败: ' + err.message);
        }
    }

    // ── Add form (step-based) ──

    function _buildAddForm() {
        // Container with id=bgf-add-body that gets rebuilt on step transitions
        var html = '<div id="bgf-add-body"></div>';
        html += '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;">';
        html += '<button type="button" id="bgf-cancel" style="padding:6px 16px;border:1px solid #ddd;border-radius:4px;background:#f6f8fa;cursor:pointer;">取消</button>';
        html += '</div>';
        return html;
    }

    /** Step 1: pick tester (printed list, not dropdown) + group count */
    function _initAddStep1() {
        _addState = { step: 1, testerId: null, groupCount: 2, selectedFactors: [], allGroups: false, groupIndex: 1 };
        var body = $('bgf-add-body');
        if (!body) return;

        var subs = window.submissions || [];
        var html = '';

        // Tester list
        html += '<div style="margin-bottom:16px;">';
        html += '<div style="font-size:13px;font-weight:600;margin-bottom:8px;color:#333;">选择测试器 <span style="color:red;">*</span></div>';
        if (subs.length === 0) {
            html += '<div style="color:#888;font-size:12px;">暂无提交记录，请先在产品类别筛选模块提交产品。</div>';
        } else {
            html += '<div id="bgf-tester-list" style="display:flex;flex-wrap:wrap;gap:6px;">';
            for (var i = 0; i < subs.length; i++) {
                var sub = subs[i];
                var subId = String(sub.id);
                var isPg = !!sub.product_group;
                var icon = isPg ? '📦 ' : '📁 ';
                var label = isPg ? (sub.product_group || sub.label) : (sub.label || ('测试器 #' + subId));
                var tag = isPg ? '<span style="font-size:10px;background:#dbeafe;color:#1d4ed8;padding:1px 4px;border-radius:3px;margin-left:4px;">产品组</span>'
                    : '<span style="font-size:10px;background:#fef3c7;color:#b45309;padding:1px 4px;border-radius:3px;margin-left:4px;">路径组</span>';
                html += '<button type="button" class="bgf-tester-card" data-tester-id="' + escapeHTML(subId) + '"'
                    + ' style="padding:8px 12px;border:1px solid #d0d5dd;border-radius:6px;background:#fff;cursor:pointer;font-size:13px;text-align:left;transition:all 0.15s;">'
                    + icon + escapeHTML(label) + tag
                    + '<br><span style="font-size:11px;color:#888;">ID:' + escapeHTML(subId) + '</span>'
                    + '</button>';
            }
            html += '</div>';
        }
        html += '</div>';

        // Group count
        html += '<div style="margin-bottom:16px;">';
        html += '<div style="font-size:13px;font-weight:600;margin-bottom:4px;color:#333;">分组数 <span style="color:red;">*</span></div>';
        html += '<input type="number" id="bgf_groupCount" value="2" min="1" step="1" style="width:100px;padding:6px;border:1px solid #ddd;border-radius:4px;">';
        html += '<div style="font-size:11px;color:#888;margin-top:2px;">大于等于 1 的整数</div>';
        html += '</div>';

        // Batch add button
        html += '<div style="margin-bottom:16px;">';
        html += '<button type="button" id="bgf-batch-add" style="padding:8px 16px;border:none;border-radius:4px;background:#10b981;color:#fff;cursor:pointer;font-size:13px;font-weight:600;">＋ 添加全部因子分组组合</button>';
        html += '</div>';

        // Divider
        html += '<div style="border-top:1px solid #e5e7eb;margin:16px 0;position:relative;">';
        html += '<span style="position:absolute;top:-10px;left:50%;transform:translateX(-50%);background:#fff;padding:0 8px;font-size:11px;color:#888;">或单独选择</span>';
        html += '</div>';

        // Factor list
        html += '<div style="margin-bottom:16px;">';
        html += '<div style="font-size:13px;font-weight:600;margin-bottom:8px;color:#333;">选择因子 <span style="color:red;">*</span></div>';
        var factors = window.factorList || [];
        if (factors.length === 0) {
            html += '<div style="color:#888;font-size:12px;">暂无因子数据</div>';
        } else {
            html += '<div id="bgf-factor-list" style="display:flex;flex-wrap:wrap;gap:6px;">';
            for (var j = 0; j < factors.length; j++) {
                var alias = factors[j].alias || factors[j].name || '';
                html += '<button type="button" class="bgf-factor-card" data-factor-alias="' + escapeHTML(alias) + '"'
                    + ' style="padding:6px 12px;border:1px solid #d0d5dd;border-radius:4px;background:#fff;cursor:pointer;font-size:12px;transition:all 0.15s;">'
                    + escapeHTML(alias) + '</button>';
            }
            html += '</div>';
        }
        html += '</div>';

        // Group index + "所有分组" checkbox on the right
        html += '<div style="margin-bottom:16px;">';
        html += '<div style="font-size:13px;font-weight:600;margin-bottom:8px;color:#333;">分组索引 (从1开始)</div>';
        html += '<div style="display:flex;align-items:center;gap:12px;">';
        html += '<input type="number" id="bgf_groupIndex" value="1" min="1" step="1" style="width:100px;padding:6px;border:1px solid #ddd;border-radius:4px;">';
        html += '<label style="display:flex;align-items:center;gap:4px;cursor:pointer;font-size:13px;white-space:nowrap;">';
        html += '<input type="checkbox" id="bgf_isAllGroups"> <span>所有分组</span>';
        html += '</label>';
        html += '</div>';
        html += '</div>';

        // Single add button
        html += '<div style="text-align:right;">';
        html += '<button type="button" id="bgf-single-add" style="padding:6px 16px;border:none;border-radius:4px;background:#0078d4;color:#fff;cursor:pointer;font-size:13px;">确认添加</button>';
        html += '</div>';

        body.innerHTML = html;

        // ── Bind Step 1 events ──

        // Tester cards
        var testerCards = body.querySelectorAll('.bgf-tester-card');
        for (var ti = 0; ti < testerCards.length; ti++) {
            testerCards[ti].addEventListener('click', function() {
                var tid = this.getAttribute('data-tester-id');
                _addState.testerId = tid;
                // Highlight
                testerCards.forEach(function(c) {
                    c.style.borderColor = '#d0d5dd';
                    c.style.background = '#fff';
                });
                this.style.borderColor = '#0078d4';
                this.style.background = '#e8f4fd';
            });
        }

        // Factor cards
        var factorCards = body.querySelectorAll('.bgf-factor-card');
        for (var fi = 0; fi < factorCards.length; fi++) {
            factorCards[fi].addEventListener('click', function() {
                var alias = this.getAttribute('data-factor-alias');
                var idx = _addState.selectedFactors.indexOf(alias);
                if (idx >= 0) {
                    _addState.selectedFactors.splice(idx, 1);
                    this.style.borderColor = '#d0d5dd';
                    this.style.background = '#fff';
                } else {
                    _addState.selectedFactors.push(alias);
                    this.style.borderColor = '#0078d4';
                    this.style.background = '#e8f4fd';
                }
            });
        }

        // Group count
        var gcEl = $('bgf_groupCount');
        if (gcEl) {
            gcEl.addEventListener('input', function() {
                var v = parseInt(this.value, 10);
                if (v >= 1) _addState.groupCount = v;
            });
        }

        // All groups checkbox → gray out group index
        var allG = $('bgf_isAllGroups');
        var gIdx = $('bgf_groupIndex');
        if (allG && gIdx) {
            allG.addEventListener('change', function() {
                _addState.allGroups = this.checked;
                gIdx.disabled = this.checked;
                gIdx.style.background = this.checked ? '#f0f0f0' : '';
                gIdx.style.color = this.checked ? '#999' : '';
            });
        }

        // Group index
        if (gIdx) {
            gIdx.addEventListener('input', function() {
                var v = parseInt(this.value, 10);
                if (v >= 1) _addState.groupIndex = v;
            });
        }

        // Batch add button
        var batchBtn = $('bgf-batch-add');
        if (batchBtn) {
            batchBtn.addEventListener('click', function() {
                if (!_addState.testerId) { alert('请先选择测试器'); return; }
                var gc = parseInt($('bgf_groupCount').value, 10) || _addState.groupCount;
                if (gc < 1) { alert('分组数必须 ≥ 1'); return; }
                _addState.groupCount = gc;
                _doBatchAdd(_addState.testerId, gc, window.factorList || []);
            });
        }

        // Single add button
        var singleBtn = $('bgf-single-add');
        if (singleBtn) {
            singleBtn.addEventListener('click', function() {
                if (!_addState.testerId) { alert('请先选择测试器'); return; }
                if (_addState.selectedFactors.length === 0) { alert('请至少选择一个因子'); return; }
                var gc = parseInt($('bgf_groupCount').value, 10) || _addState.groupCount;
                if (gc < 1) { alert('分组数必须 ≥ 1'); return; }
                _addState.groupCount = gc;
                _addState.allGroups = $('bgf_isAllGroups').checked;
                _addState.groupIndex = parseInt($('bgf_groupIndex').value, 10) || 1;
                _doSingleAdd();
            });
        }
    }

    /** Batch: add ALL factors × [1..groupCount] for the selected tester */
    function _doBatchAdd(testerId, groupCount, factors) {
        var aliases = [];
        for (var fi = 0; fi < factors.length; fi++) {
            var a = factors[fi].alias || factors[fi].name || '';
            if (a) aliases.push(a);
        }
        var comboLetters = _preComputeComboLetters(testerId, aliases, groupCount);

        var added = 0;
        for (var fi2 = 0; fi2 < aliases.length; fi2++) {
            var alias = aliases[fi2];
            var comboKey = String(testerId) + '|' + alias + '|' + groupCount;
            var letter = comboLetters[comboKey] || 'A';
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
                } catch (err) {
                    // Just skip duplicates
                }
            }
        }
        _closeModal();
        if (added === 0) {
            alert('未能添加任何基础组（可能全部重复）');
        }
    }

    /** Single: add selected factors × (selected index or all groups) */
    function _doSingleAdd() {
        var testerId = _addState.testerId;
        var groupCount = _addState.groupCount;
        var factors = _addState.selectedFactors;
        var allGroups = _addState.allGroups;
        var groupIndex = _addState.groupIndex;

        var comboLetters = _preComputeComboLetters(testerId, factors, groupCount);

        var added = 0;
        for (var fi = 0; fi < factors.length; fi++) {
            var alias = factors[fi];
            var comboKey = String(testerId) + '|' + alias + '|' + groupCount;
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
        _closeModal();
        if (added === 0) {
            alert('未能添加任何基础组（可能全部重复）');
        }
    }

    function _closeModal() {
        _addState = null;
        var modal = $(_modalId);
        if (modal) { modal.remove(); }
    }

    // ---------------------------------------------------------------------------
    // Render table
    // ---------------------------------------------------------------------------

    function render() {
        var container = $(_containerId);
        if (!container) {
            // No container yet — maybe this sub-tab is not mounted
            return;
        }

        var items = GT.datamodel.base_groups.getAll();

        var addBtnHtml = '<button id="base-group-add-btn" style="margin-bottom:12px;padding:6px 16px;border:none;border-radius:4px;background:#0078d4;color:#fff;cursor:pointer;font-size:13px;">＋ 新增基础组</button>';

        if (items.length === 0) {
            container.innerHTML = '<div class="group-test-empty-state" style="padding:32px;text-align:center;color:#888;">'
                + '<div style="margin-bottom:12px;">暂无基础组</div>'
                + addBtnHtml
                + '</div>';
            // Bind add button
            var emptyAddBtn = container.querySelector('#base-group-add-btn');
            if (emptyAddBtn) emptyAddBtn.addEventListener('click', function() { _showModal(null); });
            return;
        }

        var html = addBtnHtml;
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

        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            var isActive = item.id === _activeId;
            var rowClass = isActive ? 'grouptest-row-active' : '';
            var rowStyle = isActive ? 'background:#e8f4fd;' : '';

            html += '<tr class="grouptest-base-row ' + rowClass + '" data-bg-id="' + escapeHTML(item.id) + '" style="cursor:pointer;border-bottom:1px solid #e8eaed;' + rowStyle + '">';
            html += '<td style="padding:8px 12px;font-weight:600;color:#0078d4;">' + escapeHTML(item.shortAlias || item.name) + '</td>';
            html += '<td style="padding:8px 12px;font-size:11px;color:#555;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escapeHTML(item.name) + '</td>';
            html += '<td style="padding:8px 12px;">' + escapeHTML(_testerLabel(item.testerId)) + '</td>';
            html += '<td style="padding:8px 12px;">' + escapeHTML(item.factorAlias) + '</td>';
            html += '<td style="padding:8px 12px;text-align:center;">' + item.groupCount + '</td>';
            html += '<td style="padding:8px 12px;text-align:center;">' + item.groupIndex + '</td>';
            html += '<td style="padding:8px 12px;text-align:center;white-space:nowrap;">';
            html += '<button class="grouptest-edit-btn" data-bg-id="' + escapeHTML(item.id) + '" style="margin-right:4px;padding:2px 8px;font-size:12px;border:1px solid #d0d5dd;border-radius:3px;background:#fff;cursor:pointer;">✏️ 编辑</button>';
            html += '<button class="grouptest-del-btn" data-bg-id="' + escapeHTML(item.id) + '" style="padding:2px 8px;font-size:12px;border:1px solid #d0d5dd;border-radius:3px;background:#fff;cursor:pointer;">🗑️ 删除</button>';
            html += '</td>';
            html += '</tr>';
        }

        html += '</tbody></table>';
        container.innerHTML = html;

        // Bind add button
        var addBtn = container.querySelector('#base-group-add-btn');
        if (addBtn) addBtn.addEventListener('click', function() { _showModal(null); });

        // Bind row clicks
        _bindRowEvents(container);
    }

    function _bindRowEvents(container) {
        // Row click → select
        var rows = container.querySelectorAll('.grouptest-base-row');
        for (var i = 0; i < rows.length; i++) {
            rows[i].addEventListener('click', function(e) {
                // Don't select if clicking a button
                if (e.target.tagName === 'BUTTON') return;
                var id = this.getAttribute('data-bg-id');
                GT.state.setActiveBaseGroupId(id);
            });
        }

        // Edit button
        var editBtns = container.querySelectorAll('.grouptest-edit-btn');
        for (var j = 0; j < editBtns.length; j++) {
            editBtns[j].addEventListener('click', function(e) {
                e.stopPropagation();
                var id = this.getAttribute('data-bg-id');
                var item = GT.datamodel.base_groups.get(id);
                if (item) {
                    _showModal(item);
                }
            });
        }

        // Delete button
        var delBtns = container.querySelectorAll('.grouptest-del-btn');
        for (var k = 0; k < delBtns.length; k++) {
            delBtns[k].addEventListener('click', function(e) {
                e.stopPropagation();
                var id = this.getAttribute('data-bg-id');
                var item = GT.datamodel.base_groups.get(id);
                if (item && confirm('确定删除基础组 "' + item.name + '" 吗？此操作不可撤销。')) {
                    try {
                        GT.datamodel.base_groups.remove(id);
                        // Rerender handled by event
                    } catch (err) {
                        alert('删除失败: ' + err.message);
                    }
                }
            });
        }
    }

    function _highlightRow(id) {
        _activeId = id;
        var container = $(_containerId);
        if (!container) return;

        // Remove all highlights
        var allRows = container.querySelectorAll('.grouptest-base-row');
        for (var i = 0; i < allRows.length; i++) {
            allRows[i].classList.remove('grouptest-row-active');
            allRows[i].style.background = '';
        }

        if (!id) return;

        // Add highlight to matching row
        var row = container.querySelector('.grouptest-base-row[data-bg-id="' + id + '"]');
        if (row) {
            row.classList.add('grouptest-row-active');
            row.style.background = '#e8f4fd';
        }
    }

    // ---------------------------------------------------------------------------
    // Event handlers (for GT.state events)
    // ---------------------------------------------------------------------------

    function _onBaseGroupsChanged(data) {
        if (_mounted) {
            render();
        }
    }

    function _onActiveBaseGroupChanged(data) {
        if (_mounted) {
            _highlightRow(data.id);
        }
    }

    // ---------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------

    /**
     * Mount the panel — set up container, render, bind events.
     * Call when switching to this sub-tab.
     */
    function mount() {
        _mounted = true;

        // Ensure container exists
        var container = $(_containerId);
        if (!container) {
            GT.log('panels.base.list: container #' + _containerId + ' not found');
            return;
        }

        // Sync active state
        _activeId = GT.state.getActiveBaseGroupId();

        // Listen for changes
        GT.state.on('baseGroupsChanged', _onBaseGroupsChanged);
        GT.state.on('activeBaseGroupChanged', _onActiveBaseGroupChanged);

        // Initial render
        render();
    }

    /**
     * Unmount the panel — remove event listeners.
     * Call when switching away from this sub-tab.
     */
    function unmount() {
        _mounted = false;
        GT.state.off('baseGroupsChanged', _onBaseGroupsChanged);
        GT.state.off('activeBaseGroupChanged', _onActiveBaseGroupChanged);
    }

    /**
     * Force re-render (useful after manual DOM changes).
     */
    function refresh() {
        if (_mounted) {
            _activeId = GT.state.getActiveBaseGroupId();
            render();
        }
    }

    // ---------------------------------------------------------------------------
    // Export
    // ---------------------------------------------------------------------------

    GT.panels.base.list = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,       // exposed for testing
        _showModal: _showModal, // exposed for testing
        _closeModal: _closeModal,
    };

    GT.log('panels.base.list loaded');
})();
