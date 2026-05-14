/**
 * Product Group Manager — overlay for managing named product path groups.
 * Uses ProductSelector unified two-column layout + ProductGroupShared.renderExpandableGroupList.
 * Depends on: jQuery, Fancytree, SortableJS, ProductGroupShared, ProductSelector.
 */
(function($, window) {
    'use strict';

    var PG = window.ProductGroupShared;
    var PS = window.ProductSelector;
    if (!PG) { console.error('ProductGroupShared not loaded'); return; }
    if (!PS) { console.error('ProductSelector not loaded'); return; }

    var allGroupPaths = [];
    var groupTree = null;
    var $managerRoot = null;
    var categoryTreeSizer = null;
    var selectedName = null;
    var editingName = null;                  // 输入框编辑中的组名，null = 无
    var expandedNames = {};
    var groups = [];
    var newItemPlaceholderName = null;  // placeholder 名称，null = 无

    var $overlay = $('#pg-overlay');

    function renderGroupList() {
        var $container = PS.getSubmissionContainer($managerRoot);
        if (!$container || !$container.length) return;

        PG.fetchGroups().then(function(fetched) {
            groups = fetched || [];
            var searchText = ($('#pg-search-input').val() || '').toLowerCase();
            var filtered = groups;
            if (searchText) {
                filtered = groups.filter(function(g) {
                    return g.name.toLowerCase().indexOf(searchText) !== -1;
                });
            }

            var editing = {};
            if (editingName) editing[editingName] = true;
            var sel = {};
            if (selectedName) sel[selectedName] = true;

            PG.renderExpandableGroupList(filtered, $container, {
                mode: 'manage',
                selected: sel,
                expanded: expandedNames,
                editing: editing,
                showAddButton: true,
                newItemPlaceholder: newItemPlaceholderName ? { name: newItemPlaceholderName } : null,
                dragHandle: '.pg-exp-grip',
                onAdd: function() {
                    if (newItemPlaceholderName) return;
                    selectedName = null;
                    editingName = null;
                    var now = new Date();
                    var pad = function(n) { return n < 10 ? '0' + n : '' + n; };
                    newItemPlaceholderName = now.getFullYear() + pad(now.getMonth()+1) + pad(now.getDate()) + '-' + pad(now.getHours()) + pad(now.getMinutes()) + pad(now.getSeconds());
                    allGroupPaths = [];
                    PS.clearChecks(groupTree);
                    renderGroupList();
                },
                onToggle: function(name) {
                    // 互斥：进入选中清 placeholder 和输入框编辑
                    if (newItemPlaceholderName) { newItemPlaceholderName = null; }
                    editingName = null;
                    selectedName = (selectedName === name) ? null : name;
                    if (selectedName) {
                        PS.clearChecks(groupTree);
                        PG.fetchGroupDetail(name).then(function(g) {
                            if (g && g.paths) {
                                allGroupPaths = g.paths.slice();
                                PS.restoreChecks(groupTree, allGroupPaths);
                            }
                        });
                    } else {
                        allGroupPaths = [];
                        PS.clearChecks(groupTree);
                    }
                    renderGroupList();
                },
                onExpand: function(name) {
                    expandedNames[name] = true;
                    renderGroupList();
                },
                onCollapse: function(name) {
                    delete expandedNames[name];
                    renderGroupList();
                },
                onEditName: function(name) {
                    editingName = name;
                    renderGroupList();
                },
                onSave: function(name, newName, isPlaceholder) {
                    newName = (newName || '').trim();
                    if (!newName) { editingName = null; renderGroupList(); return; }

                    var isPh = isPlaceholder || (newItemPlaceholderName && newItemPlaceholderName === name);
                    if (isPh) {
                        newItemPlaceholderName = newName;
                        if (!allGroupPaths.length) {
                            // 还没有路径 → 仅改名，退出编辑（保持 placeholder 待后续添加路径）
                            editingName = null;
                            renderGroupList();
                            return;
                        }
                        // 有路径 → 真正创建，清 placeholder
                        PG.createGroup(newName, allGroupPaths).then(function(resp) {
                            if (resp.success) {
                                newItemPlaceholderName = null;
                                selectedName = null;
                                editingName = null;
                                renderGroupList();
                            } else {
                                alert('保存失败: ' + (resp.error || '未知错误'));
                            }
                        });
                        return;
                    }

                    // 已有记录
                    if (!allGroupPaths.length) {
                        // 无路径选中 → 仅改名
                        if (newName !== name) {
                            PG.renameGroup(name, newName).then(function() {
                                if (selectedName === name) selectedName = newName;
                                if (expandedNames[name]) { delete expandedNames[name]; expandedNames[newName] = true; }
                                selectedName = null;
                                editingName = null;
                                renderGroupList();
                            });
                        } else {
                            selectedName = null;
                            editingName = null;
                            renderGroupList();
                        }
                        return;
                    }

                    var exists = groups.some(function(g) { return g.name === name; });
                    if (exists && newName !== name) {
                        // Rename + update
                        PG.renameGroup(name, newName).then(function() {
                            return PG.updateGroup(newName, allGroupPaths);
                        }).then(function(resp) {
                            if (resp && resp.success) {
                                selectedName = null;
                                editingName = null;
                                renderGroupList();
                            } else {
                                alert('保存失败: ' + ((resp && resp.error) || '未知错误'));
                            }
                        });
                    } else if (exists) {
                        PG.updateGroup(name, allGroupPaths).then(function(resp) {
                            if (resp.success) { selectedName = null; editingName = null; renderGroupList(); }
                            else { alert('保存失败: ' + (resp.error || '未知错误')); }
                        });
                    } else {
                        // New
                        PG.createGroup(newName, allGroupPaths).then(function(resp) {
                            if (resp.success) { selectedName = null; editingName = null; renderGroupList(); }
                            else { alert('保存失败: ' + (resp.error || '未知错误')); }
                        });
                    }
                },
                onDelete: function(name) {
                    // placeholder 删除 → 恢复加号行
                    if (newItemPlaceholderName && newItemPlaceholderName === name) {
                        newItemPlaceholderName = null;
                        editingName = null;
                        renderGroupList();
                        return;
                    }
                    if (!confirm('删除产品组 "' + name + '"？')) return;
                    PG.deleteGroup(name).then(function() {
                        if (selectedName === name) { selectedName = null; allGroupPaths = []; PS.clearChecks(groupTree); }
                        editingName = null;
                        delete expandedNames[name];
                        renderGroupList();
                    });
                },
                onRename: function(oldName, newName) {
                    newName = (newName || '').trim();
                    if (!newName || newName === oldName) { renderGroupList(); return; }
                    PG.renameGroup(oldName, newName).then(function() {
                        if (selectedName === oldName) selectedName = newName;
                        if (expandedNames[oldName]) { delete expandedNames[oldName]; expandedNames[newName] = true; }
                        renderGroupList();
                    });
                },
                onReorder: function(names) {
                    PG.reorderGroups(names).then(function() {});
                }
            });
        });
    }

    function openOverlay() {
        $overlay.css('display', 'flex');
        selectedName = null;
        editingName = null;
        expandedNames = {};
        allGroupPaths = [];
        groups = [];

        if (!$('#ps-manager-root').find('.ps-body').length) {
            PS.render($('#ps-manager-root'), {
                title: '📦 产品组管理',
                submitLabel: '',
                onSubmit: function() {},
                showSubmit: false,
                headerBtns: '<button id="pg-overlay-close" style="background:none;border:none;font-size:20px;cursor:pointer;color:#888;">&times;</button>',
                toolbar: '<input id="pg-search-input" type="text" placeholder="🔍 搜索产品组..." style="padding:6px 10px;border:1px solid #d0d5dd;border-radius:4px;font-size:12px;width:180px;height:32px;box-sizing:border-box;margin:0;" maxlength="50">'
            });
            $managerRoot = $('#ps-manager-root');

            PS.initLeftTree($managerRoot, {
                onInit: function(tree) { groupTree = tree; },
                onSelect: function(paths) { allGroupPaths = paths; }
            });

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

            $('#pg-overlay-close').on('click', closeOverlay);
            $('#pg-search-input').on('input', function() { renderGroupList(); });
            PS.updateLeftHint($managerRoot, '点击路径组以编辑 → 勾选品种 → 保存');
        } else {
            $managerRoot = $('#ps-manager-root');
            PS.clearChecks(groupTree);
        }

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

})(jQuery, window);
