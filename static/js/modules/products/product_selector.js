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
        html += '<div style="font-size:12px;color:#586069;margin-bottom:8px;flex-shrink:0;">💡 拖拽提交路径组可调整顺序，点击路径组以编辑</div>';
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
            + '<div class="ps-tree-container" style="width:100%;box-sizing:border-box;height:100%;min-height:300px;overflow:auto;border:1px solid #e1e4e8;border-radius:8px;padding:8px;background:#fff;"></div>');
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
        var onAdd = callbacks.onAdd || null;
        var onImportGroup = callbacks.onImportGroup || null;
        var newItemPlaceholder = callbacks.newItemPlaceholder || null;  // {name} | null

        var onInsertPlaceholder = callbacks.onInsertPlaceholder || null;
        var onDeletePlaceholder = callbacks.onDeletePlaceholder || null;
        var onRename = callbacks.onRename || null;
        var onSave = callbacks.onSave || null;                 // 统一保存回调（替代 onInsertPlaceholder/onRename）
        var onExitEdit = callbacks.onExitEdit || null;         // 退出编辑回调（Enter/blur/单击已编辑行）

        var editingName = callbacks.editingName || null;       // 当前编辑中的记录标识（CF传sub.id，PG-manager传组名）
        var onToggleEdit = callbacks.onToggleEdit || null;     // 点击进入编辑模式，参数：editingName（与editingName同键）

        // 映射成 expandable 格式：优先显示产品组名（带标示），否则 #N + serial
        // displayName 必须唯一，用 sub.id 保证唯一性以支持单选编辑模式
        var expItems = submissions.map(function(sub, i) {
            var isFromGroup = !!sub.product_group;
            var displayName;
            if (isFromGroup) {
                displayName = '📦 ' + sub.product_group;
            } else {
                displayName = '#' + (i + 1) + ' ' + (sub.factor_tester_serial || '');
            }
            return {
                name: displayName,
                paths: sub.paths || [],
                _index: i,
                _sub: sub,
                _fromGroup: isFromGroup
            };
        });

        var expExpanded = {};
        expItems.forEach(function(item) {
            if (expandedState[item._index]) {
                expExpanded[item.name] = true;
            }
        });

        var editing = {};
        if (editingName != null) {
            // editingName 存的是 sub.id（CF）或组名（PG-manager）；映射到 displayName
            var editItem = expItems.find(function(item) {
                // CF：通过 _sub.id 匹配；PG-manager：直接用组名匹配
                return (item._sub && String(item._sub.id) === String(editingName)) || (item.name === editingName);
            });
            if (editItem) editing[editItem.name] = true;
        }

        PG.renderExpandableGroupList(expItems, $container, {
            mode: 'manage',
            selected: {},
            expanded: expExpanded,
            editing: editing,
            showAddButton: !!(onAdd || onImportGroup),
            newItemPlaceholder: newItemPlaceholder,
            dragHandle: '.pg-exp-grip',
            onAdd: function() {
                if (onAdd) onAdd();
            },
            onToggle: function(name) {
                // 点击已有记录行 → 进入编辑模式
                if (name && name !== (newItemPlaceholder && newItemPlaceholder.name) && onToggleEdit) {
                    onToggleEdit(name);
                }
            },
            onSave: function(name, newName, isPlaceholder) {
                if (onSave) {
                    onSave(name, newName, isPlaceholder);
                } else if (isPlaceholder && onInsertPlaceholder) {
                    onInsertPlaceholder(newName);
                } else if (!isPlaceholder && onRename) {
                    onRename(name, newName);
                }
            },
            onExitEdit: function(name, newName, isPlaceholder) {
                if (onExitEdit) onExitEdit(name, newName, isPlaceholder);
            },
            onRename: onRename,
            onExpand: function(name) {
                var found = expItems.find(function(item) { return item.name === name; });
                if (found) {
                    expandedState[found._index] = expandedState[found._index] || {};
                }
            },
            onCollapse: function(name) {
                var found = expItems.find(function(item) { return item.name === name; });
                if (found) {
                    delete expandedState[found._index];
                }
            },
            onDeletePath: function(name, path) {
                var found = expItems.find(function(item) { return item.name === name; });
                if (found && onDeletePath) {
                    var pi = (found.paths || []).indexOf(path);
                    if (pi >= 0) onDeletePath(found._index, pi);
                }
            },
            onDelete: function(name) {
                // placeholder 删除 → 通知调用方恢复加号行
                var isPh = newItemPlaceholder && newItemPlaceholder.name === name;
                if (isPh && onDeletePlaceholder) {
                    onDeletePlaceholder();
                    return;
                }
                var found = expItems.find(function(item) { return item.name === name; });
                if (found) onDeleteSub(found._index);
            },
            onReorder: function(names) {
                var newOrder = [];
                names.forEach(function(n) {
                    for (var i = 0; i < expItems.length; i++) {
                        if (expItems[i].name === n) { newOrder.push(i); break; }
                    }
                });
                var reordered = [];
                newOrder.forEach(function(oldIdx) {
                    reordered.push(submissions[oldIdx]);
                });
                submissions.length = 0;
                reordered.forEach(function(s) { submissions.push(s); });
                onReorder();
            }
        });

        // 从产品组导入按钮（在 PG 的加号块之后独立插入，因为 PG 不知道导入按钮）
        if (onImportGroup) {
            // PG 的加号块用 .pg-exp-add-block 标记，导入按钮追加到其后
            var $addBlock = $container.find('.pg-exp-add-block');
            if ($addBlock.length) {
                $addBlock.append('<button class="ps-import-group-btn" style="height:28px;padding:0 12px;margin-left:8px;border:none;border-radius:5px;background:#6c63ff;color:#fff;cursor:pointer;font-size:12px;white-space:nowrap;flex-shrink:0;">📥 从产品组导入</button>');
            }
            $container.find('.ps-import-group-btn').off('click.psaction').on('click.psaction', function(e) {
                e.stopPropagation();
                onImportGroup();
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
            var selectedNames = {};
            var expandedNames = {};

            var html = '<div id="ps-import-overlay" style="position:fixed;inset:0;background:rgba(0,0,0,0.4);display:flex;align-items:center;justify-content:center;z-index:10000;">'
                + '<div style="background:#fff;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.2);width:520px;max-width:95vw;max-height:75vh;display:flex;flex-direction:column;">'
                + '<div style="display:flex;align-items:center;justify-content:space-between;padding:14px 20px;border-bottom:1px solid #e1e4e8;">'
                + '<h3 style="margin:0;font-size:16px;">📥 从产品组导入</h3>'
                + '<button id="ps-import-close" style="background:none;border:none;font-size:20px;cursor:pointer;color:#888;">&times;</button>'
                + '</div>'
                + '<div style="display:flex;align-items:center;padding:10px 20px;border-bottom:1px solid #e1e4e8;background:#f6f8fa;">'
                + '<input id="ps-import-search" type="text" placeholder="🔍 搜索产品组..." style="flex:1;padding:6px 10px;border:1px solid #d0d5dd;border-radius:4px;font-size:12px;margin:0;" maxlength="50">'
                + '</div>'
                + '<div id="ps-import-body" style="flex:1;overflow-y:auto;padding:12px 20px;min-height:200px;">'
                + '<div style="color:#888;text-align:center;padding:40px 0;">加载产品组列表...</div>'
                + '</div>'
                + '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;padding:10px 20px;border-top:1px solid #e1e4e8;">'
                + '<span id="ps-import-count" style="font-size:12px;color:#888;"></span>'
                + '<div style="display:flex;gap:8px;">'
                + '<button id="ps-import-cancel" style="padding:6px 18px;border:1px solid #ddd;border-radius:6px;background:#fff;color:#333;cursor:pointer;font-size:13px;">取消</button>'
                + '<button id="ps-import-confirm" style="padding:6px 18px;border:none;border-radius:6px;background:#6c63ff;color:#fff;cursor:pointer;font-size:13px;white-space:nowrap;" disabled>导入选中 (0)</button>'
                + '</div>'

            var $ov = $(html).appendTo('body');

            function close() { $ov.remove(); }
            $('#ps-import-close, #ps-import-cancel').on('click', close);
            $ov.on('click', function(e) { if (e.target === this) close(); });

            var $confirm = $('#ps-import-confirm');
            var $body = $('#ps-import-body');
            var $search = $('#ps-import-search');

            function updateConfirmButton() {
                var count = Object.keys(selectedNames).length;
                $confirm.text('导入选中 (' + count + ')').prop('disabled', count === 0);
                $('#ps-import-count').text(count > 0 ? '已选 ' + count + ' 组' : '');
            }

            function renderImportList(filterText) {
                filterText = (filterText || '').toLowerCase();
                var filtered = groups;
                if (filterText) {
                    filtered = groups.filter(function(g) {
                        return g.name.toLowerCase().indexOf(filterText) !== -1;
                    });
                }

                PG.renderExpandableGroupList(filtered, $body, {
                    mode: 'import',
                    selected: selectedNames,
                    expanded: expandedNames,
                    dragHandle: null,
                    showAddButton: false,
                    onToggle: function(name) {
                        if (selectedNames[name]) {
                            delete selectedNames[name];
                        } else {
                            selectedNames[name] = true;
                        }
                        updateConfirmButton();
                        renderImportList($search.val());
                    },
                    onExpand: function(name) {
                        expandedNames[name] = true;
                        renderImportList($search.val());
                    },
                    onCollapse: function(name) {
                        delete expandedNames[name];
                        renderImportList($search.val());
                    }
                });
            }

            $search.on('input', function() {
                renderImportList($(this).val());
            });

            $confirm.on('click', function() {
                var names = Object.keys(selectedNames);
                if (!names.length) return;
                var promises = names.map(function(n) {
                    return PG.fetchGroupDetail(n).then(function(g) {
                        return { name: n, paths: g && g.paths ? g.paths : [] };
                    });
                });
                Promise.all(promises).then(function(results) {
                    var allEmpty = results.every(function(r) { return !r.paths.length; });
                    if (allEmpty) { alert('选中的产品组没有路径'); return; }
                    results.forEach(function(r) {
                        if (r.paths.length) {
                            onImport(r.name, r.paths);
                        }
                    });
                    close();
                });
            });

            updateConfirmButton();
            renderImportList('');
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
