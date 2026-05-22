/**
 * 产品类别筛选模块独立脚本
 * 功能：Fancytree 产品树、提交选中产品、历史记录管理、拖拽排序、路径删除等
 */
(function() {
    // 全局变量
    // SubmissionRecord 是前端提交记录；它引用后端创建的 FactorTester，但不是 FactorTester 本身。
    var submissions = [];           // 兼容旧模块名：IC/Group 仍读取 window.submissions
    window.submissions = submissions;
    window.getSubmissionRecords = function() { return submissions; };
    var expandedState = {};        // 记录每个提交中路径的展开状态
    var newItemPlaceholderName = null;  // 当前 placeholder 名称，null = 无
    var editingName = null;            // 当前选中态记录标识（sub.id）
    var inlineEditingName = null;      // 当前输入框编辑中的记录标识（sub.id）
    var treeInstance = null;
    var categoryTreeSizer = null;
    var $moduleContainer = null;  // PS.render() 的容器

    function submissionEditableLabel(sub, index) {
        if (!sub) return '';
        return sub.label || sub.product_group || ('#' + (index + 1) + ' ' + (sub.factor_tester_serial || ''));
    }

    function submissionVisibleLabel(sub, index) {
        if (!sub) return '';
        return sub.product_group || sub.label || ('#' + (index + 1) + ' ' + (sub.factor_tester_serial || ''));
    }

    function submissionDisplayName(sub, index) {
        var label = submissionVisibleLabel(sub, index);
        var visibleName = sub.product_group ? ('📦 ' + label) : label;
        return visibleName + ' (ID:' + sub.id + ')';
    }

    function setEditingHint(sub) {
        if (!$moduleContainer || !$moduleContainer.length || !window.ProductSelector) return;
        if (sub) {
            var idx = submissions.indexOf(sub);
            window.ProductSelector.updateLeftHint($moduleContainer, '正在编辑：' + submissionEditableLabel(sub, idx) + '；调整左侧勾选后点击保存');
        } else {
            window.ProductSelector.updateLeftHint($moduleContainer, '树状结构，勾选叶子节点或分类后提交');
        }
    }

    function flashChangeStatus(message, ok) {
        var $s = window.ProductSelector.getChangeStatusEl($moduleContainer);
        $s.html(message).css('color', ok === false ? '#d40000' : '#28a745');
        setTimeout(function() { $s.html(''); }, 3000);
    }

    function escHtml(str) {
        return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    function _hasMountedTree($container) {
        if (!$container || !$container.length) return false;
        try {
            return !!$container.fancytree('getTree');
        } catch (e) {
            return false;
        }
    }

    // 用后端列表同步本地 submissions
    function syncFromServer(serverSubmissions) {
        // 保留下标映射：用 id 作为 key
        var oldMap = {};
        submissions.forEach(function(sub, i) {
            oldMap[sub.id] = { index: i, data: sub };
        });
        var newSubs = serverSubmissions.map(function(s) {
            var old = oldMap[s.id];
            if (old) {
                // 保留本地字段（paths, pathsDescMap, timestamp 等前端特有状态）
                var merged = old.data;
                merged.product_count = s.product_count;
                merged.factor_tester_serial = s.factor_tester_serial;
                merged.label = s.label || merged.label || '';
                merged.product_group = s.product_group || merged.product_group || '';
                merged.selected_paths = s.selected_paths;
                merged.paths = s.selected_paths || merged.paths;
                return merged;
            }
            // 新提交：用后端 selected_paths 作为 paths
            var paths = s.selected_paths || [];
            return {
                id: s.id,
                paths: paths,
                pathsDescMap: {},
                factor_tester_name: s.name,
                factor_tester_serial: s.factor_tester_serial,
                label: s.label || '',
                product_count: s.product_count,
                product_group: s.product_group || '',
                count_desc: s.product_count + ' 个产品',
                timestamp: new Date().toLocaleTimeString(),
                start_date: '',
                end_date: '',
                start_time: '',
                end_time: ''
            };
        });
        submissions = newSubs;
        window.submissions = submissions;
        window.submissionRecords = submissions;
        renderHistory();
        refreshSubmissionDependents();
    }

    function refreshSubmissionDependents() {
        setTimeout(function() {
            try {
                if (typeof window.updateCategorySummary === 'function') {
                    window.updateCategorySummary();
                }
            } catch (e) {
                console.error('刷新产品类别摘要失败:', e);
            }
            try {
                if (typeof window.renderICTabs === 'function') {
                    Promise.resolve(window.renderICTabs(submissions)).catch(function(e) {
                        console.error('刷新 IC 测试标签失败:', e);
                    });
                } else if (typeof window.renderGroupTabs === 'function') {
                    window.renderGroupTabs(submissions);
                }
            } catch (e) {
                console.error('刷新 submission 依赖模块失败:', e);
            }
        }, 0);
    }

    // 辅助函数：渲染右侧历史记录（委托给统一的 ProductSelector）
    function renderHistory() {
        if (!$moduleContainer || !$moduleContainer.length || !window.ProductSelector) return;
        var $container = window.ProductSelector.getSubmissionContainer($moduleContainer);
        if (!$container || !$container.length) return;

        window.ProductSelector.renderSubmissionHistory(submissions, expandedState, $container, {
            newItemPlaceholder: newItemPlaceholderName ? { name: newItemPlaceholderName } : null,
            editingName: editingName,
            displayEditingName: inlineEditingName,
            onAdd: function() {
                // 已有 placeholder 时不重复添加；点击添加时退出其他编辑
                if (newItemPlaceholderName) return;
                editingName = null;
                inlineEditingName = null;
                var now = new Date();
                var pad = function(n) { return n < 10 ? '0' + n : '' + n; };
                newItemPlaceholderName = now.getFullYear() + pad(now.getMonth()+1) + pad(now.getDate()) + '-' + pad(now.getHours()) + pad(now.getMinutes()) + pad(now.getSeconds());
                renderHistory();
            },
            onSave: function(name, newName, isPlaceholder) {
                newName = (newName || '').trim();
                if (!newName) { inlineEditingName = null; editingName = null; renderHistory(); return; }

                if (isPlaceholder) {
                    // placeholder：有路径 → 提交；无路径 → 仅改名保持 placeholder
                    newItemPlaceholderName = newName;
                    var selNodes = treeInstance ? treeInstance.getSelectedNodes() : [];
                    if (selNodes.length > 0) {
                        submitSelectedProducts();
                        newItemPlaceholderName = null;
                    }
                    editingName = null;
                    inlineEditingName = null;
                    renderHistory();
                } else {
                    // 已有记录：用 editingName（sub.id）精确查找
                    var subId = editingName;
                    var found = submissions.find(function(s) { return String(s.id) === String(subId); });
                    if (!found) { editingName = null; inlineEditingName = null; renderHistory(); return; }

                    var minimalPaths = [];
                    if (treeInstance) {
                        var sel = treeInstance.getSelectedNodes();
                        var keySet = new Set(sel.map(function(n) { return n.key; }));
                        minimalPaths = sel.filter(function(n) {
                            var p = n.parent;
                            while (p && p.key) { if (keySet.has(p.key)) return false; p = p.parent; }
                            return true;
                        }).map(function(n) { return n.key; });
                    }

                    if (minimalPaths.length > 0) {
                        // 有选中路径 → 更新
                        fetch('/update_submission_paths', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({ id_time: found.id, selected_paths: minimalPaths, new_name: newName })
                        })
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            if (data.success) {
                                inlineEditingName = null;
                                editingName = null;
                                setEditingHint(null);
                                flashChangeStatus('✓ 已保存');
                                if (data.submissions) syncFromServer(data.submissions);
                                else renderHistory();
                            } else {
                                flashChangeStatus('✗ 保存失败: ' + (data.error || '未知错误'), false);
                            }
                        });
                    } else if (newName !== name) {
                        // 无路径 → 仅改名
                        fetch('/rename_submission', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({ id_time: found.id, new_name: newName })
                        })
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            if (data.success) {
                                inlineEditingName = null;
                                editingName = null;
                                setEditingHint(null);
                                flashChangeStatus('✓ 已重命名');
                                if (data.submissions) syncFromServer(data.submissions);
                                else renderHistory();
                            } else {
                                flashChangeStatus('✗ 重命名失败: ' + (data.error || '未知错误'), false);
                            }
                        });
                    } else {
                        // 名字没变、没路径 → 直接退出
                        inlineEditingName = null;
                        editingName = null;
                        renderHistory();
                    }
                }
            },
            onDeletePlaceholder: function() {
                newItemPlaceholderName = null;
                renderHistory();
            },
            onToggleEdit: function(subId, sub) {
                // ProductSelector 直接传 sub.id；兼容旧调用时再退回显示名匹配。
                if (!sub) {
                    sub = submissions.find(function(s) {
                        return String(s.id) === String(subId) || submissionDisplayName(s, submissions.indexOf(s)) === subId;
                    });
                    subId = sub ? sub.id : subId;
                }
                if (editingName === subId) {
                    editingName = null;
                    inlineEditingName = null;
                    if (treeInstance) {
                        window.ProductSelector.clearChecks(treeInstance);
                    }
                    setEditingHint(null);
                } else {
                    editingName = subId;
                    inlineEditingName = null;  // 新选中不退输入框
                    newItemPlaceholderName = null;
                    if (treeInstance) {
                        window.ProductSelector.clearChecks(treeInstance);
                        if (sub && sub.paths) {
                            window.ProductSelector.restoreChecks(treeInstance, sub.paths);
                        }
                    }
                    setEditingHint(sub);
                }
                renderHistory();
            },
            onEditName: function(subId, sub) {
                if (!sub) {
                    sub = submissions.find(function(s) {
                        return String(s.id) === String(subId) || submissionDisplayName(s, submissions.indexOf(s)) === subId;
                    });
                    subId = sub ? sub.id : subId;
                }
                editingName = subId;
                inlineEditingName = subId;
                setEditingHint(sub || null);
                renderHistory();
            },
            onImportGroup: function() {
                window.ProductSelector.openGroupImport(function(groupName, paths) {
                    var importId = Date.now() + '-' + Math.random().toString(36).slice(2, 10);
                    fetch('/submit_selected_products', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            selected_paths: paths,
                            id_time: importId,
                            group_name: groupName,
                            page_uuid: window._pageUuid || ''
                        })
                    })
                    .then(function(r) { return r.json(); })
                    .then(function(submitResp) {
                        if (!submitResp.success) {
                            alert('提交失败: ' + (submitResp.error || '未知错误'));
                            return;
                        }
                        if (submitResp.submissions) syncFromServer(submitResp.submissions);
                        editingName = null;
                        newItemPlaceholderName = null;
                        renderHistory();
                        refreshSubmissionDependents();
                    });
                });
            },
            onReorder: function() {
                fetch('/reorder_submissions', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ new_order: submissions.map(function(s) { return s.id; }) })
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    var $s = window.ProductSelector.getChangeStatusEl($moduleContainer);
                    $s.html(data.success ? '✓ 顺序已更新' : '✗ 排序失败: ' + data.error)
                      .css('color', data.success ? '#28a745' : '#d40000');
                    setTimeout(function() { $s.html(''); }, 3000);
                });
            },
            onDeleteSub: function(index) {
                var sub = submissions[index];
                if (!sub) return;
                fetch('/delete_submission', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ id_time: sub.id })
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    var $s = window.ProductSelector.getChangeStatusEl($moduleContainer);
                    if (data.success) {
                        $s.html('<div>✓ 提交已删除</div>').css('color', '#28a745');
                        if (data.submissions) {
                            syncFromServer(data.submissions);
                        } else {
                            submissions.splice(index, 1);
                            renderHistory();
                            refreshSubmissionDependents();
                        }
                    } else {
                        $s.html('<div>✗ 删除失败: ' + data.error + '</div>').css('color', '#d40000');
                    }
                    setTimeout(function() { $s.html(''); }, 3000);
                });
            },
            onDeletePath: function(subIndex, pathIndex) {
                var sub = submissions[subIndex];
                if (!sub) return;
                var newPaths = sub.paths.filter(function(_, i) { return i !== pathIndex; });
                fetch('/delete_path_of_submission', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ id_time: sub.id, new_paths: newPaths })
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    var $s = window.ProductSelector.getChangeStatusEl($moduleContainer);
                    if (data.success) {
                        if (newPaths.length === 0) {
                            fetch('/delete_submission', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify({ id_time: sub.id })
                            })
                            .then(function(r) { return r.json(); })
                            .then(function(d2) {
                                if (d2.success) {
                                    if (d2.submissions) syncFromServer(d2.submissions);
                                    else { submissions.splice(subIndex, 1); renderHistory(); refreshSubmissionDependents(); }
                                }
                                $s.html((d2.success ? '✓' : '✗') + ' 提交已删除').css('color', d2.success ? '#28a745' : '#d40000');
                                setTimeout(function() { $s.html(''); }, 3000);
                            });
                        } else {
                            if (data.submissions) syncFromServer(data.submissions);
                            else { sub.paths = newPaths; renderHistory(); refreshSubmissionDependents(); }
                            $s.html('<div>✓ 路径已删除</div>').css('color', '#28a745');
                            setTimeout(function() { $s.html(''); }, 3000);
                        }
                    } else {
                        $s.html('<div>✗ 删除失败: ' + data.error + '</div>').css('color', '#d40000');
                        setTimeout(function() { $s.html(''); }, 3000);
                    }
                });
            },
            onLabelChange: function(idx, val) {
                if (typeof window.renderICTabs === 'function') window.renderICTabs(submissions);
                if (typeof window.renderGroupTabs === 'function') window.renderGroupTabs(submissions);
            },
            onPathClick: function(path, subIndex, pathIndex) {
                loadProductsForPath(path, subIndex, pathIndex);
            }
        });
    }

    // 加载指定路径的产品详情
    function loadProductsForPath(path, subIndex, pathIndex) {
        var $detailCell = $('#detail-' + subIndex + '-' + pathIndex + ' td');
        if (!$detailCell.length) return;
        $.get('/get_products', { path: path })
            .done(function(data) {
                if (data && data.length) {
                    var html = '<div style="font-size:13px;">';
                    data.forEach(function(prod) {
                        html += '<div>' + _escHtml(prod.title) + ' <span style="color:#888;">' + _escHtml(prod.desc || '') + '</span></div>';
                    });
                    html += '</div>';
                    $detailCell.html(html);
                } else {
                    $detailCell.html('<span style="color:#888;font-size:13px;">无产品</span>');
                }
            })
            .fail(function() {
                $detailCell.html('<span style="color:#d00;font-size:13px;">加载失败</span>');
            });
    }

    // 兼容 PS.renderSubmissionHistory 内部的 _escHtml
    var _escHtml = escHtml;

    // 提交选中的产品
    function submitSelectedProducts() {
        if (!treeInstance) {
            console.error("树尚未初始化完成");
            return;
        }
        var selectedNodes = treeInstance.getSelectedNodes();
        // 只保留「祖先节点中没有其他已选节点」的最小集合，避免发送海量叶子路径
        var selectedKeySet = new Set(selectedNodes.map(function(n) { return n.key; }));
        var minimalNodes = selectedNodes.filter(function(node) {
            var p = node.parent;
            while (p && p.key) {
                if (selectedKeySet.has(p.key)) return false;
                p = p.parent;
            }
            return true;
        });
        var selectedPaths = minimalNodes.map(function(node) { return node.key; });
        var pathToDescMap = {};
        minimalNodes.forEach(function(node) {
            pathToDescMap[node.key] = node.data.desc || "";
        });

        var timestamp = new Date();
        var id_time = timestamp.getTime();
        var timeStr = timestamp.toLocaleTimeString();

        fetch('/submit_selected_products', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                selected_paths: selectedPaths,
                id_time: id_time,
                page_uuid: window._pageUuid || ''
            })
        })
        .then(r => r.json())
        .then(data => {
            var statusSpan = window.ProductSelector.getStatusEl($moduleContainer);
            if (data.success) {
                var msg = '✓ 已提交，产品数量: ' + data.count + ', 路径数量: ' + data.count_paths;
                statusSpan.html(msg).css('color', '#28a745');
                // 清空树选中状态
                treeInstance.getRootNode().children.forEach(function(topNode) {
                    topNode.setSelected(false);
                });
                // 添加到历史
                if (data.selected_paths && data.selected_paths.length > 0) {
                    // 用后端返回的 submissions 同步
                    if (data.submissions) {
                        syncFromServer(data.submissions);
                    }
                }
            } else {
                var errMsg = '提交失败: ' + (data.error || '未知错误');
                statusSpan.html(errMsg).css('color', '#d40000');
                alert(errMsg);
            }
            setTimeout(function() { statusSpan.html(''); }, 3000);
        });
    }

    // 初始化 Fancytree 和 Sortable。动态创建悬浮 overlay 页面（居中弹窗），
    // 替代旧的侧边 drawer。外部依赖脚本（jQuery/Fancytree/Sortable）可能比本模块稍晚就绪；
    // 因此显式等待依赖。
    function initCategoryFilterModule(retryCount) {
        retryCount = retryCount || 0;
        if (!window.jQuery) {
            if (retryCount < 80) {
                setTimeout(function() { initCategoryFilterModule(retryCount + 1); }, 50);
            } else {
                var el = document.getElementById('category-summary-text');
                if (el) el.textContent = '产品树加载失败：jQuery 未就绪';
            }
            return;
        }
        var $ = window.jQuery;
        if (!$.fn || typeof $.fn.fancytree !== 'function') {
            if (retryCount < 80) {
                setTimeout(function() { initCategoryFilterModule(retryCount + 1); }, 50);
            }
            return;
        }

        var PS = window.ProductSelector;

        // 创建悬浮 overlay 容器
        var $overlay = $('#category-filter-overlay');
        if (!$overlay.length) {
            $overlay = $('<div id="category-filter-overlay" style="display:none;position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.35);align-items:center;justify-content:center;"></div>');
            $('body').append($overlay);
            // 点击遮罩关闭
            $overlay.on('click', function(e) {
                if (e.target === this) closeCategoryFilter();
            });
        }

        // 在 overlay 内部创建面板容器
        if (!$overlay.find('#cf-panel').length) {
            var panelHtml = '<div id="cf-panel" style="position:relative;width:min(92vw,1100px);height:min(88vh,720px);background:#fff;border-radius:10px;box-shadow:0 8px 40px rgba(0,0,0,0.2);display:flex;flex-direction:column;overflow:hidden;">';
            panelHtml += '<div id="ps-cf-root" style="flex:1;overflow:hidden;"></div>';
            panelHtml += '</div>';
            $overlay.append(panelHtml);
        }

        $moduleContainer = $('#ps-cf-root');
        if (!$moduleContainer.length) return;

        // 如果已渲染过，不再重复构建结构，但仍需刷新历史
        // （切换因子家族时 overlay 可能复用旧 DOM，若不刷新会残留旧提交路径）
        if ($moduleContainer.find('.ps-body').length) {
            try { renderHistory(); } catch (e) {}
            return;
        }

        // 统一布局渲染
        PS.render($moduleContainer, {
            title: '🌳 产品类别筛选',
            submitLabel: '',
            toolbar: '',
            onSubmit: submitSelectedProducts,
            headerBtns: '<button id="cf-overlay-close" style="background:none;border:none;font-size:22px;cursor:pointer;color:#888;line-height:1;">&times;</button>'
        });
        $('#cf-overlay-close').on('click', closeCategoryFilter);

        // 初始化左侧树
        PS.initLeftTree($moduleContainer, {
            onInit: function(tree) {
                treeInstance = tree;
            }
        });

        // 左栏右下角拖动缩放
        if (typeof window.setupResizableTreeContainer === 'function' && !categoryTreeSizer) {
            var $leftPanel = $moduleContainer.find('.ps-left-panel');
            var $treeContainer = $moduleContainer.find('.ps-tree-container');
            if ($leftPanel.length && $treeContainer.length) {
                categoryTreeSizer = window.setupResizableTreeContainer({
                    outerElement: $leftPanel[0],
                    innerElement: $treeContainer[0],
                    minWidth: 260,
                    initialWidth: 340,
                    minHeight: 150,
                    initialHeight: 400,
                    maxWidth: 'min(54vw, 620px)',
                    maxWidthFallback: 620,
                    resizeDirection: 'both',
                    desktopMediaQuery: '(max-width: 1200px)',
                    mobileInnerMaxHeight: '400px'
                });
            }
        }

        // 初始渲染历史记录
        renderHistory();

    }

    // 暴露给单因子设置快照模块。产品类别筛选弹窗是懒加载的，因此这些接口必须在
    // openCategoryFilter() 之前就存在，模板恢复才能更新外部摘要和后续测试模块。
    window._getCurrentSubmissions = function() {
        return submissions;
    };
    window._applySubmissions = function(newSubmissions) {
        submissions = Array.isArray(newSubmissions) ? newSubmissions : [];
        window.submissions = submissions;
        window.submissionRecords = submissions;
        expandedState = {};
        renderHistory();
        refreshSubmissionDependents();
    };

    window.openCategoryFilter = function() {
        var $overlay = $('#category-filter-overlay');
        if (!$overlay.length || !$('#ps-cf-root').find('.ps-body').length) {
            initCategoryFilterModule(0);
        }
        $('#category-filter-overlay').css('display', 'flex');
        if (categoryTreeSizer && typeof categoryTreeSizer.sync === 'function') {
            setTimeout(function() { categoryTreeSizer.sync(); }, 100);
        }
    };

    window.closeCategoryFilter = function() {
        $('#category-filter-overlay').css('display', 'none');
        try { if (typeof window.updateCategorySummary === 'function') window.updateCategorySummary(); } catch(e) {}
    };

    // 不再自动 init，由 openCategoryFilter() 按需懒加载
})();
