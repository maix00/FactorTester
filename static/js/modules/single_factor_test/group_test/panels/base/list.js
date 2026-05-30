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

    // ---------------------------------------------------------------------------
    // Modal management
    // ---------------------------------------------------------------------------

    function _showModal(editData) {
        var existing = $(_modalId);
        if (existing) { existing.remove(); }

        var isEdit = !!editData;
        var title = isEdit ? '编辑基础组' : '新增基础组';

        var html = '<div id="' + _modalId + '" style="position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);display:flex;align-items:center;justify-content:center;z-index:10000;">';
        html += '<div style="background:#fff;border-radius:8px;padding:24px;min-width:420px;max-width:520px;box-shadow:0 8px 32px rgba(0,0,0,0.2);">';
        html += '<h3 style="margin:0 0 16px 0;">' + title + '</h3>';
        html += '<form id="' + _formId + '" onsubmit="return false;">';

        // --- Fields ---
        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">名称 <span style="color:red;">*</span></span>';
        html += '<input type="text" id="bgf_name" value="' + escapeHTML(isEdit ? editData.name : '') + '" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;" required>';
        html += '</label>';

        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">测试器 <span style="color:red;">*</span></span>';
        html += '<select id="bgf_testerId" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;" required>';
        html += '<option value="">-- 请选择测试器 --</option>';
        // Populate from window.submissions (the list of FactorTester submissions)
        var subs = window.submissions || [];
        subs.forEach(function(sub) {
            var subId = String(sub.id);
            var subLabel = sub.product_group || sub.label || ('测试器 #' + subId);
            var selected = (isEdit && String(editData.testerId) === subId) ? ' selected' : '';
            html += '<option value="' + escapeHTML(subId) + '"' + selected + '>' + escapeHTML(subLabel) + ' (ID:' + escapeHTML(subId) + ')</option>';
        });
        html += '</select>';
        html += '</label>';

        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">因子别名 <span style="color:red;">*</span></span>';
        html += '<input type="text" id="bgf_factorAlias" value="' + escapeHTML(isEdit ? editData.factorAlias : '') + '" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;" required>';
        html += '</label>';

        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">分组数 <span style="color:red;">*</span> (2-10)</span>';
        html += '<input type="number" id="bgf_groupCount" value="' + (isEdit ? editData.groupCount : 5) + '" min="2" max="10" step="1" style="width:80px;padding:6px;border:1px solid #ddd;border-radius:4px;" required>';
        html += '</label>';

        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">分组索引 (0-based)</span>';
        html += '<input type="number" id="bgf_groupIndex" value="' + (isEdit ? editData.groupIndex : 0) + '" min="0" step="1" style="width:80px;padding:6px;border:1px solid #ddd;border-radius:4px;">';
        html += '</label>';

        html += '<label style="display:block;margin-bottom:16px;">';
        html += '<input type="checkbox" id="bgf_isAllGroups" ' + (isEdit && editData.isAllGroups ? 'checked' : '') + '>';
        html += '<span style="font-size:13px;margin-left:4px;">所有分组</span>';
        html += '</label>';

        // --- Buttons ---
        html += '<div style="display:flex;gap:8px;justify-content:flex-end;">';
        html += '<button type="button" id="bgf-cancel" style="padding:6px 16px;border:1px solid #ddd;border-radius:4px;background:#f6f8fa;cursor:pointer;">取消</button>';
        html += '<button type="submit" id="bgf-save" style="padding:6px 16px;border:none;border-radius:4px;background:#0078d4;color:#fff;cursor:pointer;">' + (isEdit ? '保存' : '新增') + '</button>';
        html += '</div>';

        html += '</form></div></div>';

        document.body.insertAdjacentHTML('beforeend', html);

        // Store editing ID
        $(_modalId)._editId = isEdit ? editData.id : null;

        // Bind events
        $('bgf-cancel').addEventListener('click', _closeModal);
        $(_formId).addEventListener('submit', _handleFormSubmit);

        // Close on backdrop click
        $(_modalId).addEventListener('click', function(e) {
            if (e.target === this) _closeModal();
        });
    }

    function _closeModal() {
        var modal = $(_modalId);
        if (modal) { modal.remove(); }
    }

    function _handleFormSubmit(e) {
        e.preventDefault();

        var editId = $(_modalId)._editId;
        var testerSelect = $('bgf_testerId');
        var testerId = testerSelect ? testerSelect.value : '';
        var testerLabel = testerSelect && testerSelect.selectedIndex >= 0 ? testerSelect.options[testerSelect.selectedIndex].text : '';
        var data = {
            name: $('bgf_name').value.trim(),
            testerId: testerId,
            factorAlias: $('bgf_factorAlias').value.trim(),
            groupCount: parseInt($('bgf_groupCount').value, 10),
            groupIndex: parseInt($('bgf_groupIndex').value, 10) || 0,
            isAllGroups: $('bgf_isAllGroups').checked,
        };

        try {
            if (editId) {
                GT.datamodel.base_groups.update(editId, data);
            } else {
                GT.datamodel.base_groups.add(data);
            }
            _closeModal();
            // Rerender handled by baseGroupsChanged event
        } catch (err) {
            alert('操作失败: ' + err.message);
        }
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
            html += '<td style="padding:8px 12px;">' + escapeHTML(item.name) + '</td>';
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
