/**
 * Product Group Manager — overlay for managing named product path groups.
 * Used in products.html (price viewer / product management page).
 * Depends on: jQuery, Fancytree (loaded in products.html).
 * Expects: treeInstance (main page Fancytree) in outer scope.
 */
(function($, window) {
    'use strict';

    var escHtml = window.escHtml || function(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    };

    var currentGroupName = null;
    var allGroupPaths = [];  // product_name array of the currently editing group
    var groupTreeInstance = null;

    var $overlay = $('#pg-overlay');
    var $groupList = $('#pg-group-list');
    var $selectedCount = $('#pg-selected-count');
    var $newName = $('#pg-new-name');
    var $treeContainer = $('#pg-tree-container');

    // ── API helpers ──
    async function api(method, url, body) {
        var opts = { method: method, headers: {'Content-Type': 'application/json'} };
        if (body) opts.body = JSON.stringify(body);
        var resp = await fetch(url, opts);
        return resp.json();
    }

    async function listGroups() {
        return (await api('GET', '/api/product-groups')).groups || [];
    }

    async function saveGroup(name, paths) {
        return api('POST', '/api/product-groups', {name: name, paths: paths});
    }

    async function updateGroup(name, paths) {
        return api('PUT', '/api/product-groups/' + encodeURIComponent(name), {paths: paths});
    }

    async function deleteGroup(name) {
        return api('DELETE', '/api/product-groups/' + encodeURIComponent(name));
    }

    // ── Build all product paths from the main Fancytree ──
    function collectProductPaths() {
        var paths = [];
        var tree = window._mainTreeInstance || (typeof treeInstance !== 'undefined' ? treeInstance : null);
        if (!tree) return paths;
        tree.visit(function(node) {
            if (node.data && node.data.product_name && node.data.has_data !== false) {
                paths.push({key: node.key, name: node.data.product_name, desc: node.data.desc || ''});
            }
        });
        return paths;
    }

    // ── Render group list ──
    async function renderGroupList() {
        var groups = await listGroups();
        var html = '';
        for (var i = 0; i < groups.length; i++) {
            var g = groups[i];
            var cnt = g.path_count || (g.paths ? g.paths.length : 0);
            var active = g.name === currentGroupName ? ' style="background:#e8f0fe; font-weight:600;"' : '';
            html += '<div class="pg-group-item" data-name="' + escHtml(g.name) + '"' + active + '>' +
                '<span style="flex:1; cursor:pointer;" class="pg-group-name">' + escHtml(g.name) + ' (' + cnt + ')</span>' +
                '<button class="pg-group-del" data-name="' + escHtml(g.name) + '" title="删除" style="background:none; border:none; color:#d32f2f; cursor:pointer; font-size:14px;">&times;</button>' +
            '</div>';
        }
        $groupList.html(html || '<div style="color:#888; font-size:12px;">暂无产品组</div>');

        $groupList.find('.pg-group-item').css({
            display:'flex', alignItems:'center', padding:'6px 8px', marginBottom:'2px',
            borderRadius:'4px', cursor:'pointer', fontSize:'12px', border:'1px solid transparent'
        }).hover(
            function() {
                var name = $(this).find('.pg-group-name').text().split(' (')[0];
                if (name !== (currentGroupName||'')) $(this).css('background','#f0f4f8');
            },
            function() {
                var name = $(this).find('.pg-group-name').text().split(' (')[0];
                if (name !== (currentGroupName||'')) $(this).css('background','transparent');
            }
        );

        $groupList.find('.pg-group-name').off('click').on('click', function() {
            var name = $(this).text().split(' (')[0];
            loadGroupForEdit(name);
        });

        $groupList.find('.pg-group-del').off('click').on('click', async function(e) {
            e.stopPropagation();
            var name = $(this).data('name');
            if (!confirm('删除产品组 "' + name + '"？')) return;
            await deleteGroup(name);
            if (currentGroupName === name) { currentGroupName = null; allGroupPaths = []; }
            renderGroupList();
            refreshTreeChecks();
        });
    }

    // ── Tree: init group picker Fancytree ──
    async function initGroupTree() {
        await new Promise(function(r) { setTimeout(r, 200); });

        $treeContainer.empty();
        $treeContainer.fancytree({
            source: {url: '/api/product_tree'},
            checkbox: true,
            selectMode: 2,
            init: function(event, data) {
                groupTreeInstance = data.tree;
            },
            lazyLoad: function(event, data) {
                var node = data.node;
                if (node.key && node.key.indexOf('CNFuturesContract') >= 0) {
                    data.result = { url: '/api/contract_tree', data: {path: node.key} };
                    return;
                }
                data.result = { url: '/get_products', data: {path: node.key, checkbox: 'true'} };
            },
            loadChildren: function(event, data) {
                restoreTreeChecks();
            },
            select: function(event, data) {
                if (data.node.data && data.node.data.product_name) {
                    var pname = data.node.data.product_name;
                    var idx = allGroupPaths.indexOf(pname);
                    if (data.node.selected && idx < 0) {
                        allGroupPaths.push(pname);
                    } else if (!data.node.selected && idx >= 0) {
                        allGroupPaths.splice(idx, 1);
                    }
                    $selectedCount.text(allGroupPaths.length);
                }
            }
        });
    }

    function restoreTreeChecks() {
        if (!groupTreeInstance) return;
        groupTreeInstance.visit(function(node) {
            if (node.data && node.data.product_name) {
                node.setSelected(allGroupPaths.indexOf(node.data.product_name) >= 0);
            }
        });
    }

    function refreshTreeChecks() {
        restoreTreeChecks();
        $selectedCount.text(allGroupPaths.length);
    }

    async function loadGroupForEdit(name) {
        var resp = await api('GET', '/api/product-groups/' + encodeURIComponent(name));
        if (!resp.group) return;
        currentGroupName = name;
        allGroupPaths = resp.group.paths || [];
        $newName.val(name);
        refreshTreeChecks();
        renderGroupList();
    }

    // ── Save/New group ──
    async function doSave() {
        var name = $newName.val().trim();
        if (!name) { alert('请输入组名'); return; }
        if (!allGroupPaths.length) { alert('请至少选择一个品种'); return; }

        var resp;
        if (currentGroupName && currentGroupName !== name) {
            await deleteGroup(currentGroupName);
            resp = await saveGroup(name, allGroupPaths);
        } else if (currentGroupName === name) {
            resp = await updateGroup(name, allGroupPaths);
        } else {
            resp = await saveGroup(name, allGroupPaths);
        }

        if (resp.success) {
            currentGroupName = name;
            renderGroupList();
        } else {
            alert('保存失败: ' + (resp.error || '未知错误'));
        }
    }

    // ── Open/Close overlay ──
    function openOverlay() {
        $overlay.css('display', 'flex');
        currentGroupName = null;
        allGroupPaths = [];
        $newName.val('');
        $selectedCount.text('0');
        renderGroupList();
        if (!groupTreeInstance) {
            initGroupTree();
        } else {
            refreshTreeChecks();
        }
    }

    function closeOverlay() {
        $overlay.css('display', 'none');
    }

    // ── Export ──
    window.openProductGroupManager = openOverlay;

    // ── Bind events ──
    $('#btn-product-groups').on('click', openOverlay);
    $('#pg-overlay-close').on('click', closeOverlay);
    $('#pg-overlay').on('click', function(e) { if (e.target === this) closeOverlay(); });
    $('#pg-btn-save').on('click', doSave);
    $('#pg-new-name').on('keydown', function(e) { if (e.key === 'Enter') doSave(); });

})(jQuery, window);
