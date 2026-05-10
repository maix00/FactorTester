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
    var treeInstance = null;
    var categoryTreeSizer = null;

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
                product_count: s.product_count,
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
    }

    // 辅助函数：渲染右侧历史记录
    function renderHistory() {
        var html = '';
        submissions.forEach(function(sub, index) {
            var isExpanded = expandedState[index] || {};
            html += '<div class="submission-item" data-index="' + index + '" style="width:100%; box-sizing:border-box; border:1px solid #e1e4e8; border-radius:8px; margin-bottom:12px; background:#fff; overflow:hidden;">';
            html += '  <div class="submission-header" style="background:#f6f8fa; padding:8px 36px 8px 12px; cursor:move; position:relative; border-bottom:1px solid #e1e4e8; min-height:52px;">';
            var labelHtml = sub.label
                ? '<span class="sub-label-text" data-index="' + index + '" title="点击重命名" style="color:#0078d4;font-weight:600;cursor:pointer;font-size:12px;">' + sub.label + '</span>'
                : '<span class="sub-label-add" data-index="' + index + '" title="点击添加名称" style="color:#aaa;cursor:pointer;font-size:12px;">[添加名称]</span>';
            var labelInput = '<input class="sub-label-input" data-index="' + index + '" type="text" value="' + (sub.label||'').replace(/"/g,'&quot;') + '" placeholder="输入名称后 Enter 确认" style="display:none;font-size:12px;padding:2px 6px;border:1px solid #0078d4;border-radius:4px;width:140px;vertical-align:middle;">';
            // 信息行：序号 + 序列号 + 时间
            html += '    <div style="font-size:13px;display:flex;align-items:center;gap:4px;flex-wrap:wrap;margin-bottom:4px;">'
                + '<i class="fas fa-grip-vertical" style="color:#888; flex-shrink:0;"></i>'
                + '<strong style="flex-shrink:0;">#' + (index+1) + '</strong>'
                + '<span style="flex-shrink:0;margin:0 4px;">' + sub.factor_tester_serial + '</span>'
                + '<span style="color:#888;font-size:12px;flex-shrink:0;">(' + sub.timestamp + ')</span>'
                + (sub.count_desc ? ' <span style="color:#d00;flex-shrink:0;">' + sub.count_desc + '</span>' : '')
                + '</div>';
            // 标签名称行：span 和 input 同行，inline-block 避免抖动
            html += '    <div style="line-height:24px; min-height:24px;">' + labelHtml + labelInput + '</div>';
            // 删除按钮放在 header 右下角
            html += '    <button class="delete-submission" data-index="' + index + '" style="position:absolute; right:8px; bottom:8px; background:transparent; border:none; color:#d00; cursor:pointer; font-size:14px;"><i class="fas fa-trash"></i></button>';
            html += '  </div>';
            html += '  <div style="width:100%; box-sizing:border-box; padding:8px 12px; overflow-x:auto;">';
            html += '    <table style="width:100%; min-width:100%; border-collapse:collapse; table-layout:auto;">';
            sub.paths.forEach(function(path, pathIdx) {
                var rowId = 'path-' + index + '-' + pathIdx;
                var expanded = isExpanded[path] || false;
                var pathDisplay = path;
                if (sub.pathsDescMap && sub.pathsDescMap[path]) {
                    pathDisplay = path + ' <span style="color:#888;font-size:12px;">' + sub.pathsDescMap[path] + '</span>';
                }
                html += '      <tr class="path-row" data-path="' + path.replace(/"/g, '&quot;') + '" data-sub-index="' + index + '" data-path-index="' + pathIdx + '">';
                html += '        <td style="padding:4px 0; border-bottom:1px solid #f0f0f0; min-width:0; overflow-wrap:anywhere; word-break:break-word;">';
                html += '          <div style="display:flex;align-items:flex-start;">';
                html += '            <span class="path-text" style="cursor:pointer; font-size:13px; margin-left:6px; flex:1; min-width:0; overflow-wrap:anywhere; word-break:break-word;">' + pathDisplay + '</span>';
                html += '            <button class="delete-path" data-sub-index="' + index + '" data-path-index="' + pathIdx + '" style="flex-shrink:0; background:transparent; border:none; color:#d00; cursor:pointer; padding:0 8px;"><i class="fas fa-times"></i></button>';
                html += '          </div>';
                html += '        </td>';
                html += '      </tr>';
                if (expanded) {
                    html += '      <tr class="product-detail-row" id="detail-' + index + '-' + pathIdx + '">';
                    html += '        <td style="width:100%; box-sizing:border-box; padding:8px 0 8px 20px; background:#fafbfc;">';
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
                    '<td style="width:100%; box-sizing:border-box; padding:8px 0 8px 20px; background:#fafbfc;">' +
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
                    statusElem.html('<div>✓ 路径已删除</div>').css('color', '#28a745');
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
                                statusElem.html('<div>✓ 提交已删除</div>').css('color', '#28a745');
                            } else {
                                statusElem.html('<div>✗ 删除提交失败: ' + data2.error + '</div>').css('color', '#d40000');
                            }
                            renderHistory();
                            setTimeout(function() { statusElem.html(''); }, 3000);
                        });
                    } else {
                        renderHistory();
                        setTimeout(function() { statusElem.html(''); }, 3000);
                    }
                } else {
                    statusElem.html('<div>✗ 删除失败: ' + data.error + '</div>').css('color', '#d40000');
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
                    statusElem.html('<div>✓ 提交已删除</div>').css('color', '#28a745');
                    // 用后端返回的列表同步本地
                    if (data.submissions) {
                        syncFromServer(data.submissions);
                    } else {
                        submissions.splice(index, 1);
                        renderHistory();
                    }
                    setTimeout(function() { statusElem.html(''); }, 3000);
                } else {
                    statusElem.html('<div>✗ 删除失败: ' + data.error + '</div>').css('color', '#d40000');
                    setTimeout(function() { statusElem.html(''); }, 3000);
                }
            });
        });

        // 新增：通知 IC 模块更新
        if (typeof window.renderICTabs === 'function') {
            window.renderICTabs(submissions);
        }
        if (typeof window.renderGroupTabs === 'function') {
            window.renderGroupTabs(submissions);
        }

        // ── 提交名称（label）行内编辑 ────────────────────────────────────────
        function commitLabelEdit($inp) {
            var idx = parseInt($inp.data('index'), 10);
            var val = $inp.val().trim();
            submissions[idx].label = val || '';
            $inp.hide();
            // Update display without full re-render
            var $lbl = $('.sub-label-text[data-index="' + idx + '"], .sub-label-add[data-index="' + idx + '"]');
            if (val) {
                $lbl.replaceWith('<span class="sub-label-text" data-index="' + idx + '" title="点击重命名" style="color:#0078d4;font-weight:600;cursor:pointer;font-size:12px;margin-right:4px;">' + val + '</span>');
            } else {
                $lbl.replaceWith('<span class="sub-label-add" data-index="' + idx + '" title="点击添加名称" style="color:#aaa;cursor:pointer;font-size:12px;margin-right:4px;">[添加名称]</span>');
            }
            // Notify IC and Group modules
            if (typeof window.renderICTabs === 'function') window.renderICTabs(submissions);
            if (typeof window.renderGroupTabs === 'function') window.renderGroupTabs(submissions);
        }

        $(document).off('click.sublabel').on('click.sublabel', '.sub-label-text, .sub-label-add', function() {
            var idx = $(this).data('index');
            var $inp = $('.sub-label-input[data-index="' + idx + '"]');
            $(this).hide();
            $inp.show().focus().select();
        });

        $(document).off('keydown.sublabel').on('keydown.sublabel', '.sub-label-input', function(e) {
            if (e.key === 'Enter') { commitLabelEdit($(this)); }
            if (e.key === 'Escape') {
                var idx = $(this).data('index');
                $(this).hide();
                var val = submissions[idx] ? (submissions[idx].label || '') : '';
                var $lbl = val
                    ? $('<span class="sub-label-text" data-index="' + idx + '" title="点击重命名" style="color:#0078d4;font-weight:600;cursor:pointer;font-size:12px;margin-right:4px;">' + val + '</span>')
                    : $('<span class="sub-label-add" data-index="' + idx + '" title="点击添加名称" style="color:#aaa;cursor:pointer;font-size:12px;margin-right:4px;">[添加名称]</span>');
                $(this).before($lbl);
            }
        });

        $(document).off('blur.sublabel').on('blur.sublabel', '.sub-label-input', function() {
            if ($(this).is(':visible')) commitLabelEdit($(this));
        });
        // ── 提交名称编辑 END ─────────────────────────────────────────────────
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

    function getCurrentTimeRange() {
        if (typeof window.getSharedRuntimeTimeRange === 'function') {
            return window.getSharedRuntimeTimeRange();
        }
        // 根据你的时间范围模块的输入框 ID 来读取
        const startYear = document.getElementById('start_year').value;
        const startMonth = document.getElementById('start_month').value.padStart(2, '0');
        const startDay = document.getElementById('start_day').value.padStart(2, '0');
        const startHour = document.getElementById('start_hour').value.padStart(2, '0');
        const startMinute = document.getElementById('start_minute').value.padStart(2, '0');
        const endYear = document.getElementById('end_year').value;
        const endMonth = document.getElementById('end_month').value.padStart(2, '0');
        const endDay = document.getElementById('end_day').value.padStart(2, '0');
        const endHour = document.getElementById('end_hour').value.padStart(2, '0');
        const endMinute = document.getElementById('end_minute').value.padStart(2, '0');

        return {
            start_date: `${startYear}-${startMonth}-${startDay}`,
            start_time: `${startHour}:${startMinute}`,
            end_date: `${endYear}-${endMonth}-${endDay}`,
            end_time: `${endHour}:${endMinute}`
        };
    }

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
                    // 用后端返回的 submissions 同步
                    if (data.submissions) {
                        syncFromServer(data.submissions);
                    }
                }
            } else {
                statusSpan.html('提交失败: ' + (data.error || '未知错误')).css('color', '#d40000');
            }
            setTimeout(function() { statusSpan.html(''); }, 3000);
        });
    }

    // 初始化 Fancytree 和 Sortable。单因子测试页面会动态替换内容，
    // 外部依赖脚本（jQuery/Fancytree/Sortable）可能比本模块稍晚就绪；
    // 因此这里不用直接依赖 $(ready)，而是显式等待依赖，避免抽屉停在“加载产品树...”。
    function initCategoryFilterModule(retryCount) {
        retryCount = retryCount || 0;
        if (!window.jQuery) {
            if (retryCount < 80) {
                setTimeout(function() { initCategoryFilterModule(retryCount + 1); }, 50);
            } else {
                var el = document.getElementById('tree-container');
                if (el) el.innerHTML = '<div style="color:#d40000;text-align:center;padding:20px;">产品树加载失败：jQuery 未就绪</div>';
            }
            return;
        }
        var $ = window.jQuery;
        if (!$.fn || typeof $.fn.fancytree !== 'function') {
            var $waitingContainer = $("#tree-container");
            if ($waitingContainer.length) {
                $waitingContainer.html('<div style="color:#888;text-align:center;padding:20px;">产品树插件加载中...</div>');
            }
            if (retryCount < 80) {
                setTimeout(function() { initCategoryFilterModule(retryCount + 1); }, 50);
            } else if ($waitingContainer.length) {
                $waitingContainer.html('<div style="color:#d40000;text-align:center;padding:20px;">产品树加载失败：Fancytree 未就绪</div>');
            }
            return;
        }

        var $container = $("#tree-container");
        if (!_hasMountedTree($container)) {
            treeInstance = null;
        }

        if (typeof window.setupResizableTreeContainer === 'function') {
            categoryTreeSizer = window.setupResizableTreeContainer({
                outerSelector: '#category-tree-panel',
                innerSelector: '#tree-container',
                minWidth: 260,
                initialWidth: 340,
                maxWidth: 'min(54vw, 620px)',
                outerMaxWidth: 'min(58vw, 700px)',
                desktopMediaQuery: '(max-width: 1200px)',
                mobileInnerMaxHeight: '400px'
            });
        }
        var drawer = document.getElementById('category-drawer');
        if (drawer && categoryTreeSizer && typeof categoryTreeSizer.sync === 'function') {
            drawer.addEventListener('transitionend', function() {
                if (drawer.classList.contains('open')) {
                    categoryTreeSizer.sync();
                }
            });
        }

        // 若之前已初始化，先销毁后重建（处理内容热替换后树丢失/失效）。
        if (_hasMountedTree($container)) {
            try {
                $container.fancytree('destroy');
            } catch (e) {}
            treeInstance = null;
        }

        // 清空容器，确保没有残留内容
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
        $("#submit-selected").off('click').on('click', submitSelectedProducts);

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

        // ── 路径模板管理 ──────────────────────────────────────────────────────

        function tplStatus(msg, ok) {
            var $s = $('#tpl-status');
            $s.text(msg).css('color', ok ? '#28a745' : '#d40000');
            setTimeout(function() { if ($s.text() === msg) $s.text(''); }, 3000);
        }

        function collectAllCurrentPaths() {
            var paths = [];
            submissions.forEach(function(sub) {
                sub.paths.forEach(function(p) { if (!paths.includes(p)) paths.push(p); });
            });
            return paths;
        }

        function populateTplSelect(selectId) {
            var $sel = $('#' + (selectId || 'tpl-select'));
            var prev = $sel.val();
            fetch('/api/path_templates')
                .then(r => r.json())
                .then(function(data) {
                    $sel.empty().append('<option value="">— 选择模板 —</option>');
                    if (data.success && data.templates) {
                        data.templates.forEach(function(t) {
                            $sel.append($('<option>').val(t.id).text(t.name));
                        });
                    }
                    if (prev) $sel.val(prev);
                });
        }

        populateTplSelect();

        // 加载模板：清空当前所有提交，批量重新提交模板中存储的所有 submission
        $('#tpl-load-btn').on('click', function() {
            var id = $('#tpl-select').val();
            if (!id) { tplStatus('请先选择一个模板', false); return; }
            fetch('/api/path_templates/' + id)
                .then(r => r.json())
                .then(async function(data) {
                    if (!data.success) { tplStatus('加载失败: ' + data.error, false); return; }
                    var tplSubs = data.template.submissions;
                    if (!tplSubs || tplSubs.length === 0) { tplStatus('该模板没有提交记录', false); return; }
                    var replaceData = await fetch('/replace_submissions', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            template_submissions: tplSubs,
                            page_uuid: window._pageUuid || ''
                        })
                    }).then(function(r) { return r.json(); });
                    if (!replaceData.success) { tplStatus('加载失败: ' + (replaceData.error || '未知错误'), false); return; }

                    var timeRange = getCurrentTimeRange();
                    var normalized = (replaceData.replaced_submissions || []).map(function(s) {
                        return {
                            id: s.id,
                            paths: s.paths || [],
                            pathsDescMap: {},
                            factor_tester_name: s.factor_tester_name,
                            factor_tester_serial: s.factor_tester_serial,
                            count_desc: s.count_desc,
                            timestamp: new Date().toLocaleTimeString(),
                            start_date: timeRange.start_date,
                            end_date: timeRange.end_date,
                            start_time: timeRange.start_time,
                            end_time: timeRange.end_time,
                            label: s.label || ''
                        };
                    });
                    if (typeof window._applySubmissions === 'function') {
                        window._applySubmissions(normalized);
                    } else {
                        submissions = normalized;
                        window.submissions = submissions;
                        renderHistory();
                    }
                    tplStatus('✓ 模板已加载（' + normalized.length + '条提交）', true);
                });
        });

        function collectSubmissionsForTemplate() {
            return submissions.map(function(s) { return { label: s.label || '', paths: s.paths.slice() }; });
        }

        // 另存为新模板
        $('#tpl-save-btn').on('click', function() {
            if (submissions.length === 0) { tplStatus('当前没有提交记录可保存', false); return; }
            var name = prompt('请输入模板名称：');
            if (!name || !name.trim()) return;
            fetch('/api/path_templates', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ name: name.trim(), submissions: collectSubmissionsForTemplate() })
            })
            .then(r => r.json())
            .then(function(data) {
                if (data.success) {
                    tplStatus('✓ 模板已保存', true);
                    populateTplSelect();
                    // 自动选中新模板
                    setTimeout(function() { $('#tpl-select').val(data.id); }, 300);
                } else {
                    tplStatus('保存失败: ' + data.error, false);
                }
            });
        });

        // 覆盖更新选中模板的提交列表
        $('#tpl-update-btn').on('click', function() {
            var id = $('#tpl-select').val();
            if (!id) { tplStatus('请先选择一个模板', false); return; }
            if (submissions.length === 0) { tplStatus('当前没有提交记录可保存', false); return; }
            fetch('/api/path_templates/' + id, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ submissions: collectSubmissionsForTemplate() })
            })
            .then(r => r.json())
            .then(function(data) {
                tplStatus(data.success ? '✓ 模板已更新' : '更新失败: ' + data.error, data.success);
            });
        });

        // 双击下拉选项名称 → 行内重命名（通过双击 select 旁的名称标签实现）
        function updateTplNameDisplay() {
            var $sel = $('#tpl-select');
            var name = $sel.find('option:selected').text();
            var id = $sel.val();
            var $lbl = $('#tpl-name-label');
            if (id) {
                $lbl.text(name).show();
            } else {
                $lbl.hide();
            }
        }

        $('#tpl-select').on('change', function() {
            $('#tpl-name-input').hide();
            updateTplNameDisplay();
        });

        // 双击名称标签 → 变为输入框
        $(document).on('dblclick', '#tpl-name-label', function() {
            var id = $('#tpl-select').val();
            if (!id) return;
            var $lbl = $(this);
            var $inp = $('#tpl-name-input');
            $inp.val($lbl.text()).show().focus();
            $lbl.hide();
        });

        // 输入框 blur 或 Enter → 提交重命名
        $(document).on('keydown blur', '#tpl-name-input', function(e) {
            if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== 'Escape') return;
            var $inp = $(this);
            if (e.key === 'Escape') {
                $inp.hide();
                $('#tpl-name-label').show();
                return;
            }
            var id = $('#tpl-select').val();
            if (!id) { $inp.hide(); return; }
            var newName = $inp.val().trim();
            if (!newName) { $inp.hide(); $('#tpl-name-label').show(); return; }
            fetch('/api/path_templates/' + id, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ name: newName })
            })
            .then(r => r.json())
            .then(function(data) {
                $inp.hide();
                if (data.success) {
                    populateTplSelect();
                    setTimeout(function() {
                        $('#tpl-select').val(id);
                        updateTplNameDisplay();
                    }, 300);
                    tplStatus('✓ 重命名成功', true);
                } else {
                    $('#tpl-name-label').show();
                    tplStatus('重命名失败: ' + data.error, false);
                }
            });
        });

        // 删除选中模板
        $('#tpl-delete-btn').on('click', function() {
            var id = $('#tpl-select').val();
            if (!id) { tplStatus('请先选择一个模板', false); return; }
            var name = $('#tpl-select option:selected').text();
            if (!confirm('确定删除模板「' + name + '」？')) return;
            fetch('/api/path_templates/' + id, { method: 'DELETE' })
                .then(r => r.json())
                .then(function(data) {
                    if (data.success) {
                        tplStatus('✓ 模板已删除', true);
                        populateTplSelect();
                    } else {
                        tplStatus('删除失败: ' + data.error, false);
                    }
                });
        });

        // ── 路径模板管理 END ──────────────────────────────────────────────────

        // 暴露给单因子设置快照模块
        window._getCurrentSubmissions = function() {
            return submissions;
        };
        window._applySubmissions = function(newSubmissions) {
            submissions = newSubmissions;
            window.submissions = newSubmissions;
            window.submissionRecords = newSubmissions;
            expandedState = {};
            renderHistory();
            if (typeof updateCategorySummary === 'function') updateCategorySummary();
            // 触发 IC/Group 模块刷新
            if (typeof window.renderICTabs === 'function') window.renderICTabs(submissions);
            if (typeof window.renderGroupTabs === 'function') window.renderGroupTabs(submissions);
        };
    }

    window.ensureCategoryTreeReady = function() {
        var $ = window.jQuery;
        if (!$) return;
        var $container = $("#tree-container");
        if (!$container.length) return;
        if (_hasMountedTree($container)) return;
        initCategoryFilterModule(0);
    };

    initCategoryFilterModule();
})();
