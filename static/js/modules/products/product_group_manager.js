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
    var $liquidityOverlay = null;
    var liquidityGroupName = null;
    var liquidityPath = null;
    var liquidityProducts = [];

    function escHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function negativeProductPath(parentPath, productName) {
        var basePath = parentPath.slice(-10) === '/_products' ? parentPath : parentPath + '/_products';
        return '-' + basePath + '/' + productName;
    }

    function formatVolume(value) {
        if (value == null || isNaN(Number(value))) return '—';
        return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 0 });
    }

    function positivePaths(paths) {
        return (paths || []).filter(function(path) { return path.charAt(0) !== '-'; });
    }

    function exclusionsCoveredBy(paths, positive) {
        return (paths || []).filter(function(path) {
            if (path.charAt(0) !== '-') return false;
            var leafPath = path.substring(1);
            return positive.some(function(includedPath) {
                return leafPath === includedPath || leafPath.indexOf(includedPath + '/') === 0;
            });
        });
    }

    function restoreGroupChecks() {
        PS.restoreChecks(groupTree, positivePaths(allGroupPaths));
    }

    function setManagerHint(name) {
        if (!$managerRoot || !$managerRoot.length) return;
        PS.updateLeftHint($managerRoot, name ? ('正在编辑：' + name + '；调整左侧勾选后点击保存') : '点击路径组以编辑 → 勾选品种 → 保存');
    }

    function flashStatus(message, ok) {
        if (!$managerRoot || !$managerRoot.length) return;
        var $s = PS.getChangeStatusEl($managerRoot);
        $s.html(message).css('color', ok === false ? '#d40000' : '#28a745');
        setTimeout(function() { $s.html(''); }, 3000);
    }

    function ensureLiquidityOverlay() {
        if ($liquidityOverlay && $liquidityOverlay.length) return;
        var html = ''
            + '<div id="pg-liquidity-overlay" style="display:none;position:fixed;inset:0;z-index:1100;background:rgba(15,23,42,0.42);align-items:center;justify-content:center;padding:28px;">'
            + '<div style="width:min(1080px,calc(100vw - 56px));max-height:calc(100vh - 56px);display:flex;flex-direction:column;background:#fff;border-radius:12px;box-shadow:0 20px 55px rgba(15,23,42,0.24);overflow:hidden;">'
            + '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;padding:16px 20px;border-bottom:1px solid #e5e7eb;">'
            + '<div><div style="font-size:16px;font-weight:600;color:#101828;">产品流动性与排除设置</div><div class="pg-liquidity-subtitle" style="margin-top:5px;font-size:12px;color:#667085;font-family:monospace;word-break:break-all;"></div></div>'
            + '<button type="button" class="pg-liquidity-close" style="border:none;background:none;color:#667085;font-size:24px;line-height:1;cursor:pointer;">&times;</button>'
            + '</div>'
            + '<div class="pg-liquidity-note" style="padding:10px 20px;background:#f8fafc;border-bottom:1px solid #e5e7eb;color:#475467;font-size:12px;">统计窗口：以每个产品最近可得交易日为终点，滚动 1 年。排除项将保存为独立的负路径规则。</div>'
            + '<div class="pg-liquidity-content" style="overflow:auto;padding:14px 20px 20px;"></div>'
            + '</div></div>';
        $('body').append(html);
        $liquidityOverlay = $('#pg-liquidity-overlay');
        $liquidityOverlay.on('click', function(event) {
            if (event.target === this) closeLiquidityOverlay();
        });
        $liquidityOverlay.on('click', '.pg-liquidity-close', closeLiquidityOverlay);
        $liquidityOverlay.on('click', '.pg-liquidity-toggle', function() {
            var $button = $(this);
            var exclusionPath = $button.data('exclusion');
            var excluded = String($button.data('excluded')) === '1';
            if (selectedName !== liquidityGroupName) return;
            allGroupPaths = allGroupPaths.filter(function(path) { return path !== exclusionPath; });
            if (!excluded) allGroupPaths.push(exclusionPath);
            var editingGroup = groups.find(function(group) { return group.name === liquidityGroupName; });
            if (editingGroup) editingGroup.paths = allGroupPaths.slice();
            renderLiquidityProducts(liquidityProducts);
            flashStatus(excluded ? '↩ 已恢复该产品，点击产品组保存按钮生效' : '− 已排除该产品，点击产品组保存按钮生效');
        });
    }

    function closeLiquidityOverlay() {
        if ($liquidityOverlay) $liquidityOverlay.css('display', 'none');
        liquidityGroupName = null;
        liquidityPath = null;
        liquidityProducts = [];
    }

    function renderLiquidityProducts(products) {
        var canEdit = selectedName === liquidityGroupName;
        var displayedGroup = groups.find(function(group) { return group.name === liquidityGroupName; });
        var displayedPaths = canEdit ? allGroupPaths : ((displayedGroup && displayedGroup.paths) || []);
        liquidityProducts = products || [];
        var html = '<table style="width:100%;border-collapse:collapse;table-layout:fixed;font-size:13px;">'
            + '<thead><tr style="color:#475467;text-align:left;border-bottom:1px solid #d0d5dd;">'
            + '<th style="width:14%;padding:9px 10px;">产品代码</th><th style="width:22%;padding:9px 10px;">产品说明</th>'
            + '<th style="width:17%;padding:9px 10px;">最近日成交量</th><th style="width:19%;padding:9px 10px;">近 1 年日均成交量</th>'
            + '<th style="width:15%;padding:9px 10px;">近 1 年零量日</th><th style="width:13%;padding:9px 10px;">操作</th></tr></thead><tbody>';
        liquidityProducts.forEach(function(product) {
            var productName = product.product_name || product.title || product.name || '';
            var exclusionPath = negativeProductPath(liquidityPath, productName);
            var excluded = displayedPaths.indexOf(exclusionPath) !== -1;
            html += '<tr style="border-bottom:1px solid #f0f2f5;' + (excluded ? 'color:#98a2b3;background:#f9fafb;' : '') + '">'
                + '<td style="padding:10px;">' + escHtml(productName) + (excluded ? ' <span style="color:#b42318;font-size:11px;">已排除</span>' : '') + '</td>'
                + '<td style="padding:10px;">' + escHtml(product.desc || '—') + '</td>'
                + '<td style="padding:10px;">' + formatVolume(product.latest_volume) + '</td>'
                + '<td style="padding:10px;">' + formatVolume(product.average_daily_volume_1y) + '</td>'
                + '<td style="padding:10px;">' + (product.zero_volume_days_1y == null ? '—' : escHtml(product.zero_volume_days_1y)) + '</td>'
                + '<td style="padding:10px;">'
                + (canEdit ? '<button type="button" class="pg-liquidity-toggle" data-exclusion="' + escHtml(exclusionPath) + '" data-excluded="' + (excluded ? '1' : '0') + '" style="padding:4px 10px;border:1px solid ' + (excluded ? '#1570ef' : '#d92d20') + ';border-radius:5px;background:#fff;color:' + (excluded ? '#1570ef' : '#d92d20') + ';cursor:pointer;">' + (excluded ? '恢复' : '排除') + '</button>' : '<span style="font-size:11px;color:#98a2b3;">选择该组后可编辑</span>')
                + '</td></tr>';
        });
        html += '</tbody></table>';
        if (!liquidityProducts.length) html = '<div style="padding:20px;color:#667085;text-align:center;">该路径下没有产品</div>';
        $liquidityOverlay.find('.pg-liquidity-content').html(html);
    }

    function openLiquidityOverlay(groupName, path) {
        ensureLiquidityOverlay();
        liquidityGroupName = groupName;
        liquidityPath = path;
        $liquidityOverlay.find('.pg-liquidity-subtitle').text(groupName + ' / ' + path);
        $liquidityOverlay.find('.pg-liquidity-content').html('<div style="padding:28px;color:#667085;text-align:center;">正在读取一年成交量统计...</div>');
        $liquidityOverlay.css('display', 'flex');
        $.get('/get_products', { path: path, include_volume_stats: 'true' })
            .done(renderLiquidityProducts)
            .fail(function() {
                $liquidityOverlay.find('.pg-liquidity-content').html('<div style="padding:28px;color:#d92d20;text-align:center;">成交量统计加载失败</div>');
            });
    }

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
                    setManagerHint(newItemPlaceholderName);
                    renderGroupList();
                },
                onToggle: function(name) {
                    // 互斥：进入选中清 placeholder 和输入框编辑
                    if (newItemPlaceholderName) { newItemPlaceholderName = null; }
                    editingName = null;
                    selectedName = (selectedName === name) ? null : name;
                    if (selectedName) {
                        PS.clearChecks(groupTree);
                        setManagerHint(selectedName);
                        PG.fetchGroupDetail(name).then(function(g) {
                            if (g && g.paths) {
                                allGroupPaths = g.paths.slice();
                                restoreGroupChecks();
                            }
                        });
                    } else {
                        allGroupPaths = [];
                        PS.clearChecks(groupTree);
                        setManagerHint(null);
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
                    selectedName = name;
                    editingName = name;
                    PS.clearChecks(groupTree);
                    PG.fetchGroupDetail(name).then(function(g) {
                        if (g && g.paths) {
                            allGroupPaths = g.paths.slice();
                            restoreGroupChecks();
                        }
                    });
                    setManagerHint(name);
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
                                setManagerHint(null);
                                flashStatus('✓ 产品组已创建');
                                renderGroupList();
                            } else {
                                flashStatus('✗ 保存失败: ' + (resp.error || '未知错误'), false);
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
                                setManagerHint(null);
                                flashStatus('✓ 已重命名');
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
                                setManagerHint(null);
                                flashStatus('✓ 已保存');
                                renderGroupList();
                            } else {
                                flashStatus('✗ 保存失败: ' + ((resp && resp.error) || '未知错误'), false);
                            }
                        });
                    } else if (exists) {
                        PG.updateGroup(name, allGroupPaths).then(function(resp) {
                            if (resp.success) { selectedName = null; editingName = null; setManagerHint(null); flashStatus('✓ 已保存'); renderGroupList(); }
                            else { flashStatus('✗ 保存失败: ' + (resp.error || '未知错误'), false); }
                        });
                    } else {
                        // New
                        PG.createGroup(newName, allGroupPaths).then(function(resp) {
                            if (resp.success) { selectedName = null; editingName = null; setManagerHint(null); flashStatus('✓ 产品组已创建'); renderGroupList(); }
                            else { flashStatus('✗ 保存失败: ' + (resp.error || '未知错误'), false); }
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
                        setManagerHint(null);
                        flashStatus('✓ 已删除');
                        renderGroupList();
                    });
                },
                onDeletePath: function(name, path) {
                    var group = groups.find(function(g) { return g.name === name; });
                    if (!group) return;
                    var newPaths = (group.paths || []).filter(function(p) {
                        if (p === path) return false;
                        return path.charAt(0) === '-' || p.charAt(0) !== '-' || p.substring(1).indexOf(path + '/') !== 0;
                    });
                    PG.updateGroup(name, newPaths).then(function(resp) {
                        if (resp && resp.success) {
                            if (selectedName === name) {
                                allGroupPaths = newPaths.slice();
                                PS.clearChecks(groupTree);
                                restoreGroupChecks();
                            }
                            flashStatus('✓ 路径已删除');
                            renderGroupList();
                        } else {
                            flashStatus('✗ 删除路径失败: ' + ((resp && resp.error) || '未知错误'), false);
                        }
                    });
                },
                onRename: function(oldName, newName) {
                    newName = (newName || '').trim();
                    if (!newName || newName === oldName) { renderGroupList(); return; }
                    PG.renameGroup(oldName, newName).then(function() {
                        if (selectedName === oldName) selectedName = newName;
                        if (expandedNames[oldName]) { delete expandedNames[oldName]; expandedNames[newName] = true; }
                        flashStatus('✓ 已重命名');
                        renderGroupList();
                    });
                },
                onReorder: function(names) {
                    var visible = {};
                    names.forEach(function(n) { visible[n] = true; });
                    var visibleStorageOrder = names.slice().reverse();
                    var fullOrder = [];
                    groups.forEach(function(g) {
                        if (visible[g.name]) {
                            fullOrder.push(visibleStorageOrder.shift());
                        } else {
                            fullOrder.push(g.name);
                        }
                    });
                    PG.reorderGroups(fullOrder).then(function(resp) {
                        flashStatus(resp && resp.success ? '✓ 顺序已更新' : '✗ 排序失败', !!(resp && resp.success));
                    });
                },
                onOpenProductDetails: function(name, path) {
                    openLiquidityOverlay(name, path);
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
        setManagerHint(null);

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
                onSelect: function(paths) {
                    allGroupPaths = paths.concat(exclusionsCoveredBy(allGroupPaths, paths));
                }
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
        closeLiquidityOverlay();
        $overlay.css('display', 'none');
    }

    window.openProductGroupManager = openOverlay;

    $('#btn-product-groups').on('click', openOverlay);
    $('#pg-overlay').on('click', function(e) { if (e.target === this) closeOverlay(); });
    $(document).on('keydown.pgLiquidity', function(e) {
        if (e.key === 'Escape' && $liquidityOverlay && $liquidityOverlay.is(':visible')) closeLiquidityOverlay();
    });

})(jQuery, window);
