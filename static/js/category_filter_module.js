/**
 * 产品类别筛选模块独立脚本
 * 功能：Fancytree 产品树、提交选中产品、历史记录管理、拖拽排序、路径删除等
 */
(function() {
    // 全局变量
    var submissions = [];           // 存储所有提交记录
    window.submissions = submissions;   // 新增
    var expandedState = {};        // 记录每个提交中路径的展开状态
    var treeInstance = null;

    // 辅助函数：渲染右侧历史记录
    function renderHistory() {
        var html = '';
        submissions.forEach(function(sub, index) {
            var isExpanded = expandedState[index] || {};
            html += '<div class="submission-item" data-index="' + index + '" style="border:1px solid #e1e4e8; border-radius:8px; margin-bottom:12px; background:#fff; overflow:hidden;">';
            html += '  <div class="submission-header" style="background:#f6f8fa; padding:8px 12px; cursor:move; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #e1e4e8;">';
            html += '    <span style="font-size:13px;"><i class="fas fa-grip-vertical" style="margin-right:8px; color:#888;"></i> <strong>#' + (index+1) + '</strong> ' + sub.factor_tester_serial + ' (' + sub.timestamp + ')' + (sub.count_desc ? ' <span style="color:#d00;">' + sub.count_desc + '</span>' : '') + '</span>';
            html += '    <button class="delete-submission" data-index="' + index + '" style="background:transparent; border:none; color:#d00; cursor:pointer; font-size:14px;"><i class="fas fa-trash"></i></button>';
            html += '  </div>';
            html += '  <div style="padding:8px 12px;">';
            html += '    <table style="width:100%; border-collapse:collapse;">';
            sub.paths.forEach(function(path, pathIdx) {
                var rowId = 'path-' + index + '-' + pathIdx;
                var expanded = isExpanded[path] || false;
                var pathDisplay = path;
                if (sub.pathsDescMap && sub.pathsDescMap[path]) {
                    pathDisplay = path + ' <span style="color:#888;font-size:12px;">' + sub.pathsDescMap[path] + '</span>';
                }
                html += '      <tr class="path-row" data-path="' + path.replace(/"/g, '&quot;') + '" data-sub-index="' + index + '" data-path-index="' + pathIdx + '">';
                html += '        <td style="padding:4px 0; border-bottom:1px solid #f0f0f0;">';
                html += '          <div style="display:flex;align-items:center;">';
                html += '            <span class="path-text" style="cursor:pointer; font-size:13px; margin-left:6px;">' + pathDisplay + '</span>';
                html += '            <button class="delete-path" data-sub-index="' + index + '" data-path-index="' + pathIdx + '" style="margin-left:auto; background:transparent; border:none; color:#d00; cursor:pointer; padding:0 8px;"><i class="fas fa-times"></i></button>';
                html += '          </div>';
                html += '        </td>';
                html += '      </tr>';
                if (expanded) {
                    html += '      <tr class="product-detail-row" id="detail-' + index + '-' + pathIdx + '">';
                    html += '        <td style="padding:8px 0 8px 20px; background:#fafbfc;">';
                    html += '          <div class="loading-products" style="font-size:13px;">加载中...</div>';
                    html += '        </td>';
                    html += '      </tr>';
                }
            });
            html += '    </table>';
            html += '  </div>';
            html += '</div>';
        });
        $('#submission-history').html(html || '<div style="color:#888;text-align:center;padding:20px;">暂无提交记录</div>');

        // 绑定路径点击展开/折叠事件
        $('.path-text').off('click').on('click', function() {
            var $row = $(this).closest('tr.path-row');
            var subIndex = $row.data('sub-index');
            var path = $row.data('path');
            var pathIndex = $row.data('path-index');
            var expanded = expandedState[subIndex] || {};
            if (expanded[path]) {
                // 折叠
                $('#detail-' + subIndex + '-' + pathIndex).remove();
                delete expanded[path];
            } else {
                // 展开：加载产品详情
                expanded[path] = true;
                var detailHtml = '<tr class="product-detail-row" id="detail-' + subIndex + '-' + pathIndex + '">' +
                    '<td style="padding:8px 0 8px 20px; background:#fafbfc;">' +
                    '<div class="loading-products" style="font-size:13px;">加载中...</div>' +
                    '</td></tr>';
                $row.after(detailHtml);
                loadProductsForPath(path, subIndex, pathIndex);
            }
            expandedState[subIndex] = expanded;
        });

        // 绑定删除路径按钮
        $('.delete-path').off('click').on('click', function() {
            var subIndex = $(this).data('sub-index');
            var pathIndex = $(this).data('path-index');
            var submission = submissions[subIndex];
            if (!submission) return;
            var newPaths = submission.paths.filter(function(_, idx) { return idx !== pathIndex; });
            fetch('/delete_path_of_submission', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    id_time: submission.id,
                    new_paths: newPaths
                })
            })
            .then(r => r.json())
            .then(data => {
                var statusElem = $('#submission_change_status');
                if (data.success) {
                    statusElem.html('✓ 路径已删除').css('color', '#28a745');
                    // 本地更新
                    submissions[subIndex].paths = newPaths;
                    if (newPaths.length === 0) {
                        // 如果没有路径了，删除整个提交
                        fetch('/delete_submission', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({ id_time: submission.id })
                        })
                        .then(r => r.json())
                        .then(data2 => {
                            if (data2.success) {
                                submissions.splice(subIndex, 1);
                                statusElem.html('✓ 提交已删除').css('color', '#28a745');
                            } else {
                                statusElem.html('✗ 删除提交失败: ' + data2.error).css('color', '#d40000');
                            }
                            renderHistory();
                            setTimeout(function() { statusElem.html(''); }, 3000);
                        });
                    } else {
                        renderHistory();
                        setTimeout(function() { statusElem.html(''); }, 3000);
                    }
                } else {
                    statusElem.html('✗ 删除失败: ' + data.error).css('color', '#d40000');
                    setTimeout(function() { statusElem.html(''); }, 3000);
                }
            });
        });

        // 绑定删除整个提交按钮
        $('.delete-submission').off('click').on('click', function() {
            var index = $(this).data('index');
            var submission = submissions[index];
            if (!submission) return;
            fetch('/delete_submission', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ id_time: submission.id })
            })
            .then(r => r.json())
            .then(data => {
                var statusElem = $('#submission_change_status');
                if (data.success) {
                    statusElem.html('✓ 提交已删除').css('color', '#28a745');
                    submissions.splice(index, 1);
                    renderHistory();
                    setTimeout(function() { statusElem.html(''); }, 3000);
                } else {
                    statusElem.html('✗ 删除失败: ' + data.error).css('color', '#d40000');
                    setTimeout(function() { statusElem.html(''); }, 3000);
                }
            });
        });

        // 新增：通知 IC 模块更新
        if (typeof window.renderICTabs === 'function') {
            window.renderICTabs(submissions);
        }
    }

    // 加载指定路径的产品详情
    function loadProductsForPath(path, subIndex, pathIndex) {
        var $detailCell = $('#detail-' + subIndex + '-' + pathIndex + ' td');
        $.get('/get_products', { path: path })
            .done(function(data) {
                if (data && data.length) {
                    var html = '<div style="font-size:13px;">';
                    data.forEach(function(prod) {
                        html += `<div>${prod.title} <span style="color:#888;">${prod.desc || ''}</span></div>`;
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

    // 提交选中的产品
    function submitSelectedProducts() {
        if (!treeInstance) {
            console.error("树尚未初始化完成");
            return;
        }
        var selectedNodes = treeInstance.getSelectedNodes();
        var selectedPaths = selectedNodes.map(function(node) { return node.key; });
        var pathToDescMap = {};
        selectedNodes.forEach(function(node) {
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
                id_time: id_time
            })
        })
        .then(r => r.json())
        .then(data => {
            var statusSpan = $('#submit_status');
            if (data.success) {
                var msg = '✓ 已提交，产品数量: ' + data.count + ', 路径数量: ' + data.count_paths;
                statusSpan.html(msg).css('color', '#28a745');
                // 清空树选中状态
                treeInstance.getRootNode().children.forEach(function(topNode) {
                    topNode.setSelected(false);
                });
                // 添加到历史
                if (data.selected_paths && data.selected_paths.length > 0) {
                    var newSubmission = {
                        id: id_time,
                        paths: data.selected_paths.slice(),
                        pathsDescMap: pathToDescMap,
                        factor_tester_name: data.factor_tester_name,
                        factor_tester_serial: data.factor_tester_serial,
                        count_desc: data.count_desc,
                        timestamp: timeStr,
                    };
                    submissions.push(newSubmission);
                    renderHistory();
                }
            } else {
                statusSpan.html('提交失败: ' + (data.error || '未知错误')).css('color', '#d40000');
            }
            setTimeout(function() { statusSpan.html(''); }, 3000);
        });
    }

    // 初始化 Fancytree 和 Sortable
    $(function() {
        // 清空容器，确保没有残留内容
        var $container = $("#tree-container");
        $container.empty();  // 移除任何可能存在的占位文字

        // 可选：显示一个临时的 loading 提示（Fancytree 加载期间会显示自带 loading，但为了体验可以加一个）
        $container.html('<div style="color:#888;text-align:center;padding:20px;">加载产品树...</div>');

        // 初始化 Fancytree
        $container.fancytree({
            source: {
                url: "/api/tree-data"
            },
            checkbox: true,
            selectMode: 3,
            init: function(event, data) {
                treeInstance = data.tree;
                // 树初始化完成后，移除可能残留的临时占位（Fancytree 已填充内容）
                $container.find('> div:first-child').remove(); // 移除临时占位
            },
            lazyLoad: function(event, data) {
                var node = data.node;
                data.result = {
                    url: "/get_products",
                    data: { path: node.key }
                };
            },
            renderNode: function(event, data) {
                var node = data.node;
                var desc = node.data.desc;
                if (desc) {
                    var $title = $(node.span).find('.fancytree-title');
                    $title.siblings('.node-description').remove();
                    $title.after('<span class="node-description" style="color:#888; margin-left:8px; font-size:12px;">' + desc + '</span>');
                }
            }
        });

        // 提交按钮事件
        $("#submit-selected").click(submitSelectedProducts);

        // 初始化 SortableJS 实现拖动排序
        var historyContainer = document.getElementById('submission-history');
        if (historyContainer) {
            new Sortable(historyContainer, {
                animation: 150,
                handle: '.submission-header',
                onEnd: function(evt) {
                    fetch('/reorder_submissions', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ new_order: submissions.map(sub => sub.id) })
                    })
                    .then(r => r.json())
                    .then(data => {
                        var statusElem = $('#submission_change_status');
                        if (data.success) {
                            statusElem.html('✓ 顺序已更新').css('color', '#28a745');
                            // 重新排序 submissions 数组
                            var oldIndex = evt.oldIndex;
                            var newIndex = evt.newIndex;
                            if (oldIndex !== newIndex) {
                                var movedItem = submissions.splice(oldIndex, 1)[0];
                                submissions.splice(newIndex, 0, movedItem);
                                renderHistory();
                            }
                            setTimeout(function() { statusElem.html(''); }, 3000);
                        } else {
                            statusElem.html('✗ 排序失败: ' + data.error).css('color', '#d40000');
                            setTimeout(function() { statusElem.html(''); }, 3000);
                        }
                    });
                }
            });
        }
    });
})();