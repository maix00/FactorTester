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
    var currentGroupDetail = null; // {name, paths[]} — 当前查看的组详情
    var allGroupPaths = [];
    var groupTree = null;
    var $managerRoot = null;
    var pathExpandedState = {};   // 组详情中每条路径的展开状态
    var categoryTreeSizer = null;
    var selectedGroups = {};      // Ctrl/Cmd+点击多选: {name: true}
    var lastClickedGroup = null;  // 最后点击的组名（用于 Shift+点击范围选择）
    var wasDragging = false;      // SortableJS 拖拽标志位

    var $overlay = $('#pg-overlay');

    // ── 组列表渲染（右侧面板） ─────────────────────────────────────────────

    function renderGroupList() {
        var $container = PS.getSubmissionContainer($managerRoot);
        if (!$container || !$container.length) return;

        // 如果有当前选中的组详情，渲染路径视图
        if (currentGroupDetail) {
            renderGroupPathView($container);
            return;
        }

        updateRightTitle('📋 产品组列表（Ctrl/Cmd+点击多选）');

        PG.fetchGroups().then(function(groups) {
            var searchText = ($('#pg-search-input').val() || '').toLowerCase();
            var filtered = groups;
            if (searchText) {
                filtered = groups.filter(function(g) {
                    return g.name.toLowerCase().indexOf(searchText) !== -1;
                });
            }

            var html = '';
            if (filtered.length) {
                html += '<div id="pg-group-list" style="font-size:13px;">';
                filtered.forEach(function(g) {
                    var isSelected = !!selectedGroups[g.name];
                    html += '<div class="pg-group-item" data-name="' + _esc(g.name) + '" style="display:flex;align-items:center;justify-content:space-between;padding:8px 10px;margin-bottom:4px;border-radius:6px;cursor:pointer;'
                        + (isSelected ? 'background:#d0e4ff;font-weight:600;border:2px solid #4a90d9;' : 'background:#f6f8fa;border:1px solid #e1e4e8;')
                        + '">';
                    html += '<div style="display:flex;align-items:center;gap:6px;flex:1;min-width:0;">';
                    html += '<i class="fas fa-grip-vertical" style="color:#888;cursor:grab;flex-shrink:0;position:relative;z-index:1;"></i>';
                    html += '<span class="pg-group-name" title="单击查看路径 / Ctrl+点击多选 / 双击重命名" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + _esc(g.name) + '</span>';
                    html += '<span style="color:#888;font-size:11px;flex-shrink:0;">(' + (g.path_count || g.paths ? g.paths.length : 0) + '条)</span>';
                    html += '</div>';
                    html += '<button class="pg-group-del" data-name="' + _esc(g.name) + '" style="background:none;border:none;color:#d00;cursor:pointer;font-size:13px;flex-shrink:0;margin-left:4px;"><i class="fas fa-trash"></i></button>';
                    html += '</div>';
                });
                html += '</div>';
            } else {
                html = '<div style="color:#888;text-align:center;padding:20px;">' + (searchText ? '无匹配产品组' : '暂无产品组，在左侧树中勾选路径后点击保存') + '</div>';
            }
            $container.html(html);

            // 拖拽排序
            var el = document.getElementById('pg-group-list');
            if (el && window.Sortable) {
                if (el._sortable) el._sortable.destroy();
                window.Sortable.create(el, {
                    animation: 150,
                    handle: '.fa-grip-vertical',
                    onStart: function() {
                        wasDragging = true;
                    },
                    onEnd: function() {
                        var names = [];
                        $('#pg-group-list .pg-group-item').each(function() {
                            names.push($(this).data('name'));
                        });
                        PG.reorderGroups(names).then(function() {});
                        // 延迟清除标志位，确保 click 事件在 mouseup 后才触发时能读到
                        setTimeout(function() { wasDragging = false; }, 50);
                    }
                });
            }

            // Ctrl/Cmd+点击多选 + 普通单击查看
            $container.find('.pg-group-item').on('click', function(e) {
                if (wasDragging) return;
                if ($(e.target).closest('.pg-group-del').length) return;
                if ($(e.target).closest('.fa-grip-vertical').length) return;

                var $item = $(this);
                var name = $item.data('name');
                var isCtrl = e.ctrlKey || e.metaKey;

                if (isCtrl) {
                    // Ctrl/Cmd+点击：切换选中
                    if (selectedGroups[name]) {
                        delete selectedGroups[name];
                    } else {
                        selectedGroups[name] = true;
                    }
                    lastClickedGroup = name;
                    currentGroupName = null;
                    currentGroupDetail = null;
                    pathExpandedState = {};
                    renderGroupList();
                } else {
                    // 普通单击：清除多选，查看该组路径详情
                    selectedGroups = {};
                    lastClickedGroup = name;
                    loadGroupForEdit(name);
                }
            });

            // 双击重命名
            $container.find('.pg-group-name').on('dblclick', function(e) {
                e.stopPropagation();
                e.preventDefault();
                wasDragging = false;
                var $name = $(this);
                var oldName = $name.text().trim();
                var $inp = $('<input type="text" style="font-size:13px;padding:2px 6px;border:1px solid #4a90d9;border-radius:4px;width:100%;box-sizing:border-box;">')
                    .val(oldName);
                $name.replaceWith($inp);
                $inp.focus().select();

                function commit() {
                    var newName = $inp.val().trim();
                    if (newName && newName !== oldName) {
                        PG.renameGroup(oldName, newName).then(function() {
                            if (currentGroupName === oldName) currentGroupName = newName;
                            if (currentGroupDetail && currentGroupDetail.name === oldName) {
                                currentGroupDetail.name = newName;
                            }
                            if (selectedGroups[oldName]) {
                                delete selectedGroups[oldName];
                                selectedGroups[newName] = true;
                            }
                            renderGroupList();
                        });
                    } else {
                        $inp.replaceWith($name);
                    }
                }
                function cancel() {
                    $inp.replaceWith($name);
                }
                $inp.on('keydown', function(ev) {
                    if (ev.key === 'Enter') { ev.preventDefault(); commit(); }
                    if (ev.key === 'Escape') { ev.preventDefault(); cancel(); }
                });
                $inp.on('blur', function() {
                    if ($inp.closest('body').length) {
                        commit();
                    }
                });
            });

            // 删除按钮
            $container.find('.pg-group-del').off('click').on('click', function(e) {
                e.stopPropagation();
                var name = $(this).data('name');
                if (!confirm('删除产品组 "' + name + '"？')) return;
                PG.deleteGroup(name).then(function() {
                    if (currentGroupName === name) { currentGroupName = null; allGroupPaths = []; currentGroupDetail = null; pathExpandedState = {}; }
                    delete selectedGroups[name];
                    renderGroupList();
                    PS.clearChecks(groupTree);
                });
            });
        });
    }

    // 搜索过滤：重新渲染组列表（保持多选状态）
    function filterGroupList(searchText) {
        var $container = PS.getSubmissionContainer($managerRoot);
        if (!$container || !$container.length) return;
        var $items = $container.find('.pg-group-item');
        if (!searchText) {
            $items.show();
            return;
        }
        $items.each(function() {
            var name = ($(this).data('name') || '').toLowerCase();
            $(this).toggle(name.indexOf(searchText) !== -1);
        });
    }

    // ── 组路径详情视图（点击组后展示路径列表，点击路径查看产品） ─────

    function updateRightTitle(title) {
        var $panel = $managerRoot && $managerRoot.find('.ps-right-panel');
        if ($panel.length) {
            $panel.find('> div:first-child > div:first-child').text(title);
        }
    }

    function renderGroupPathView($container) {
        var g = currentGroupDetail;
        if (!g) { renderGroupList(); return; }
        updateRightTitle('📋 ' + g.name + ' — 路径列表');

        var html = '';
        html += '<div style="margin-bottom:8px;">';
        html += '<button class="pg-back-to-groups" style="background:none;border:1px solid #d0d5dd;border-radius:4px;padding:4px 10px;font-size:12px;cursor:pointer;color:#0078d4;">← 返回组列表</button>';
        html += '</div>';
        html += '<div style="font-size:13px;">';
        if (g.paths && g.paths.length) {
            g.paths.forEach(function(path, pi) {
                var expanded = pathExpandedState[path] || false;
                html += '<div class="pg-path-row" data-path="' + _esc(path) + '" style="border:1px solid #e1e4e8;border-radius:6px;margin-bottom:6px;overflow:hidden;">';
                html += '<div class="pg-path-header" style="padding:8px 12px;background:#f6f8fa;cursor:pointer;display:flex;align-items:center;justify-content:space-between;">';
                html += '<span class="pg-path-text" style="font-size:13px;word-break:break-word;">' + _esc(path) + '</span>';
                html += '<span class="pg-path-toggle" style="font-size:11px;color:#888;">' + (expanded ? '收起 ▲' : '展开 ▼') + '</span>';
                html += '</div>';
                if (expanded) {
                    html += '<div class="pg-path-products" id="pg-path-prods-' + pi + '" style="padding:8px 12px;background:#fafbfc;font-size:12px;color:#888;">加载中...</div>';
                }
                html += '</div>';
            });
        } else {
            html += '<div style="color:#888;text-align:center;padding:20px;">该组暂无路径</div>';
        }
        html += '</div>';

        $container.html(html);

        // 返回按钮
        $container.find('.pg-back-to-groups').on('click', function() {
            currentGroupDetail = null;
            pathExpandedState = {};
            renderGroupList();
        });

        // 点击路径头：展开/收起
        $container.find('.pg-path-header').on('click', function() {
            var $row = $(this).closest('.pg-path-row');
            var path = $row.data('path');
            var $prods = $row.find('.pg-path-products');
            var $toggle = $(this).find('.pg-path-toggle');

            if (pathExpandedState[path]) {
                pathExpandedState[path] = false;
                $prods.remove();
                $toggle.text('展开 ▼');
            } else {
                pathExpandedState[path] = true;
                // 插入加载占位
                var pi = $row.index();
                $row.append('<div class="pg-path-products" id="pg-path-prods-' + pi + '" style="padding:8px 12px;background:#fafbfc;font-size:12px;color:#888;">加载中...</div>');
                $toggle.text('收起 ▲');
                // 加载产品
                $.get('/get_products', { path: path })
                    .done(function(data) {
                        var $pc = $('#pg-path-prods-' + pi);
                        if (!$pc.length) return;
                        if (data && data.length) {
                            var h = '<div style="font-size:12px;">';
                            data.forEach(function(prod) {
                                h += '<div style="padding:2px 0;">' + _esc(prod.title) + ' <span style="color:#888;">' + _esc(prod.desc || '') + '</span></div>';
                            });
                            h += '</div>';
                            $pc.html(h);
                        } else {
                            $pc.html('<span style="color:#888;">无产品</span>');
                        }
                    })
                    .fail(function() {
                        var $pc = $('#pg-path-prods-' + pi);
                        if ($pc.length) $pc.html('<span style="color:#d00;">加载失败</span>');
                    });
            }
        });
    }

    // ── 组删除（在 renderGroupList 中绑定） ───────────────────────────────

    // ── 加载组用于编辑 ────────────────────────────────────────────────────

    async function loadGroupForEdit(name) {
        var group = await PG.fetchGroupDetail(name);
        if (!group) return;
        currentGroupName = name;
        allGroupPaths = group.paths || [];
        currentGroupDetail = { name: name, paths: allGroupPaths };
        pathExpandedState = {};
        selectedGroups = {};
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
        currentGroupDetail = null;
        pathExpandedState = {};
        allGroupPaths = [];
        selectedGroups = {};
        wasDragging = false;

        // 如果还没渲染，用 PS.render 生成统一两栏布局
        if (!$('#ps-manager-root').find('.ps-body').length) {
            PS.render($('#ps-manager-root'), {
                title: '📦 产品组管理',
                submitLabel: '💾 保存产品组',
                onSubmit: doSave,
                headerBtns: '<button id="pg-overlay-close" style="background:none;border:none;font-size:20px;cursor:pointer;color:#888;">&times;</button>',
                toolbar: '<input id="pg-search-input" type="text" placeholder="🔍 搜索产品组..." style="padding:6px 10px;border:1px solid #d0d5dd;border-radius:4px;font-size:12px;width:180px;" maxlength="50">'
                    + '<input id="pg-new-name" placeholder="新组名..." style="padding:6px 8px;border:1px solid #d0d5dd;border-radius:4px;font-size:12px;width:150px;" maxlength="30">'
                    + '<span style="font-size:12px;color:#666;">或从右侧列表点击已有组编辑</span>'
            });
            $managerRoot = $('#ps-manager-root');

            // 初始化左侧树
            PS.initLeftTree($managerRoot, {
                onInit: function(tree) { groupTree = tree; },
                onSelect: function(paths) { allGroupPaths = paths; }
            });

            // 左栏右下角拖动缩放
            if (typeof window.setupResizableTreeContainer === 'function' && !categoryTreeSizer) {
                var $leftPanel = $managerRoot.find('.ps-left-panel');
                var $treeContainer = $managerRoot.find('.ps-tree-container');
                if ($leftPanel.length && $treeContainer.length) {
                    categoryTreeSizer = window.setupResizableTreeContainer({
                        outerElement: $leftPanel[0],
                        innerElement: $treeContainer[0],
                        minWidth: 260,
                        initialWidth: 340,
                        minHeight: 150,
                        initialHeight: 420,
                        maxWidth: 'min(54vw, 620px)',
                        maxWidthFallback: 620,
                        resizeDirection: 'both',
                        desktopMediaQuery: '(max-width: 1200px)',
                        mobileInnerMaxHeight: '400px'
                    });
                }
            }

            // 关闭按钮
            $('#pg-overlay-close').on('click', closeOverlay);
            // 搜索框：输入时过滤组列表
            $('#pg-search-input').on('input', function() {
                filterGroupList($(this).val().toLowerCase());
            });

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

        // overlay 显示后同步 tree container 高度
        if (categoryTreeSizer && typeof categoryTreeSizer.sync === 'function') {
            categoryTreeSizer.sync();
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
