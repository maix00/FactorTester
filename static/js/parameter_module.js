/**
 * 参数模块独立脚本（无自定义滑块版本）
 * 仅处理新增、删除、拖拽排序，滚动使用浏览器原生滚动条
 */

(function() {
    document.addEventListener('DOMContentLoaded', function() {
        initParameterModule();
    });

    window.initParameterModule = function() {
        const moduleElem = document.getElementById('parameter_module');
        if (!moduleElem) return;

        const tbody = document.getElementById('factor_table_body');
        const factorAlias = moduleElem.getAttribute('data-factor-alias');
        
        let paramAliases = [];
        const aliasesAttr = moduleElem.getAttribute('data-param-aliases');
        if (aliasesAttr) {
            try {
                paramAliases = JSON.parse(aliasesAttr);
            } catch(e) {
                console.error('Failed to parse param-aliases:', e);
            }
        }

        // 刷新整个参数模块（不刷新页面），可选回调在替换完成后执行
        function reloadParamModule(callback) {
            fetch(window.location.pathname + '?factor=' + encodeURIComponent(factorAlias))
                .then(res => res.text())
                .then(html => {
                    const parser = new DOMParser();
                    const doc = parser.parseFromString(html, 'text/html');
                    const newModule = doc.getElementById('parameter_module');
                    if (newModule) {
                        const oldModule = document.getElementById('parameter_module');
                        oldModule.parentNode.replaceChild(newModule, oldModule);
                        window.initParameterModule();  // 重新初始化事件
                        if (typeof callback === 'function') callback();
                    }
                })
                .catch(err => alert('刷新参数模块失败: ' + err));
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

            // 执行新增因子
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
                                fetch('/set_time_range', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify(window._confirmedTimeData)
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
    };
})();