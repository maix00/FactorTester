/**
 * panels/base/add_tester.js — Add-flow sub-tab: "测试器与分组数(序号)"
 *
 * Renders a row-based tester list (master-branch style) where the user picks
 * a tester, sets groupCount, groupIndex, and allGroups toggle.
 * State is stored in GT.ui.getAddDraft() / GT.ui.updateAddDraft().
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.base) { GT.panels.base = {}; }

    var _containerId = 'base-add-tester';
    var _mounted = false;

    function $(id) { return document.getElementById(id); }

    function escapeHTML(str) {
        if (str === null || str === undefined) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function render() {
        var container = $(_containerId);
        if (!container) return;

        var subs = window.submissions || [];
        var draft = GT.ui.getAddDraft();
        if (!draft) return;

        var html = '';

        // ── Tester list (row-based, master-branch style) ──
        html += '<div style="margin-bottom:20px;">';
        html += '<div style="font-size:13px;font-weight:600;margin-bottom:8px;color:#333;">选择测试器 <span style="color:red;">*</span></div>';
        if (subs.length === 0) {
            html += '<div style="color:#888;font-size:12px;padding:8px;">暂无提交记录，请先在产品类别筛选模块提交产品。</div>';
        } else {
            html += '<table style="width:100%;border-collapse:collapse;font-size:13px;">';
            html += '<thead><tr style="background:#f6f8fa;border-bottom:1px solid #d0d5dd;">';
            html += '<th style="padding:6px 10px;text-align:left;width:40px;"></th>';
            html += '<th style="padding:6px 10px;text-align:left;">类型</th>';
            html += '<th style="padding:6px 10px;text-align:left;">名称</th>';
            html += '<th style="padding:6px 10px;text-align:left;">ID</th>';
            html += '</tr></thead><tbody>';
            for (var i = 0; i < subs.length; i++) {
                var sub = subs[i];
                var subId = String(sub.id);
                var isPg = !!sub.product_group;
                var label = isPg ? (sub.product_group || sub.label) : (sub.label || ('测试器 #' + subId));
                var typeLabel = isPg ? '📦 产品组' : '📁 路径组';
                var isSelected = (String(draft.testerId) === subId);
                var rowStyle = isSelected ? 'background:#e8f4fd;' : '';
                html += '<tr class="at-tester-row" data-tester-id="' + escapeHTML(subId) + '"'
                    + ' style="cursor:pointer;border-bottom:1px solid #e8eaed;' + rowStyle + '">';
                html += '<td style="padding:6px 10px;">';
                html += '<span class="at-tester-radio" style="display:inline-block;width:16px;height:16px;border-radius:50%;border:2px solid ' + (isSelected ? '#0078d4' : '#ccc') + ';background:' + (isSelected ? '#0078d4' : '#fff') + ';"></span>';
                html += '</td>';
                html += '<td style="padding:6px 10px;">' + escapeHTML(typeLabel) + '</td>';
                html += '<td style="padding:6px 10px;">' + escapeHTML(label) + '</td>';
                html += '<td style="padding:6px 10px;color:#888;font-size:11px;">' + escapeHTML(subId) + '</td>';
                html += '</tr>';
            }
            html += '</tbody></table>';
        }
        html += '</div>';

        // ── Group count ──
        html += '<div style="margin-bottom:16px;">';
        html += '<div style="font-size:13px;font-weight:600;margin-bottom:4px;color:#333;">分组数 <span style="color:red;">*</span></div>';
        html += '<input type="number" id="at-group-count" value="' + (draft.groupCount || 2) + '" min="1" step="1" style="width:100px;padding:6px;border:1px solid #d0d5dd;border-radius:4px;">';
        html += '<span style="font-size:11px;color:#888;margin-left:8px;">≥ 1</span>';
        html += '</div>';

        // ── Group index ──
        html += '<div style="margin-bottom:16px;">';
        html += '<div style="font-size:13px;font-weight:600;margin-bottom:4px;color:#333;">分组索引 (从1开始)</div>';
        html += '<input type="number" id="at-group-index" value="' + (draft.groupIndex || 1) + '" min="1" step="1"'
            + (draft.allGroups ? ' disabled style="width:100px;padding:6px;border:1px solid #ddd;border-radius:4px;background:#f0f0f0;color:#999;"'
               : ' style="width:100px;padding:6px;border:1px solid #d0d5dd;border-radius:4px;"') + '>';
        html += '<span style="font-size:11px;color:#888;margin-left:8px;">如勾选"所有分组"则忽略此值</span>';
        html += '</div>';

        // ── All groups checkbox ──
        html += '<div style="margin-bottom:16px;">';
        html += '<label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px;">';
        html += '<input type="checkbox" id="at-all-groups" ' + (draft.allGroups ? 'checked' : '') + ' style="width:16px;height:16px;">';
        html += '<span>所有分组（为每个分组索引都创建一个基础组）</span>';
        html += '</label>';
        html += '</div>';

        container.innerHTML = html;

        // ── Bind events ──
        var testerRows = container.querySelectorAll('.at-tester-row');
        for (var ti = 0; ti < testerRows.length; ti++) {
            testerRows[ti].addEventListener('click', function() {
                var tid = this.getAttribute('data-tester-id');
                GT.ui.updateAddDraft({ testerId: tid });
                render();
            });
        }

        var gcInput = $('at-group-count');
        if (gcInput) {
            gcInput.addEventListener('input', function() {
                var v = parseInt(this.value, 10);
                if (v >= 1) GT.ui.updateAddDraft({ groupCount: v });
            });
        }

        var giInput = $('at-group-index');
        if (giInput) {
            giInput.addEventListener('input', function() {
                var v = parseInt(this.value, 10);
                if (v >= 1) GT.ui.updateAddDraft({ groupIndex: v });
            });
        }

        var agCheck = $('at-all-groups');
        if (agCheck) {
            agCheck.addEventListener('change', function() {
                GT.ui.updateAddDraft({ allGroups: this.checked });
                render();
            });
        }
    }

    function _onAddDraftChanged() {
        if (_mounted) render();
    }

    function mount() {
        _mounted = true;
        var container = $(_containerId);
        if (!container) {
            GT.log('panels.base.add_tester: container #' + _containerId + ' not found');
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

    GT.panels.base.add_tester = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
    };

    GT.log('panels.base.add_tester loaded');
})();
