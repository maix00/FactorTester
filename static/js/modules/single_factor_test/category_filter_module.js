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
    var $moduleContainer = null;  // PS.render() 的容器

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
        var $container = window.ProductSelector.getSubmissionContainer($moduleContainer);
        if (!$container || !$container.length) return;

        window.ProductSelector.renderSubmissionHistory(submissions, expandedState, $container, {
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
                var el = document.getElementById('category_filter_module');
                if (el) el.innerHTML = '<div style="color:#d40000;text-align:center;padding:20px;">产品树加载失败：jQuery 未就绪</div>';
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

        $moduleContainer = $('#category_filter_module');
        if (!$moduleContainer.length) return;

        var PS = window.ProductSelector;

        // 如果已渲染过，跳过重新渲染（保留树实例）
        if ($moduleContainer.find('.ps-body').length) return;

        // 读取隐藏的 toolbar 模板 HTML 并删除模板 DOM
        var toolbarHTML = '';
        var $toolbarTpl = $moduleContainer.find('#category-toolbar-tpl');
        if ($toolbarTpl.length) {
            toolbarHTML = $toolbarTpl.html();
            $toolbarTpl.remove();
        }

        // 统一布局渲染
        PS.render($moduleContainer, {
            title: '🌳 产品类别筛选',
            submitLabel: '✅ 提交选中产品',
            toolbar: toolbarHTML,
            onSubmit: submitSelectedProducts
        });

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
                    maxWidth: 'min(54vw, 620px)',
                    maxWidthFallback: 620,
                    desktopMediaQuery: '(max-width: 1200px)',
                    mobileInnerMaxHeight: '400px'
                });
            }
        }
        // 抽屉打开时同步 resize 尺寸
        var drawer = document.getElementById('category-drawer');
        if (drawer && categoryTreeSizer && typeof categoryTreeSizer.sync === 'function') {
            drawer.addEventListener('transitionend', function() {
                if (drawer.classList.contains('open')) {
                    categoryTreeSizer.sync();
                }
            });
        }

        // 提交按钮委托（已在 render 中绑定，此处保留兼容）
        $(document)
            .off('click.categorySubmit', '.ps-submit-btn')
            .on('click.categorySubmit', '.ps-submit-btn', submitSelectedProducts);

        // SortableJS 拖拽已由 renderHistory() → PS.renderSubmissionHistory() 内部处理

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
                            label: s.label || '',
                            product_group: s.product_group || ''
                        };
                    });
                    if (typeof window._applySubmissions === 'function') {
                        window._applySubmissions(normalized);
                    } else {
                        submissions = normalized;
                        window.submissions = submissions;
                        window.submissionRecords = submissions;
                        renderHistory();
                        refreshSubmissionDependents();
                    }
                    tplStatus('✓ 模板已加载（' + normalized.length + '条提交）', true);
                });
        });

        function collectSubmissionsForTemplate() {
            return submissions.map(function(s) {
                var entry = { label: s.label || '' };
                if (s.product_group) {
                    entry.product_group = s.product_group;
                    // 也带上 paths 作为 fallback（模板加载时优先用 product_group）
                    entry.paths = (s.paths || []).slice();
                } else {
                    entry.paths = (s.paths || []).slice();
                }
                return entry;
            });
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

        // ── 从产品组导入（委托给统一的 ProductSelector）────────────────────────
        $('#pg-import-btn').on('click', function() {
            window.ProductSelector.openGroupImport(function(groupName, paths) {
                var newId = 'pg-' + Date.now();
                fetch('/submit_selected_products', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        selected_paths: paths,
                        id_time: newId,
                        page_uuid: window._pageUuid || ''
                    })
                })
                .then(function(r) { return r.json(); })
                .then(function(submitResp) {
                    if (!submitResp.success) {
                        alert('提交失败: ' + (submitResp.error || '未知错误'));
                        return;
                    }
                    syncFromServer(submitResp.submissions || []);
                    var newSub = submissions.find(function(s) { return String(s.id) === String(newId); });
                    if (newSub) {
                        newSub.product_group = groupName;
                        newSub.label = groupName;
                    }
                    renderHistory();
                    refreshSubmissionDependents();
                });
            });
        });
        // ── 从产品组导入 END ─────────────────────────────────────────────────

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
            refreshSubmissionDependents();
        };
    }

    window.ensureCategoryTreeReady = function() {
        var $ = window.jQuery;
        if (!$) return;
        if (!treeInstance) {
            initCategoryFilterModule(0);
        }
    };

    initCategoryFilterModule();
})();
