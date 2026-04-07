// 参数模块功能

function initParameterModule() {
    // 获取参数模块容器
    const module = document.getElementById('parameter_module');
    if (!module) return;
    
    // 从模块容器的 data 属性获取配置（需要在 HTML 中设置这些属性）
    const factorFamilyAlias = module.getAttribute('data-factor-alias');
    const paramAliasesAttr = module.getAttribute('data-param-aliases');
    const paramAliases = paramAliasesAttr ? JSON.parse(paramAliasesAttr) : [];
    
    if (!factorFamilyAlias) {
        console.error('parameter_module: 缺少 factorFamilyAlias');
        return;
    }
    
    function reloadPage() {
        location.reload();
    }
    
    // 新增按钮
    const addBtn = document.querySelector('.add_factor_btn');
    if (addBtn) {
        // 移除已有的监听器（避免重复绑定）
        const newAddBtn = addBtn.cloneNode(true);
        addBtn.parentNode.replaceChild(newAddBtn, addBtn);
        
        newAddBtn.addEventListener('click', function() {
            const paramValues = {};
            paramAliases.forEach(function(alias) {
                const el = document.getElementById('param_' + alias);
                if (el) paramValues[alias] = el.value;
            });
            
            fetch('/add_params', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    factor_family_alias: factorFamilyAlias,
                    params: paramValues
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    reloadPage();
                } else {
                    alert('添加失败: ' + data.error);
                }
            })
            .catch(error => alert('请求失败: ' + error));
        });
    }
    
    // 删除按钮
    document.querySelectorAll('.delete_factor_btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            const idx = btn.getAttribute('data-factor-idx');
            if (confirm('确定要删除这个因子吗？')) {
                fetch('/delete_params', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        factor_family_alias: factorFamilyAlias,
                        factor_idx: idx
                    })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) reloadPage();
                    else alert('删除失败: ' + data.error);
                });
            }
        });
    });
    
    // 刷新参数表格
    function reloadParamTable() {
        fetch(window.location.pathname + '?factor=' + factorFamilyAlias)
            .then(r => r.text())
            .then(html => {
                var parser = new DOMParser();
                var doc = parser.parseFromString(html, 'text/html');
                var newTable = doc.getElementById('param_table_scroll');
                var oldTable = document.getElementById('param_table_scroll');
                if (newTable && oldTable) {
                    oldTable.parentNode.replaceChild(newTable, oldTable);
                    bindParamTableEvents();
                }
            });
    }
    
    // 绑定事件
    function bindParamTableEvents() {
        // 新增按钮
        const addBtn = document.querySelector('.add_factor_btn');
        if (addBtn) {
            addBtn.addEventListener('click', function() {
                var paramValues = {};
                paramAliases.forEach(function(alias) {
                    var el = document.getElementById('param_' + alias);
                    if (el) paramValues[alias] = el.value;
                });
                fetch('/add_params', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        factor_family_alias: factorFamilyAlias,
                        params: paramValues
                    })
                }).then(r => r.json()).then(data => {
                    if (data.success) {
                        reloadParamTable();
                    } else {
                        alert('添加失败: ' + data.error);
                    }
                });
            });
        }
        
        // 删除按钮
        document.querySelectorAll('.delete_factor_btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var idx = btn.getAttribute('data-factor-idx');
                fetch('/delete_params', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        factor_family_alias: factorFamilyAlias,
                        factor_idx: idx
                    })
                }).then(r => r.json()).then(data => {
                    if (data.success) reloadParamTable();
                    else alert('删除失败: ' + data.error);
                });
            });
        });
        
        // 拖拽排序
        var tbody = document.getElementById('factor_table_body');
        if (tbody) {
            var draggingRow = null;
            var dragStartIdx = null;
            
            tbody.querySelectorAll('tr[draggable="true"]').forEach(function(row) {
                row.addEventListener('dragstart', function(e) {
                    draggingRow = row;
                    dragStartIdx = parseInt(row.getAttribute('data-factor-idx'));
                    row.style.opacity = '0.5';
                    e.dataTransfer.effectAllowed = 'move';
                });
                row.addEventListener('dragend', function(e) {
                    row.style.opacity = '';
                    draggingRow = null;
                    dragStartIdx = null;
                });
                row.addEventListener('dragover', function(e) {
                    e.preventDefault();
                    row.style.background = '#e6f7ff';
                });
                row.addEventListener('dragleave', function(e) {
                    row.style.background = '';
                });
                row.addEventListener('drop', function(e) {
                    e.preventDefault();
                    row.style.background = '';
                    var dragOverIdx = parseInt(row.getAttribute('data-factor-idx'));
                    if (dragStartIdx !== null && dragOverIdx !== null && dragStartIdx !== dragOverIdx) {
                        fetch('/reorder_params', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({
                                factor_family_alias: factorFamilyAlias,
                                from_idx: dragStartIdx,
                                to_idx: dragOverIdx
                            })
                        }).then(r => r.json()).then(data => {
                            if (data.success) reloadParamTable();
                            else alert('排序失败: ' + data.error);
                        });
                    }
                });
            });
        }
    }
    
    bindParamTableEvents();
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    initParameterModule();
});