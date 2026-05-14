/**
 * Product Group Manager — overlay for managing named product path groups.
 * Uses ProductSelector unified two-column layout: left tree, right group list.
 * Manager submit = save product group (vs drawer submit = FactorTester).
 * Depends on: jQuery, Fancytree, SortableJS, ProductGroupShared, ProductSelector.
 */
(function($, window) {
    'use strict';

    var PG = window.ProductGroupShared;
    var PS = window.ProductSelector;
    if (!PG) { console.error('ProductGroupShared not loaded'); return; }
    if (!PS) { console.error('ProductSelector not loaded'); return; }

    var currentGroupName = null;
    var allGroupPaths = [];
    var groupTree = null;
    var $managerRoot = null;

    var $overlay = $('#pg-overlay');

    // ── 组列表渲染（右侧面板） ─────────────────────────────────────────────

    function renderGroupList() {
        var $container = PS.getSubmissionContainer($managerRoot);
        if (!$container || !$container.length) return;

        PG.fetchGroups().then(function(groups) {
            var html = '';
            if (groups && groups.length) {
                html += '<div id="pg-group-list" style="font-size:13px;">';
                groups.forEach(function(g, i) {
                    var isActive = g.name === currentGroupName;
                    html += '<div class="pg-group-item" data-name="' + _esc(g.name) + '" style="display:flex;align-items:center;justify-content:space-between;padding:8px 10px;margin-bottom:4px;border-radius:6px;cursor:pointer;'
                        + (isActive ? 'background:#e8f0fe;font-weight:600;' : 'background:#f6f8fa;')
                        + 'border:1px solid ' + (isActive ? '#4a90d9' : '#e1e4e8') + ';">';
                    html += '<div style="display:flex;align-items:center;gap:6px;flex:1;min-width:0;">';
                    html += '<i class="fas fa-grip-vertical" style="color:#888;cursor:grab;flex-shrink:0;"></i>';
                    html += '<span class="pg-group-name" title="点击加载 / 双击重命名" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + _esc(g.name) + '</span>';
                    html += '<span style="color:#888;font-size:11px;flex-shrink:0;">(' + (g.path_count || g.paths ? g.paths.length : 0) + '条)</span>';
                    html += '</div>';
                    html += '<button class="pg-group-del" data-name="' + _esc(g.name) + '" style="background:none;border:none;color:#d00;cursor:pointer;font-size:13px;flex-shrink:0;margin-left:4px;"><i class="fas fa-trash"></i></button>';
                    html += '</div>';
                });
                html += '</div>';
            } else {
                html = '<div style="color:#888;text-align:center;padding:20px;">暂无产品组，在左侧树中勾选路径后点击保存</div>';
            }
            $container.html(html);

            // 拖拽排序
            var el = document.getElementById('pg-group-list');
            if (el && window.Sortable) {
                if (el._sortable) el._sortable.destroy();
                window.Sortable.create(el, {
                    animation: 150,
                    handle: '.fa-grip-vertical',
                    onEnd: function() {
                        var names = [];
                        $('#pg-group-list .pg-group-item').each(function() {
                            names.push($(this).data('name'));
                        });
                        PG.reorderGroups(names).then(function() {
                            // reorder 完成后不需要额外操作
                        });
                    }
                });
            }

            // 事件绑定
            $container.find('.pg-group-item').on('click', function(e) {
                if ($(e.target).closest('.pg-group-del').length) return;
                if ($(e.target).closest('.fa-grip-vertical').length) return;
                loadGroupForEdit($(this).data('name'));
            });

            // 双击重命名
            $container.find('.pg-group-name').on('dblclick', function(e) {
                e.stopPropagation();
                var $name = $(this);
                var oldName = $name.text().trim();
                var $inp = $('<input type="text" style="font-size:13px;padding:2px 6px;border:1px solid #4a90d9;border-radius:4px;width:100%;box-sizing:border-box;">')
                    .val(oldName)
                    .insertAfter($name);
                $name.hide();
                $inp.focus().select();

                function commit() {
                    var newName = $inp.val().trim();
                    $inp.remove();
                    $name.show();
                    if (newName && newName !== oldName) {
                        PG.renameGroup(oldName, newName).then(function() {
                            if (currentGroupName === oldName) currentGroupName = newName;
                            renderGroupList();
                        });
                    }
                }
                $inp.on('keydown', function(ev) {
                    if (ev.key === 'Enter') commit();
                    if (ev.key === 'Escape') { $inp.remove(); $name.show(); }
                });
                $inp.on('blur', commit);
            });
        });
    }

    // ── 组删除 ────────────────────────────────────────────────────────────

    $(document).on('click', '.pg-group-del', async function(e) {
        e.stopPropagation();
        var name = $(this).data('name');
        if (!confirm('删除产品组 "' + name + '"？')) return;
        await PG.deleteGroup(name);
        if (currentGroupName === name) { currentGroupName = null; allGroupPaths = []; }
        renderGroupList();
        PS.clearChecks(groupTree);
    });

    // ── 加载组用于编辑 ────────────────────────────────────────────────────

    async function loadGroupForEdit(name) {
        var group = await PG.fetchGroupDetail(name);
        if (!group) return;
        currentGroupName = name;
        allGroupPaths = group.paths || [];
        PS.clearChecks(groupTree);
        PS.restoreChecks(groupTree, allGroupPaths);
        renderGroupList();
    }

    // ── 保存产品组 ────────────────────────────────────────────────────────

    async function doSave() {
        if (!allGroupPaths.length) { alert('请在左侧树中勾选至少一个品种'); return; }

        var name = currentGroupName;
        if (!name) {
            name = prompt('请输入产品组名称：');
            if (!name || !name.trim()) return;
            name = name.trim();
        }

        var resp;
        if (currentGroupName) {
            resp = await PG.updateGroup(currentGroupName, allGroupPaths);
        } else {
            resp = await PG.createGroup(name, allGroupPaths);
        }

        if (resp.success) {
            currentGroupName = name;
            renderGroupList();
        } else {
            alert('保存失败: ' + (resp.error || '未知错误'));
        }
    }

    // ── 打开/关闭 Overlay ────────────────────────────────────────────────

    function openOverlay() {
        $overlay.css('display', 'flex');
        currentGroupName = null;
        allGroupPaths = [];

        // 如果还没渲染，用 PS.render 生成统一两栏布局
        if (!$('#ps-manager-root').find('.ps-body').length) {
            PS.render($('#ps-manager-root'), {
                title: '📦 产品组管理',
                submitLabel: '💾 保存产品组',
                onSubmit: doSave,
                headerBtns: '<button id="pg-overlay-close" style="background:none;border:none;font-size:20px;cursor:pointer;color:#888;">&times;</button>',
                toolbar: '<input id="pg-new-name" placeholder="新组名..." style="padding:6px 8px;border:1px solid #d0d5dd;border-radius:4px;font-size:12px;width:150px;" maxlength="30">'
                    + '<span style="font-size:12px;color:#666;">或从右侧列表点击已有组编辑</span>'
            });
            $managerRoot = $('#ps-manager-root');

            // 初始化左侧树
            PS.initLeftTree($managerRoot, {
                onInit: function(tree) { groupTree = tree; },
                onSelect: function(paths) { allGroupPaths = paths; }
            });

            // 关闭按钮
            $('#pg-overlay-close').on('click', closeOverlay);
            // 新组名输入回车即保存
            $('#pg-new-name').on('keydown', function(e) {
                if (e.key === 'Enter') {
                    currentGroupName = $(this).val().trim() || null;
                    doSave();
                }
            });

            // 更新右侧提示文字
            PS.updateLeftHint($managerRoot, '勾选品种加入产品组，点击保存');
        } else {
            $managerRoot = $('#ps-manager-root');
            PS.clearChecks(groupTree);
        }

        renderGroupList();
    }

    function closeOverlay() {
        $overlay.css('display', 'none');
    }

    window.openProductGroupManager = openOverlay;

    $('#btn-product-groups').on('click', openOverlay);
    $('#pg-overlay').on('click', function(e) { if (e.target === this) closeOverlay(); });

    function _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

})(jQuery, window);
