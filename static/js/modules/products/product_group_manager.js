/**
 * Product Group Manager — overlay for managing named product path groups.
 * Used in products.html (price viewer / product management page).
 * Depends on: jQuery, Fancytree, ProductGroupShared, ProductSelector.
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

    var $overlay = $('#pg-overlay');
    var $groupList = $('#pg-group-list');
    var $selectedCount = $('#pg-selected-count');
    var $newName = $('#pg-new-name');
    var $treeContainer = $('#pg-tree-container');
    var $groupDetail = $('#pg-group-detail');

    async function renderGroupList() {
        var groups = await PG.fetchGroups();
        $groupList.html(PG.renderGroupListHTML(groups, currentGroupName, null));
    }

    function initGroupTree() {
        PS.createTree($treeContainer, {
            onInit: function(tree) { groupTree = tree; },
            onSelect: function(paths) {
                allGroupPaths = paths;
                $selectedCount.text(paths.length);
            }
        });
    }

    async function loadGroupForEdit(name) {
        var group = await PG.fetchGroupDetail(name);
        if (!group) return;
        currentGroupName = name;
        allGroupPaths = group.paths || [];
        $newName.val(name);
        PS.clearChecks(groupTree);
        PS.restoreChecks(groupTree, allGroupPaths);
        $selectedCount.text(allGroupPaths.length);
        renderGroupList();
        PG.renderGroupDetail(group, $groupDetail, '📦 ' + name);
        $groupDetail.show();
    }

    async function doSave() {
        var name = $newName.val().trim();
        if (!name) { alert('请输入组名'); return; }
        if (!allGroupPaths.length) { alert('请至少选择一个品种'); return; }

        var resp;
        if (currentGroupName) {
            if (currentGroupName !== name) {
                await PG.deleteGroup(currentGroupName);
                resp = await PG.createGroup(name, allGroupPaths);
            } else {
                resp = await PG.updateGroup(name, allGroupPaths);
            }
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

    function openOverlay() {
        $overlay.css('display', 'flex');
        currentGroupName = null;
        allGroupPaths = [];
        $newName.val('');
        $selectedCount.text('0');
        $groupDetail.hide().empty();
        renderGroupList();
        if (!groupTree) {
            initGroupTree();
        } else {
            PS.clearChecks(groupTree);
            $selectedCount.text('0');
        }
    }

    function closeOverlay() {
        $overlay.css('display', 'none');
    }

    window.openProductGroupManager = openOverlay;

    $('#btn-product-groups').on('click', openOverlay);
    $('#pg-overlay-close').on('click', closeOverlay);
    $('#pg-overlay').on('click', function(e) { if (e.target === this) closeOverlay(); });
    $('#pg-btn-save').on('click', doSave);
    $('#pg-new-name').on('keydown', function(e) { if (e.key === 'Enter') doSave(); });

    $groupList.on('click', '.pg-group-name', function() {
        loadGroupForEdit($(this).closest('.pg-group-item').data('name'));
    });
    $groupList.on('click', '.pg-group-del', async function(e) {
        e.stopPropagation();
        var name = $(this).data('name');
        if (!confirm('删除产品组 "' + name + '"？')) return;
        await PG.deleteGroup(name);
        if (currentGroupName === name) { currentGroupName = null; allGroupPaths = []; }
        renderGroupList();
        PS.clearChecks(groupTree);
        $selectedCount.text('0');
    });
    $groupList.on('mouseenter', '.pg-group-item', function() {
        if ($(this).data('name') !== currentGroupName) $(this).css('background','#f0f4f8');
    });
    $groupList.on('mouseleave', '.pg-group-item', function() {
        if ($(this).data('name') !== currentGroupName) $(this).css('background','');
    });

})(jQuery, window);
