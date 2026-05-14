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
    var expandedNames = {};
    var groups = [];

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
            if (selectedName) editing[selectedName] = true;
            var sel = {};
            if (selectedName) sel[selectedName] = true;

            PG.renderExpandableGroupList(filtered, $container, {
                mode: 'manage',
                selected: sel,
                expanded: expandedNames,
                editing: editing,
                showAddButton: true,
                dragHandle: '.pg-exp-grip',
                onAdd: function() {
                    var now = new Date();
                    var pad = function(n) { return n < 10 ? '0' + n : '' + n; };
                    var defaultName = now.getFullYear() + pad(now.getMonth()+1) + pad(now.getDate()) + '-' + pad(now.getHours()) + pad(now.getMinutes()) + pad(now.getSeconds());
                    groups.push({ name: defaultName, paths: [], path_count: 0 });
                    selectedName = defaultName;
                    allGroupPaths = [];
                    PS.clearChecks(groupTree);
                    renderGroupList();
                },
                onToggle: function(name) {
                    if (selectedName === name) {
                        selectedName = null;
                        allGroupPaths = [];
                        PS.clearChecks(groupTree);
                    } else {
                        selectedName = name;
                        PS.clearChecks(groupTree);
                        PG.fetchGroupDetail(name).then(function(g) {
                            if (g && g.paths) {
                                allGroupPaths = g.paths.slice();
                                PS.restoreChecks(groupTree, allGroupPaths);
                            }
                        });
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
                onSave: function(name, newName) {
                    newName = (newName || '').trim();
                    if (!newName) { alert('组名不能为空'); return; }
                    if (!allGroupPaths.length) { alert('请在左侧树中勾选至少一个品种'); return; }

                    var exists = groups.some(function(g) { return g.name === name; });
                    if (exists && newName !== name) {
                        // Rename + update
                        PG.renameGroup(name, newName).then(function() {
                            return PG.updateGroup(newName, allGroupPaths);
                        }).then(function(resp) {
                            if (resp && resp.success) {
                                selectedName = newName;
                                renderGroupList();
                            } else {
                                alert('保存失败: ' + ((resp && resp.error) || '未知错误'));
                            }
                        });
                    } else if (exists) {
                        PG.updateGroup(name, allGroupPaths).then(function(resp) {
                            if (resp.success) { selectedName = name; renderGroupList(); }
                            else { alert('保存失败: ' + (resp.error || '未知错误')); }
                        });
                    } else {
                        // New
                        PG.createGroup(newName, allGroupPaths).then(function(resp) {
                            if (resp.success) { selectedName = newName; renderGroupList(); }
                            else { alert('保存失败: ' + (resp.error || '未知错误')); }
                        });
                    }
                },
                onDelete: function(name) {
                    if (!confirm('删除产品组 "' + name + '"？')) return;
                    PG.deleteGroup(name).then(function() {
                        if (selectedName === name) { selectedName = null; allGroupPaths = []; PS.clearChecks(groupTree); }
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
                toolbar: '<input id="pg-search-input" type="text" placeholder="🔍 搜索产品组..." style="padding:6px 10px;border:1px solid #d0d5dd;border-radius:4px;font-size:12px;width:180px;height:32px;box-sizing:border-box;" maxlength="50">'
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
            PS.updateLeftHint($managerRoot, '点击选中产品组 → 勾选品种 → 保存');
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
