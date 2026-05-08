/**
 * 参数模块独立脚本（无自定义滑块版本）
 * 仅处理新增、删除、拖拽排序，滚动使用浏览器原生滚动条
 */

(function() {
    // DOM 可能已经就绪，先检查再决定如何初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            initParameterModule();
        });
    } else {
        initParameterModule();
    }

    window.initParameterModule = function() {
        const moduleElem = document.getElementById('parameter_module');
        if (!moduleElem) return;

        const tbody = document.getElementById('factor_table_body');
        const factorAlias = moduleElem.getAttribute('data-factor-alias');
        const factorType = moduleElem.getAttribute('data-factor-type') || 'public';

        let paramAliases = [];
        const aliasesAttr = moduleElem.getAttribute('data-param-aliases');
        if (aliasesAttr) {
            try {
                paramAliases = JSON.parse(aliasesAttr);
            } catch(e) {
                console.error('Failed to parse param-aliases:', e);
            }
        }

        // 构建 URL 查询参数
        function _buildFactorUrl(alias) {
            var params = '?factor=' + encodeURIComponent(alias);
            if (factorType === 'custom') {
                params += '&type=custom';
            }
            return params;
        }

        // 刷新整个参数模块（不刷新页面），可选回调在替换完成后执行
        window.reloadParamModule = function reloadParamModule(callback) {
            return fetch(window.location.pathname + _buildFactorUrl(factorAlias))
                .then(res => res.text())
                .then(html => {
                    const parser = new DOMParser();
                    const doc = parser.parseFromString(html, 'text/html');
                    const newModule = doc.getElementById('parameter_module');
                    if (newModule) {
                        const oldModule = document.getElementById('parameter_module');
                        const imported = document.importNode(newModule, true);
                        oldModule.parentNode.replaceChild(imported, oldModule);
                        window.initParameterModule();  // 重新初始化事件
                        if (typeof callback === 'function') callback();
                    }
                })
                .catch(err => console.error('刷新参数模块失败:', err));
        }

        // 绑定事件
        function bindEvents() {
            // 收集当前输入框参数
            function collectParams() {
                const params = {};
                paramAliases.forEach(function(alias) {
                    const input = document.getElementById('param_' + alias);
                    if (input) params[alias] = input.value;
                });
                return params;
            }

            // 执行新增因子（暴露为全局函数，供 HTML onclick 调用）
            function doAdd() {
                const params = collectParams();
                fetch('/add_params', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        factor_family_alias: factorAlias,
                        params: params
                    })
                })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        // 重新加载模块，加载完成后更新输入框为新添加的参数值
                        reloadParamModule(function() {
                            if (data.added_params) {
                                paramAliases.forEach(function(alias) {
                                    const input = document.getElementById('param_' + alias);
                                    if (input && data.added_params[alias] !== undefined) {
                                        input.value = data.added_params[alias];
                                    }
                                });
                            }
                            // 若已确认过时间，自动为新因子应用同一时间范围
                            if (window._confirmedTimeData) {
                                var timeData = Object.assign({}, window._confirmedTimeData);
                                timeData.page_uuid = window._pageUuid || '';
                                fetch('/set_time_range', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify(timeData)
                                }).catch(function() {});
                            }
                        });
                        if (typeof window.refreshICModule === 'function') {
                            window.refreshICModule();
                        }
                    } else {
                        alert('添加失败: ' + data.error);
                    }
                });
            }
            window._doAddParam = doAdd;

            // 新增按钮
            const addBtn = document.querySelector('.add_factor_btn');
            if (addBtn) {
                addBtn.addEventListener('click', doAdd);
            }

            // 输入框回车键触发新增
            paramAliases.forEach(function(alias) {
                const input = document.getElementById('param_' + alias);
                if (input) {
                    input.addEventListener('keydown', function(e) {
                        if (e.key === 'Enter') {
                            e.preventDefault();
                            doAdd();
                        }
                    });
                }
            });

            // 删除按钮（事件委托）
            if (tbody) {
                tbody.addEventListener('click', function(e) {
                    const btn = e.target.closest('.delete_factor_btn');
                    if (!btn) return;
                    const idx = btn.getAttribute('data-factor-idx');
                    fetch('/delete_params', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            factor_family_alias: factorAlias,
                            factor_idx: idx
                        })
                    })
                    .then(res => res.json())
                    .then(data => {
                        if (data.success)
                            reloadParamModule();
                            if (typeof window.refreshICModule === 'function') {
                                window.refreshICModule();
                            }
                        else alert('删除失败: ' + data.error);
                    });
                });
            }

            // 拖拽排序（事件委托）
            if (tbody) {
                let dragStartIdx = null;
                let dragOverIdx = null;

                tbody.addEventListener('dragstart', function(e) {
                    const row = e.target.closest('tr[draggable="true"]');
                    if (!row) return;
                    dragStartIdx = parseInt(row.getAttribute('data-factor-idx'));
                    row.style.opacity = '0.5';
                    e.dataTransfer.effectAllowed = 'move';
                });

                tbody.addEventListener('dragend', function(e) {
                    const row = e.target.closest('tr[draggable="true"]');
                    if (row) row.style.opacity = '';
                    dragStartIdx = null;
                    dragOverIdx = null;
                });

                tbody.addEventListener('dragover', function(e) {
                    const row = e.target.closest('tr[draggable="true"]');
                    if (!row) return;
                    e.preventDefault();
                    dragOverIdx = parseInt(row.getAttribute('data-factor-idx'));
                    row.classList.add('drag-over');
                });

                tbody.addEventListener('dragleave', function(e) {
                    const row = e.target.closest('tr[draggable="true"]');
                    if (row) row.classList.remove('drag-over');
                });

                tbody.addEventListener('drop', function(e) {
                    const row = e.target.closest('tr[draggable="true"]');
                    if (!row) return;
                    e.preventDefault();
                    row.classList.remove('drag-over');
                    if (dragStartIdx !== null && dragOverIdx !== null && dragStartIdx !== dragOverIdx) {
                        fetch('/reorder_params', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                factor_family_alias: factorAlias,
                                from_idx: dragStartIdx,
                                to_idx: dragOverIdx
                            })
                        })
                        .then(res => res.json())
                        .then(data => {
                            if (data.success)
                                reloadParamModule();
                                if (typeof window.refreshICModule === 'function') {
                                    window.refreshICModule();
                                }
                            else alert('排序失败: ' + data.error);
                        });
                    }
                });
            }
        }

        bindEvents();

        // 更新外部参数摘要行
        if (typeof window._updateParamSummary === 'function') {
            window._updateParamSummary();
        }

        // ── 参数模板管理 ─────────────────────────────────────────────────────
        var $pSel   = document.getElementById('params-tpl-select');
        var $pLbl   = document.getElementById('params-tpl-name-label');
        var $pInp   = document.getElementById('params-tpl-name-input');
        var $pStat  = document.getElementById('params-tpl-status');

        if (!$pSel) return;  // 模板栏未渲染时跳过

        function pTplStatus(msg, ok) {
            $pStat.textContent = msg;
            $pStat.style.color = ok ? '#28a745' : '#d40000';
            setTimeout(function() { if ($pStat.textContent === msg) $pStat.textContent = ''; }, 2500);
        }

        function populateParamsTplSelect() {
            var prev = $pSel.value;
            fetch('/api/params_templates/' + encodeURIComponent(factorAlias))
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    while ($pSel.options.length > 1) $pSel.remove(1);
                    if (data.success && data.templates) {
                        data.templates.forEach(function(t) {
                            if ((t.name || '').indexOf('__global_') === 0) return;
                            var opt = document.createElement('option');
                            opt.value = t.id; opt.textContent = t.name;
                            $pSel.appendChild(opt);
                        });
                    }
                    if (prev) $pSel.value = prev;
                    updateParamsTplNameDisplay();
                });
        }

        function updateParamsTplNameDisplay() {
            var id = $pSel.value;
            var name = id ? $pSel.options[$pSel.selectedIndex].text : '';
            if (id) { $pLbl.textContent = name; $pLbl.style.display = ''; }
            else    { $pLbl.style.display = 'none'; }
        }

        $pSel.addEventListener('change', function() {
            $pInp.style.display = 'none';
            updateParamsTplNameDisplay();
        });

        $pLbl.addEventListener('dblclick', function() {
            var id = $pSel.value; if (!id) return;
            var name = $pLbl.textContent;
            if (name.indexOf('__global_') === 0) { pTplStatus('全局模板不允许重命名', false); return; }
            $pInp.value = name;
            $pInp.style.display = ''; $pInp.focus();
            $pLbl.style.display = 'none';
        });

        function commitParamsRename(e) {
            if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== 'Escape') return;
            if (e.key === 'Escape') { $pInp.style.display = 'none'; $pLbl.style.display = ''; return; }
            var id = $pSel.value; if (!id) { $pInp.style.display = 'none'; return; }
            if (($pLbl.textContent || '').indexOf('__global_') === 0) {
                $pInp.style.display = 'none'; $pLbl.style.display = '';
                pTplStatus('全局模板不允许重命名', false); return;
            }
            var newName = $pInp.value.trim();
            if (!newName) { $pInp.style.display = 'none'; $pLbl.style.display = ''; return; }
            fetch('/api/params_templates/' + encodeURIComponent(factorAlias) + '/' + id, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ name: newName })
            }).then(function(r) { return r.json(); }).then(function(data) {
                $pInp.style.display = 'none';
                if (data.success) {
                    pTplStatus('✓ 重命名成功', true);
                    populateParamsTplSelect();
                    setTimeout(function() { $pSel.value = id; updateParamsTplNameDisplay(); }, 300);
                } else {
                    $pLbl.style.display = ''; pTplStatus('重命名失败: ' + data.error, false);
                }
            });
        }
        $pInp.addEventListener('keydown', commitParamsRename);
        $pInp.addEventListener('blur',    commitParamsRename);

        document.getElementById('params-tpl-load-btn').addEventListener('click', function() {
            loadSelectedParamsTemplate();
        });

        // 暴露参数模板加载函数，供全局模板等外部模块调用
        // 用法：window._loadParamsTemplate() 加载下拉框选中的模板
        window._loadParamsTemplate = function() {
            return loadSelectedParamsTemplate();
        };

        // 暴露参数模板保存函数，供全局模板等外部模块调用
        // 用法：window._saveCurrentParamsAsTemplate(name) 返回 Promise<{success, id}>
        window._saveCurrentParamsAsTemplate = function(name) {
            return fetch('/api/current_params/' + encodeURIComponent(factorAlias))
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    var params_list = data.params_list || [];
                    if (params_list.length === 0) {
                        var tbodyEl = document.getElementById('factor_table_body');
                        if (tbodyEl && paramAliases.length > 0) {
                            var rows = tbodyEl.querySelectorAll('tr');
                            rows.forEach(function(row) {
                                if (row.id === 'add_row') {
                                    var rowParams = {};
                                    var hasValue = false;
                                    paramAliases.forEach(function(alias) {
                                        var inp = document.getElementById('param_' + alias);
                                        if (inp && inp.value !== '') {
                                            rowParams[alias] = inp.value;
                                            hasValue = true;
                                        }
                                    });
                                    if (hasValue) params_list.push(rowParams);
                                } else {
                                    var cells = row.querySelectorAll('td');
                                    if (cells.length >= paramAliases.length + 1) {
                                        var rowParams = {};
                                        for (var i = 0; i < paramAliases.length; i++) {
                                            var tdText = (cells[i + 1].textContent || '').trim();
                                            if (tdText) rowParams[paramAliases[i]] = tdText;
                                        }
                                        if (Object.keys(rowParams).length > 0) {
                                            params_list.push(rowParams);
                                        }
                                    }
                                }
                            });
                        }
                    }
                    if (params_list.length === 0) {
                        return { success: false, error: '当前没有参数可保存' };
                    }
                    return fetch('/api/params_templates/' + encodeURIComponent(factorAlias), {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ name: name, params_list: params_list })
                    }).then(function(r) { return r.json(); });
                });
        };

        function loadSelectedParamsTemplate() {
            var id = $pSel.value;
            if (!id) { pTplStatus('请先选择一个模板', false); return Promise.resolve(); }
            // 先获取当前参数列表，再与模板参数去重合并
            return Promise.all([
                fetch('/api/params_templates/' + encodeURIComponent(factorAlias) + '/' + id).then(function(r) { return r.json(); }),
                fetch('/api/current_params/' + encodeURIComponent(factorAlias)).then(function(r) { return r.json(); })
            ]).then(function(results) {
                var tplData = results[0];
                var curData = results[1];
                if (!tplData.success) { pTplStatus('加载失败: ' + (tplData.error || '未知错误'), false); return; }
                
                var tplList = tplData.template.params_list || [];
                var curList = (curData.success && curData.params_list) ? curData.params_list : [];
                
                // 去重合并：将模板参数追加到当前参数（跳过已存在的）
                var merged = curList.slice();  // 先复制当前参数
                tplList.forEach(function(tplParams) {
                    // 检查是否已存在相同的参数组合
                    var isDuplicate = merged.some(function(existing) {
                        var keys = Object.keys(tplParams);
                        if (keys.length === 0) return false;
                        return keys.every(function(k) {
                            return String(existing[k] || '') === String(tplParams[k] || '');
                        });
                    });
                    if (!isDuplicate) {
                        merged.push(tplParams);
                    }
                });
                
                if (merged.length === curList.length) {
                    pTplStatus('模板中的参数组合已全部存在，无需添加', true); return;
                }
                
                var addedCount = merged.length - curList.length;
                return fetch('/replace_params', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ factor_family_alias: factorAlias, params_list: merged })
                }).then(function(r) { return r.json(); }).then(function(res) {
                    if (!res.success) { pTplStatus('加载失败: ' + res.error, false); return; }
                    reloadParamModule(function() {
                        pTplStatus('✓ 已加载，新增 ' + addedCount + ' 组参数（跳过 ' + (tplList.length - addedCount) + ' 组重复）', true);
                    });
                    if (typeof window.refreshICModule === 'function') window.refreshICModule();
                });
            });
        }

        document.getElementById('params-tpl-save-btn').addEventListener('click', function() {
            // 优先从后端获取，如果后端为空则从DOM收集
            fetch('/api/current_params/' + encodeURIComponent(factorAlias))
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    var params_list = data.params_list || [];
                    // 后端为空时从DOM收集：
                    // 1) 从已渲染的因子行（tbody中除add_row外的tr）收集，
                    //    每行的td文本按paramAliases顺序对应各参数值
                    // 2) 如果add_row输入框有值，也收集为新组合
                    if (params_list.length === 0) {
                        var tbodyEl = document.getElementById('factor_table_body');
                        if (tbodyEl && paramAliases.length > 0) {
                            var rows = tbodyEl.querySelectorAll('tr');
                            rows.forEach(function(row) {
                                if (row.id === 'add_row') {
                                    // 从新增行的输入框收集（id="param_<alias>"）
                                    var rowParams = {};
                                    var hasValue = false;
                                    paramAliases.forEach(function(alias) {
                                        var inp = document.getElementById('param_' + alias);
                                        if (inp && inp.value !== '') {
                                            rowParams[alias] = inp.value;
                                            hasValue = true;
                                        }
                                    });
                                    if (hasValue) params_list.push(rowParams);
                                } else {
                                    // 从已渲染因子行收集（td文本顺序 = paramAliases顺序）
                                    var cells = row.querySelectorAll('td');
                                    if (cells.length >= paramAliases.length + 1) {
                                        var rowParams = {};
                                        for (var i = 0; i < paramAliases.length; i++) {
                                            var tdText = (cells[i + 1].textContent || '').trim();
                                            if (tdText) rowParams[paramAliases[i]] = tdText;
                                        }
                                        if (Object.keys(rowParams).length > 0) {
                                            params_list.push(rowParams);
                                        }
                                    }
                                }
                            });
                        }
                    }
                    if (params_list.length === 0) {
                        pTplStatus('当前没有参数可保存', false); return;
                    }
                    var name = prompt('请输入模板名称：');
                    if (!name || !name.trim()) return;
                    fetch('/api/params_templates/' + encodeURIComponent(factorAlias), {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ name: name.trim(), params_list: params_list })
                    }).then(function(r) { return r.json(); }).then(function(res) {
                        if (res.success) {
                            pTplStatus('✓ 模板已保存', true);
                            populateParamsTplSelect();
                            setTimeout(function() { $pSel.value = res.id; updateParamsTplNameDisplay(); }, 300);
                        } else { pTplStatus('保存失败: ' + res.error, false); }
                    });
                });
        });

        document.getElementById('params-tpl-update-btn').addEventListener('click', function() {
            var id = $pSel.value;
            if (!id) { pTplStatus('请先选择一个模板', false); return; }
            fetch('/api/current_params/' + encodeURIComponent(factorAlias))
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    var params_list = data.params_list || [];
                    if (params_list.length === 0) {
                        var tbodyEl = document.getElementById('factor_table_body');
                        if (tbodyEl && paramAliases.length > 0) {
                            var rows = tbodyEl.querySelectorAll('tr');
                            rows.forEach(function(row) {
                                if (row.id === 'add_row') {
                                    var rowParams = {};
                                    var hasValue = false;
                                    paramAliases.forEach(function(alias) {
                                        var inp = document.getElementById('param_' + alias);
                                        if (inp && inp.value !== '') {
                                            rowParams[alias] = inp.value;
                                            hasValue = true;
                                        }
                                    });
                                    if (hasValue) params_list.push(rowParams);
                                } else {
                                    var cells = row.querySelectorAll('td');
                                    if (cells.length >= paramAliases.length + 1) {
                                        var rowParams = {};
                                        for (var i = 0; i < paramAliases.length; i++) {
                                            var tdText = (cells[i + 1].textContent || '').trim();
                                            if (tdText) rowParams[paramAliases[i]] = tdText;
                                        }
                                        if (Object.keys(rowParams).length > 0) {
                                            params_list.push(rowParams);
                                        }
                                    }
                                }
                            });
                        }
                    }
                    if (params_list.length === 0) {
                        pTplStatus('当前没有参数可保存', false); return;
                    }
                    fetch('/api/params_templates/' + encodeURIComponent(factorAlias) + '/' + id, {
                        method: 'PUT',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ params_list: params_list })
                    }).then(function(r) { return r.json(); }).then(function(res) {
                        pTplStatus(res.success ? '✓ 模板已更新' : '更新失败: ' + res.error, res.success);
                    });
                });
        });

        document.getElementById('params-tpl-delete-btn').addEventListener('click', function() {
            var id = $pSel.value;
            if (!id) { pTplStatus('请先选择一个模板', false); return; }
            var name = $pSel.options[$pSel.selectedIndex].text;
            if (!confirm('确定删除模板「' + name + '」？')) return;
            fetch('/api/params_templates/' + encodeURIComponent(factorAlias) + '/' + id, { method: 'DELETE' })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.success) { pTplStatus('✓ 模板已删除', true); populateParamsTplSelect(); }
                    else { pTplStatus('删除失败: ' + data.error, false); }
                });
        });

        populateParamsTplSelect();
        // ── 参数模板管理 END ──────────────────────────────────────────────────
    };
})();
