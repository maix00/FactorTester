/**
 * settings_row_list.js — 中立的"设置行列表"公共组件（window.SettingsRowList）。
 *
 * 由后端 manifest 的 surface（kind="list"）驱动：一行一组设置，每行展示 chips，
 * 可单/多选、可展开、可点击进入编辑、带行操作（运行/编辑/删除）。
 *
 * 与具体业务（GroupTest / IC / …）解耦：调用方传入 surface 描述符 + 行数据 + 回调，
 * 组件只负责渲染与事件分发，不知道"分组""IC 配置"等领域概念。
 *
 *   SettingsRowList.render(container, {
 *     surface: { label, selection, run_mode, editable, item_label },  // 来自 manifest.surfaces
 *     rows: [{ id, chips:[{label, value, primary?}], selected?, expanded?, title? }],
 *     showChips: bool,                 // "显示设置"开关的当前态（调用方持有）
 *     callbacks: {
 *       onSelect(id), onRun(id), onEdit(id), onDelete(id), onAdd(),
 *       onToggleExpand(id), onToggleChips(next),
 *     },
 *     escapeHTML, renderChipHtml,      // 可选，注入以复用宿主的实现/样式
 *   });
 */
(function() {
    if (window.SettingsRowList) return;

    function _escapeHTML(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function _defaultChipHtml(label, value, esc) {
        var v = '<span class="gt-backend-chip-value">' + esc(value) + '</span>';
        if (!label) return v;
        return '<span class="gt-backend-chip-label">' + esc(label) + '</span>' + v;
    }

    function render(container, opts) {
        opts = opts || {};
        if (!container) return;
        var surface = opts.surface || {};
        var rows = Array.isArray(opts.rows) ? opts.rows : [];
        var cb = opts.callbacks || {};
        var showChips = !!opts.showChips;
        var multi = surface.selection === 'multi';
        var canRun = !!cb.onRun;
        var canEdit = surface.editable && !!cb.onEdit;
        var canDelete = !!cb.onDelete;
        var esc = opts.escapeHTML || _escapeHTML;
        var chipHtml = opts.renderChipHtml || function(label, value) { return _defaultChipHtml(label, value, esc); };
        var itemLabel = surface.item_label || surface.label || '项';

        var html = '';
        // 头部：标题 + 新增 + 显示设置开关
        html += '<div class="srl-header" style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;">';
        html += '<span style="font-size:13px;font-weight:700;color:#334155;">' + esc(surface.label || itemLabel) + '</span>';
        html += '<span style="display:flex;gap:6px;">';
        html += '<button type="button" class="srl-toggle-chips" style="height:24px;padding:0 10px;border:1px solid ' + (showChips ? '#6366f1' : '#cbd5e1') + ';border-radius:4px;background:' + (showChips ? '#eef2ff' : '#fff') + ';color:' + (showChips ? '#3730a3' : '#475569') + ';font-size:12px;cursor:pointer;">' + (showChips ? '收起设置' : '显示设置') + '</button>';
        if (cb.onAdd) {
            html += '<button type="button" class="srl-add" style="height:24px;padding:0 10px;border:1px solid #93c5fd;border-radius:4px;background:#eff6ff;color:#1d4ed8;font-size:12px;cursor:pointer;">+ 新增' + esc(itemLabel) + '</button>';
        }
        html += '</span></div>';

        // 行
        html += '<div class="srl-rows" style="border:1px solid #e8eaed;border-radius:6px;overflow:hidden;">';
        if (!rows.length) {
            html += '<div style="color:#888;font-size:12px;padding:16px;text-align:center;">暂无' + esc(itemLabel) + (cb.onAdd ? '，点击"新增"创建' : '') + '</div>';
        } else {
            rows.forEach(function(row) {
                var selected = !!row.selected;
                var expanded = !!row.expanded;
                html += '<div class="srl-row' + (selected ? ' gt-row-selected' : '') + '" data-row-id="' + esc(row.id) + '"'
                    + ' style="border-bottom:1px solid #f0f2f5;' + (selected ? 'background:#e8f4fd;' : 'background:#fff;') + '">';
                // 行头：选中标记 + 展开 + chips/标题 + 操作
                html += '<div class="srl-row-head" style="display:flex;align-items:center;gap:8px;padding:8px 10px;cursor:pointer;">';
                html += '<span class="srl-mark" style="width:16px;text-align:center;font-size:12px;color:' + (selected ? '#0078d4' : '#cbd5e1') + ';">' + (multi ? (selected ? '☑' : '☐') : (selected ? '●' : '○')) + '</span>';
                html += '<span class="srl-expand" data-row-id="' + esc(row.id) + '" style="width:16px;text-align:center;cursor:pointer;color:#64748b;">' + (expanded ? '▾' : '▸') + '</span>';
                html += '<span class="srl-row-chips" style="flex:1;min-width:0;display:flex;flex-wrap:wrap;gap:6px;align-items:center;">';
                var chips = Array.isArray(row.chips) ? row.chips : [];
                if (showChips && chips.length) {
                    chips.forEach(function(chip) {
                        html += '<span class="gt-backend-chip' + (chip.primary ? ' is-primary' : ' unified-backend-chip') + '">' + chipHtml(chip.label, chip.value) + '</span>';
                    });
                } else {
                    html += '<span style="font-size:13px;font-weight:600;color:#1e293b;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(row.title || (chips[0] && chips[0].value) || row.id) + '</span>';
                }
                html += '</span>';
                html += '<span class="srl-actions" style="display:flex;gap:4px;flex-shrink:0;">';
                if (canRun) html += '<button type="button" class="srl-run" data-row-id="' + esc(row.id) + '" style="height:22px;padding:0 9px;border:1px solid #86efac;border-radius:4px;background:#f0fdf4;color:#15803d;font-size:11px;cursor:pointer;">运行</button>';
                if (canEdit) html += '<button type="button" class="srl-edit" data-row-id="' + esc(row.id) + '" style="height:22px;padding:0 9px;border:1px solid #cbd5e1;border-radius:4px;background:#fff;color:#475569;font-size:11px;cursor:pointer;">编辑</button>';
                if (canDelete) html += '<button type="button" class="srl-delete" data-row-id="' + esc(row.id) + '" style="height:22px;padding:0 9px;border:1px solid #fca5a5;border-radius:4px;background:#fef2f2;color:#dc2626;font-size:11px;cursor:pointer;">删除</button>';
                html += '</span>';
                html += '</div>';
                html += '</div>';
            });
        }
        html += '</div>';

        container.innerHTML = html;

        // 事件绑定
        var addBtn = container.querySelector('.srl-add');
        if (addBtn && cb.onAdd) addBtn.addEventListener('click', function() { cb.onAdd(); });
        var toggleBtn = container.querySelector('.srl-toggle-chips');
        if (toggleBtn && cb.onToggleChips) toggleBtn.addEventListener('click', function() { cb.onToggleChips(!showChips); });

        function rowId(el) { return el.getAttribute('data-row-id'); }

        container.querySelectorAll('.srl-expand').forEach(function(el) {
            el.addEventListener('click', function(e) {
                e.stopPropagation();
                if (cb.onToggleExpand) cb.onToggleExpand(rowId(el));
            });
        });
        container.querySelectorAll('.srl-run').forEach(function(el) {
            el.addEventListener('click', function(e) { e.stopPropagation(); if (cb.onRun) cb.onRun(rowId(el)); });
        });
        container.querySelectorAll('.srl-edit').forEach(function(el) {
            el.addEventListener('click', function(e) { e.stopPropagation(); if (cb.onEdit) cb.onEdit(rowId(el)); });
        });
        container.querySelectorAll('.srl-delete').forEach(function(el) {
            el.addEventListener('click', function(e) { e.stopPropagation(); if (cb.onDelete) cb.onDelete(rowId(el)); });
        });
        container.querySelectorAll('.srl-row-head').forEach(function(head) {
            head.addEventListener('click', function() {
                var row = head.closest('.srl-row');
                if (row && cb.onSelect) cb.onSelect(rowId(row));
            });
        });
    }

    window.SettingsRowList = { render: render };
})();
