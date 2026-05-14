/**
 * Product Selector — 统一产品选择器共享组件。
 *
 * 提供统一的左右两栏布局：
 *   ┌──────────────────────────────────────────────┐
 *   │  Header: 标题 + 操作按钮（由调用方传入）           │
 *   ├──────────────────────────────────────────────┤
 *   │  Toolbar（由调用方传入）                         │
 *   ├──────────────┬───────────────────────────────┤
 *   │  左侧：树/列表  │  右侧：已选路径面板               │
 *   └──────────────┴───────────────────────────────┘
 *
 * 三种模式（通过调用方式区分行为，布局统一）：
 *   - 'drawer'   单因子抽屉：提交 FactorTester + 拖拽重命名 + 删除
 *   - 'manager'  产品组管理：保存产品组 + 拖拽重命名 + 删除组
 *   - 'import'   产品组导入弹窗：左右两栏只读预览 + 导入按钮
 *
 * 依赖：jQuery, Fancytree, SortableJS, ProductGroupShared
 */
(function($, window) {
    'use strict';

    var PG = window.ProductGroupShared;

    var _escHtml = window.escHtml || function(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    };

    // ═══════════════════════════════════════════════════════════════════════════
    // Tree helpers
    // ═══════════════════════════════════════════════════════════════════════════

    function getMinimalPaths(tree) {
        if (!tree) return [];
        var sel = tree.getSelectedNodes();
        var keySet = {};
        sel.forEach(function(n) { keySet[n.key] = true; });
        return sel.filter(function(n) {
            var p = n.parent;
            while (p && p.key) { if (keySet[p.key]) return false; p = p.parent; }
            return true;
        }).map(function(n) { return n.key; });
    }

    function restoreChecks(tree, paths) {
        if (!tree || !paths) return;
        var set = {};
        paths.forEach(function(p) { set[p] = true; });
        tree.visit(function(n) { if (n.key && set[n.key]) n.setSelected(true); });
    }

    function clearChecks(tree) {
        if (!tree) return;
        tree.visit(function(n) { n.setSelected(false); });
    }

    function createTree($container, opts) {
        opts = opts || {};
        $container.empty();
        $container.fancytree({
            source: { url: '/api/product_tree?checkbox=1' },
            checkbox: true,
            selectMode: 3,
            init: function(e, data) {
                if (opts.onInit) opts.onInit(data.tree);
            },
            lazyLoad: function(e, data) {
                var node = data.node;
                if (node.key && node.key.indexOf('CNFuturesContract') >= 0) {
                    data.result = { url: '/api/contract_tree', data: { path: node.key } };
                    return;
                }
                data.result = { url: '/get_products', data: { path: node.key } };
            },
            select: function(e, data) {
                if (opts.onSelect) opts.onSelect(getMinimalPaths(data.tree));
            },
            renderNode: function(e, data) {
                var desc = data.node.data.desc;
                if (desc) {
                    var $t = $(data.node.span).find('.fancytree-title');
                    $t.siblings('.node-description').remove();
                    $t.after('<span class="node-description" style="color:#888;margin-left:8px;font-size:12px;">' + _escHtml(desc) + '</span>');
                }
            }
        });
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // 统一布局渲染
    // ═══════════════════════════════════════════════════════════════════════════

    function render($container, opts) {
        opts = opts || {};
        var title = opts.title || '🌳 产品类别筛选';
        var submitLabel = opts.submitLabel || '';
        var toolbar = opts.toolbar || '';
        var headerBtns = opts.headerBtns || '';

        var html = '';

        // Header
        html += '<div class="ps-header" style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:#fff;border-radius:12px 12px 0 0;border:1px solid #e1e4e8;border-bottom:none;">';
        html += '<div style="display:flex;align-items:center;gap:12px;">';
        html += '<span style="font-size:16px;font-weight:600;">' + _escHtml(title) + '</span>';
        if (opts.onSubmit && submitLabel) {
            html += '<button type="button" class="ps-submit-btn" style="background:#0078d4;color:#fff;border:none;border-radius:6px;padding:6px 16px;font-size:13px;cursor:pointer;">' + _escHtml(submitLabel) + '</button>';
            html += '<span class="ps-submit-status" style="font-size:13px;color:#28a745;"></span>';
        }
        html += '</div>';
        html += '<div style="display:flex;align-items:center;gap:8px;">';
        html += headerBtns;
        html += '<span class="ps-change-status" style="font-size:12px;color:#28a745;"></span>';
        html += '</div>';
        html += '</div>';

        // Toolbar
        if (toolbar) {
            html += '<div class="ps-toolbar" style="display:flex;align-items:center;gap:8px;padding:10px 16px;background:#f6f8fa;border-left:1px solid #e1e4e8;border-right:1px solid #e1e4e8;flex-wrap:wrap;">';
            html += toolbar;
            html += '</div>';
        }

        // Body: 左右两栏
        html += '<div class="ps-body" style="display:flex;background:#fff;border:1px solid #e1e4e8;border-top:none;border-radius:0 0 12px 12px;min-height:420px;">';
        html += '<div class="ps-left-panel" style="flex:1;min-width:260px;padding:16px;border-right:1px solid #e1e4e8;">';
        html += '<div class="ps-left-content"></div>';
        html += '</div>';
        html += '<div class="ps-right-panel" style="flex:1.5;min-width:280px;padding:16px;display:flex;flex-direction:column;">';
        html += '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;flex-shrink:0;">';
        html += '<div style="font-size:15px;font-weight:600;">📋 已选路径列表</div>';
        html += '</div>';
        html += '<div style="font-size:12px;color:#586069;margin-bottom:8px;flex-shrink:0;">💡 拖拽提交记录可调整顺序，点击路径可查看产品详情</div>';
        html += '<div class="ps-submission-history" style="flex:1;min-height:0;overflow-y:auto;overflow-x:hidden;padding-right:4px;"></div>';
        html += '</div>';
        html += '</div>';

        $container.html(html);

        if (opts.onSubmit) {
            $container.find('.ps-submit-btn').on('click', function() { opts.onSubmit(); });
        }
    }

    function initLeftTree($container, treeOpts) {
        var $left = $container.find('.ps-left-content');
        $left.html('<div style="margin-bottom:8px;color:#586069;font-size:13px;">树状结构，勾选叶子节点或分类后提交</div>'
            + '<div class="ps-tree-container" style="width:100%;box-sizing:border-box;max-height:500px;overflow:auto;border:1px solid #e1e4e8;border-radius:8px;padding:8px;background:#fff;"></div>');
        createTree($left.find('.ps-tree-container'), treeOpts);
    }

    function getSubmissionContainer($container) {
        return $container.find('.ps-submission-history');
    }

    function getStatusEl($container) {
        return $container.find('.ps-submit-status');
    }

    function getChangeStatusEl($container) {
        return $container.find('.ps-change-status');
    }

    function updateLeftHint($container, hint) {
        $container.find('.ps-left-content > div:first-child').text(hint || '树状结构，勾选叶子节点或分类后提交');
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // Submission history rendering
    // ═══════════════════════════════════════════════════════════════════════════

    function renderSubmissionHistory(submissions, expandedState, $container, callbacks) {
        callbacks = callbacks || {};
        var onReorder = callbacks.onReorder || function() {};
        var onDeleteSub = callbacks.onDeleteSub || function() {};
        var onDeletePath = callbacks.onDeletePath || function() {};
        var onLabelChange = callbacks.onLabelChange || function() {};
        var onPathClick = callbacks.onPathClick || function() {};

        var html = '';
        submissions.forEach(function(sub, index) {
            var isExpanded = expandedState[index] || {};
            html += '<div class="submission-item" data-index="' + index + '" style="border:1px solid #e1e4e8;border-radius:8px;margin-bottom:12px;background:#fff;overflow:hidden;">';
            html += '<div class="submission-header" style="background:#f6f8fa;padding:8px 36px 8px 12px;cursor:move;position:relative;border-bottom:1px solid #e1e4e8;">';
            var lblHtml = sub.label
                ? '<span class="sub-label-text" data-index="' + index + '" title="点击重命名" style="color:#0078d4;font-weight:600;cursor:pointer;font-size:12px;">' + _escHtml(sub.label) + '</span>'
                : '<span class="sub-label-add" data-index="' + index + '" title="点击添加名称" style="color:#aaa;cursor:pointer;font-size:12px;">[添加名称]</span>';
            var lblInp = '<input class="sub-label-input" data-index="' + index + '" type="text" value="' + _escHtml(sub.label||'') + '" placeholder="输入名称后 Enter 确认" style="display:none;font-size:12px;padding:2px 6px;border:1px solid #0078d4;border-radius:4px;width:140px;">';
            html += '<div style="font-size:13px;display:flex;align-items:center;gap:4px;flex-wrap:wrap;margin-bottom:4px;">'
                + '<i class="fas fa-grip-vertical" style="color:#888;"></i>'
                + '<strong>#' + (index+1) + '</strong>'
                + '<span>' + _escHtml(sub.factor_tester_serial || '') + '</span>'
                + '<span style="color:#888;font-size:12px;">(' + _escHtml(sub.timestamp || '') + ')</span>'
                + (sub.count_desc ? ' <span style="color:#d00;">' + _escHtml(sub.count_desc) + '</span>' : '')
                + '</div>';
            html += '<div style="line-height:24px;min-height:24px;">' + lblHtml + lblInp;
            if (sub.product_group) {
                html += ' <span style="background:#6c63ff;color:#fff;font-size:10px;padding:1px 6px;border-radius:8px;">📦 ' + _escHtml(sub.product_group) + '</span>';
            }
            html += '</div>';
            html += '<button class="delete-submission" data-index="' + index + '" style="position:absolute;right:8px;bottom:8px;background:none;border:none;color:#d00;cursor:pointer;font-size:14px;"><i class="fas fa-trash"></i></button>';
            html += '</div>';

            html += '<div style="padding:8px 12px;overflow-x:auto;">';
            html += '<table style="width:100%;border-collapse:collapse;">';
            sub.paths.forEach(function(path, pi) {
                var expanded = isExpanded[path] || false;
                var pathDisplay = path;
                if (sub.pathsDescMap && sub.pathsDescMap[path]) {
                    pathDisplay = path + ' <span style="color:#888;font-size:12px;">' + _escHtml(sub.pathsDescMap[path]) + '</span>';
                }
                html += '<tr class="path-row" data-path="' + _escHtml(path) + '" data-sub-index="' + index + '" data-path-index="' + pi + '">';
                html += '<td style="padding:4px 0;border-bottom:1px solid #f0f0f0;">';
                html += '<div style="display:flex;align-items:flex-start;">';
                html += '<span class="path-text" style="cursor:pointer;font-size:13px;margin-left:6px;flex:1;word-break:break-word;">' + pathDisplay + '</span>';
                if (!sub.product_group) {
                    html += '<button class="delete-path" data-sub-index="' + index + '" data-path-index="' + pi + '" style="flex-shrink:0;background:none;border:none;color:#d00;cursor:pointer;padding:0 8px;"><i class="fas fa-times"></i></button>';
                }
                html += '</div></td></tr>';
                if (expanded) {
                    html += '<tr class="product-detail-row" id="detail-' + index + '-' + pi + '">';
                    html += '<td style="padding:8px 0 8px 20px;background:#fafbfc;"><div class="loading-products" style="font-size:13px;">加载中...</div></td></tr>';
                }
            });
            html += '</table></div>';
            html += '</div>';
        });

        $container.html(html || '<div style="color:#888;text-align:center;padding:20px;">暂无提交记录</div>');

        $container.find('.path-text').off('click').on('click', function() {
            var $row = $(this).closest('tr.path-row');
            var subIndex = $row.data('sub-index');
            var path = $row.data('path');
            var pathIndex = $row.data('path-index');
            var expanded = expandedState[subIndex] || {};
            if (expanded[path]) {
                $('#detail-' + subIndex + '-' + pathIndex).remove();
                delete expanded[path];
            } else {
                expanded[path] = true;
                var detailHtml = '<tr class="product-detail-row" id="detail-' + subIndex + '-' + pathIndex + '">'
                    + '<td style="padding:8px 0 8px 20px;background:#fafbfc;">'
                    + '<div class="loading-products" style="font-size:13px;">加载中...</div></td></tr>';
                $row.after(detailHtml);
                onPathClick(path, subIndex, pathIndex);
            }
            expandedState[subIndex] = expanded;
        });

        $container.find('.delete-path').off('click').on('click', function() {
            onDeletePath(
                parseInt($(this).data('sub-index'), 10),
                parseInt($(this).data('path-index'), 10)
            );
        });

        $container.find('.delete-submission').off('click').on('click', function() {
            onDeleteSub(parseInt($(this).data('index'), 10));
        });

        $container.off('click.rename').on('click.rename', '.sub-label-text, .sub-label-add', function() {
            var idx = $(this).data('index');
            $(this).hide();
            $container.find('.sub-label-input[data-index="' + idx + '"]').show().focus().select();
        });

        function commitLabelEdit($inp) {
            var idx = parseInt($inp.data('index'), 10);
            var val = $inp.val().trim();
            if (idx >= 0 && idx < submissions.length) {
                submissions[idx].label = val || '';
            }
            $inp.hide();
            var $lbl = $container.find('.sub-label-text[data-index="' + idx + '"], .sub-label-add[data-index="' + idx + '"]');
            if (val) {
                $lbl.replaceWith('<span class="sub-label-text" data-index="' + idx + '" title="点击重命名" style="color:#0078d4;font-weight:600;cursor:pointer;font-size:12px;">' + _escHtml(val) + '</span>');
            } else {
                $lbl.replaceWith('<span class="sub-label-add" data-index="' + idx + '" title="点击添加名称" style="color:#aaa;cursor:pointer;font-size:12px;">[添加名称]</span>');
            }
            onLabelChange(idx, val);
        }

        $container.off('keydown.rename').on('keydown.rename', '.sub-label-input', function(e) {
            if (e.key === 'Enter') commitLabelEdit($(this));
            if (e.key === 'Escape') { $(this).hide(); $container.find('.sub-label-text[data-index="' + $(this).data('index') + '"], .sub-label-add[data-index="' + $(this).data('index') + '"]').show(); }
        });

        $container.off('blur.rename').on('blur.rename', '.sub-label-input', function() {
            if ($(this).is(':visible')) commitLabelEdit($(this));
        });

        var el = $container[0];
        if (el && window.Sortable) {
            if (el._sortable) el._sortable.destroy();
            window.Sortable.create(el, {
                animation: 150,
                handle: '.submission-header',
                onEnd: function(evt) {
                    var moved = submissions.splice(evt.oldIndex, 1)[0];
                    submissions.splice(evt.newIndex, 0, moved);
                    onReorder();
                }
            });
        }
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // 组导入弹窗
    // ═══════════════════════════════════════════════════════════════════════════

    function openGroupImport(onImport) {
        PG.fetchGroups().then(function(groups) {
            if (!groups || !groups.length) {
                alert('暂无产品组，请先在产品管理页面创建。');
                return;
            }
            var html = '<div id="ps-import-overlay" style="position:fixed;inset:0;background:rgba(0,0,0,0.4);display:flex;align-items:center;justify-content:center;z-index:10000;">'
                + '<div style="background:#fff;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.2);width:700px;max-width:95vw;max-height:80vh;display:flex;flex-direction:column;">'
                + '<div style="display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid #e1e4e8;">'
                + '<h3 style="margin:0;font-size:16px;">📥 从产品组导入</h3>'
                + '<button id="ps-import-close" style="background:none;border:none;font-size:20px;cursor:pointer;color:#888;">&times;</button>'
                + '</div>'
                + '<div style="display:flex;flex:1;min-height:0;overflow:hidden;">'
                + '<div style="width:200px;min-width:160px;border-right:1px solid #e1e4e8;overflow-y:auto;padding:12px;">'
                + '<div id="ps-import-group-list" style="font-size:13px;">' + PG.renderGroupListHTML(groups, null, {showDelete:false, itemClass:'ps-import-item'}) + '</div>'
                + '</div>'
                + '<div style="flex:1;overflow-y:auto;padding:16px;">'
                + '<div id="ps-import-detail" style="color:#888;text-align:center;padding:40px 0;">← 选择左侧产品组查看详情</div>'
                + '</div>'
                + '</div>'
                + '<div style="display:flex;justify-content:flex-end;gap:8px;padding:12px 20px;border-top:1px solid #e1e4e8;">'
                + '<button id="ps-import-cancel" style="padding:6px 18px;border:1px solid #ddd;border-radius:6px;background:#fff;color:#333;cursor:pointer;font-size:13px;">取消</button>'
                + '<button id="ps-import-confirm" style="padding:6px 18px;border:none;border-radius:6px;background:#6c63ff;color:#fff;cursor:pointer;font-size:13px;" disabled>导入</button>'
                + '</div></div></div>';

            var $ov = $(html).appendTo('body');
            var selectedName = null;

            function close() { $ov.remove(); }
            $('#ps-import-close, #ps-import-cancel').on('click', close);
            $ov.on('click', function(e) { if (e.target === this) close(); });

            var $detail = $('#ps-import-detail');
            var $confirm = $('#ps-import-confirm');

            $('#ps-import-group-list').on('click', '.ps-import-item', function() {
                var name = $(this).data('name');
                selectedName = name;
                $confirm.prop('disabled', false);
                $('#ps-import-group-list').find('.ps-import-item').css({background:'',fontWeight:''});
                $(this).css({background:'#e8f0fe',fontWeight:'600'});
                PG.fetchGroupDetail(name).then(function(g) {
                    if (g) {
                        $detail.empty();
                        PG.renderGroupDetail(g, $detail, g.name);
                    }
                });
            });

            $confirm.on('click', function() {
                if (!selectedName) return;
                PG.fetchGroupDetail(selectedName).then(function(g) {
                    if (!g || !g.paths) { alert('产品组路径为空'); return; }
                    onImport(selectedName, g.paths);
                    close();
                });
            });

            if (groups.length > 0) $('#ps-import-group-list').find('.ps-import-item').first().trigger('click');
        });
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // Export
    // ═══════════════════════════════════════════════════════════════════════════

    window.ProductSelector = {
        render: render,
        initLeftTree: initLeftTree,
        getSubmissionContainer: getSubmissionContainer,
        getStatusEl: getStatusEl,
        getChangeStatusEl: getChangeStatusEl,
        updateLeftHint: updateLeftHint,
        createTree: createTree,
        getMinimalPaths: getMinimalPaths,
        restoreChecks: restoreChecks,
        clearChecks: clearChecks,
        renderSubmissionHistory: renderSubmissionHistory,
        openGroupImport: openGroupImport
    };

})(jQuery, window);
