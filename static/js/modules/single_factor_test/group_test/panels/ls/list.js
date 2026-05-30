/**
 * panels/ls/list.js — LS (Long-Short) config list panel (Tab 3 "多空")
 *
 * Phase 5 UI panel. Renders LS config table with CRUD via modal forms,
 * row selection/highlight. Manages long-short pair configurations that
 * reference derived groups.
 *
 * Data shape (from GT.datamodel.ls_configs):
 *   { id, name, longGroupId, shortGroupId, feeMode, feeRate,
 *     useCloseToday, rebalanceMode, needsRegenerate, metadata }
 *
 * Contract:
 *   GT.datamodel.ls_configs — CRUD data model
 *   GT.datamodel.derived_graph — for resolving group names
 *   GT.state — events: lsConfigsChanged, activeLSConfigChanged
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.ls) { GT.panels.ls = {}; }

    // ---------------------------------------------------------------------------
    // Internal state
    // ---------------------------------------------------------------------------

    var _containerId = 'ls-configs-list';
    var _modalId = 'ls-config-form-modal';
    var _formId = 'ls-config-form';

    var _mounted = false;
    var _activeId = null;

    // ---------------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------------

    function $(id) { return document.getElementById(id); }

    function escapeHTML(str) {
        if (str === null || str === undefined) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    /** Resolve derived group name from id */
    function _dgName(id) {
        if (!id) return '—';
        if (GT.datamodel.derived_graph && GT.datamodel.derived_graph.get) {
            var dg = GT.datamodel.derived_graph.get(id);
            if (dg) return dg.name || id;
        }
        return id;
    }

    /** Look up tester label via derivedGroupId → baseGroupId → testerId */
    function _testerLabel(dgId) {
        if (!dgId) return '—';
        var dg = GT.datamodel.derived_graph && GT.datamodel.derived_graph.get(dgId);
        if (!dg || !dg.baseGroupId) return '—';
        var bg = GT.datamodel.base_groups && GT.datamodel.base_groups.get(dg.baseGroupId);
        if (!bg || !bg.testerId) return '—';
        var subs = window.submissions || [];
        for (var i = 0; i < subs.length; i++) {
            if (String(subs[i].id) === String(bg.testerId)) {
                return subs[i].product_group || subs[i].label || ('测试器 #' + subs[i].id);
            }
        }
        return bg.testerId || '—';
    }

    // ---------------------------------------------------------------------------
    // Toolbar
    // ---------------------------------------------------------------------------

    function _makeToolbar() {
        var html = '<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">';
        html += '<button id="ls-add-btn" style="padding:6px 16px;border:none;border-radius:4px;background:#0078d4;color:#fff;cursor:pointer;font-size:13px;">+ 新增多空配置</button>';
        html += '</div>';
        return html;
    }

    // ---------------------------------------------------------------------------
    // Modal: Add / Edit LS config
    // ---------------------------------------------------------------------------

    function _showModal(editData) {
        var existing = $(_modalId);
        if (existing) { existing.remove(); }

        var isEdit = !!editData;
        var title = isEdit ? '编辑多空配置' : '新增多空配置';

        // Get derived group options for dropdowns
        var dgOptions = [];
        if (GT.datamodel.derived_graph && GT.datamodel.derived_graph.list) {
            dgOptions = GT.datamodel.derived_graph.list();
        }

        var html = '<div id="' + _modalId + '" style="position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);display:flex;align-items:center;justify-content:center;z-index:10000;">';
        html += '<div style="background:#fff;border-radius:8px;padding:24px;min-width:460px;max-width:560px;box-shadow:0 8px 32px rgba(0,0,0,0.2);">';
        html += '<h3 style="margin:0 0 16px 0;">' + title + '</h3>';
        html += '<form id="' + _formId + '" onsubmit="return false;">';

        // Name
        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">名称 <span style="color:red;">*</span></span>';
        html += '<input type="text" id="lsf_name" value="' + escapeHTML(isEdit ? editData.name : '') + '" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;" required>';
        html += '</label>';

        // Long group
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

        // Short group
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

        // Buttons
        html += '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;">';
        html += '<button type="button" id="lsf-cancel" style="padding:6px 16px;border:1px solid #ddd;border-radius:4px;background:#f6f8fa;cursor:pointer;">取消</button>';
        html += '<button type="submit" id="lsf-save" style="padding:6px 16px;border:none;border-radius:4px;background:#0078d4;color:#fff;cursor:pointer;">' + (isEdit ? '保存' : '新增') + '</button>';
        html += '</div>';

        html += '</form></div></div>';

        document.body.insertAdjacentHTML('beforeend', html);

        $(_modalId)._editId = isEdit ? editData.id : null;

        $('lsf-cancel').addEventListener('click', _closeModal);
        $(_formId).addEventListener('submit', _handleFormSubmit);
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
        var data = {
            name: $('lsf_name').value.trim(),
            longGroupId: $('lsf_longGroupId').value,
            shortGroupId: $('lsf_shortGroupId').value,
        };

        try {
            if (editId) {
                GT.datamodel.ls_configs.update(editId, data);
            } else {
                GT.datamodel.ls_configs.add(data);
            }
            _closeModal();
        } catch (err) {
            alert('操作失败: ' + err.message);
        }
    }

    // ---------------------------------------------------------------------------
    // Toolbar > Add button handler
    // ---------------------------------------------------------------------------

    function _onAddClick(e) {
        _showModal(null);
    }

    // ---------------------------------------------------------------------------
    // Render table
    // ---------------------------------------------------------------------------

    function render() {
        var container = $(_containerId);
        if (!container) return;

        var items = GT.datamodel.ls_configs.getAll();

        var html = _makeToolbar();

        if (items.length === 0) {
            html += '<div style="padding:32px;text-align:center;color:#888;">暂无多空配置，点击上方「新增多空配置」创建</div>';
        } else {
            html += '<table style="width:100%;border-collapse:collapse;font-size:13px;">';
            html += '<thead><tr style="background:#f6f8fa;border-bottom:2px solid #d0d5dd;">';
            html += '<th style="padding:8px 12px;text-align:left;">名称</th>';
            html += '<th style="padding:8px 12px;text-align:left;">多头组</th>';
            html += '<th style="padding:8px 12px;text-align:left;">空头组</th>';
            html += '<th style="padding:8px 12px;text-align:left;">测试器</th>';
            html += '<th style="padding:8px 12px;text-align:center;">状态</th>';
            html += '<th style="padding:8px 12px;text-align:center;">操作</th>';
            html += '</tr></thead><tbody>';

            for (var i = 0; i < items.length; i++) {
                var item = items[i];
                var isActive = item.id === _activeId;
                var rowStyle = isActive ? 'background:#e8f4fd;' : '';
                var staleTag = item.needsRegenerate
                    ? '<span style="padding:1px 6px;background:#fef3c7;color:#d97706;border-radius:3px;font-size:11px;">待更新</span>'
                    : '<span style="padding:1px 6px;background:#d1fae5;color:#059669;border-radius:3px;font-size:11px;">就绪</span>';
                // Show tester from long group (long/short should share same tester via base_groups)
                var testerText = _testerLabel(item.longGroupId);

                html += '<tr class="ls-config-row" data-ls-id="' + escapeHTML(item.id) + '" style="cursor:pointer;border-bottom:1px solid #e8eaed;' + rowStyle + '">';
                html += '<td style="padding:8px 12px;">' + escapeHTML(item.name) + '</td>';
                html += '<td style="padding:8px 12px;font-family:monospace;font-size:12px;">' + escapeHTML(_dgName(item.longGroupId)) + '</td>';
                html += '<td style="padding:8px 12px;font-family:monospace;font-size:12px;">' + escapeHTML(_dgName(item.shortGroupId)) + '</td>';
                html += '<td style="padding:8px 12px;font-size:12px;color:#555;">' + escapeHTML(testerText) + '</td>';
                html += '<td style="padding:8px 12px;text-align:center;">' + staleTag + '</td>';
                html += '<td style="padding:8px 12px;text-align:center;white-space:nowrap;">';
                html += '<button class="ls-edit-btn" data-ls-id="' + escapeHTML(item.id) + '" style="margin-right:4px;padding:2px 8px;font-size:12px;border:1px solid #d0d5dd;border-radius:3px;background:#fff;cursor:pointer;">✏️ 编辑</button>';
                html += '<button class="ls-del-btn" data-ls-id="' + escapeHTML(item.id) + '" style="padding:2px 8px;font-size:12px;border:1px solid #d0d5dd;border-radius:3px;background:#fff;cursor:pointer;">🗑️ 删除</button>';
                html += '</td>';
                html += '</tr>';
            }

            html += '</tbody></table>';
        }

        container.innerHTML = html;

        // Bind toolbar button
        var addBtn = $('ls-add-btn');
        if (addBtn) {
            addBtn.addEventListener('click', _onAddClick);
        }

        // Bind row events
        if (items.length > 0) {
            _bindRowEvents(container);
        }
    }

    function _bindRowEvents(container) {
        var rows = container.querySelectorAll('.ls-config-row');
        for (var i = 0; i < rows.length; i++) {
            rows[i].addEventListener('click', function(e) {
                if (e.target.tagName === 'BUTTON') return;
                var id = this.getAttribute('data-ls-id');
                GT.state.setActiveLSConfigId(id);
            });
        }

        var editBtns = container.querySelectorAll('.ls-edit-btn');
        for (var j = 0; j < editBtns.length; j++) {
            editBtns[j].addEventListener('click', function(e) {
                e.stopPropagation();
                var id = this.getAttribute('data-ls-id');
                var item = GT.datamodel.ls_configs.get(id);
                if (item) _showModal(item);
            });
        }

        var delBtns = container.querySelectorAll('.ls-del-btn');
        for (var k = 0; k < delBtns.length; k++) {
            delBtns[k].addEventListener('click', function(e) {
                e.stopPropagation();
                var id = this.getAttribute('data-ls-id');
                var item = GT.datamodel.ls_configs.get(id);
                if (item && confirm('确定删除多空配置 "' + item.name + '" 吗？此操作不可撤销。')) {
                    try {
                        GT.datamodel.ls_configs.remove(id);
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

        var allRows = container.querySelectorAll('.ls-config-row');
        for (var i = 0; i < allRows.length; i++) {
            allRows[i].style.background = '';
        }

        if (!id) return;
        var row = container.querySelector('.ls-config-row[data-ls-id="' + id + '"]');
        if (row) row.style.background = '#e8f4fd';
    }

    // ---------------------------------------------------------------------------
    // Event handlers
    // ---------------------------------------------------------------------------

    function _onLSConfigsChanged() { if (_mounted) render(); }
    function _onActiveLSConfigChanged(data) { if (_mounted) _highlightRow(data && data.id); }

    // ---------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------

    function mount() {
        _mounted = true;
        var container = $(_containerId);
        if (!container) { GT.log('panels.ls.list: container #' + _containerId + ' not found'); return; }
        _activeId = GT.state.getActiveLSConfigId();
        GT.state.on('lsConfigsChanged', _onLSConfigsChanged);
        GT.state.on('activeLSConfigChanged', _onActiveLSConfigChanged);
        render();
    }

    function unmount() {
        _mounted = false;
        GT.state.off('lsConfigsChanged', _onLSConfigsChanged);
        GT.state.off('activeLSConfigChanged', _onActiveLSConfigChanged);
    }

    function refresh() { if (_mounted) { _activeId = GT.state.getActiveLSConfigId(); render(); } }

    // ---------------------------------------------------------------------------
    // Export
    // ---------------------------------------------------------------------------

    GT.panels.ls.list = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
        _showModal: _showModal,
        _closeModal: _closeModal,
    };

    GT.log('panels.ls.list loaded');
})();
