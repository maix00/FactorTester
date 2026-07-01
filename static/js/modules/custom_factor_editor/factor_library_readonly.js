(function() {
    var factors = [];
    var selectedKey = null;

    function status(message, error) {
        var node = document.getElementById('workspace-status');
        node.textContent = message;
        node.style.color = error ? '#b42318' : '#66736b';
    }

    async function json(url, options) {
        var response = await fetch(url, options);
        var payload = await response.json();
        if (!response.ok || payload.success === false) throw new Error(payload.error || ('HTTP ' + response.status));
        return payload;
    }

    async function loadWorkspace() {
        try {
            var payload = await json('/custom-factors/api/source-root');
            document.getElementById('factor-source-root-input').value = payload.source_root || '';
            status(payload.resolved_root ? ('当前目录：' + payload.resolved_root) : '使用默认用户目录');
        } catch (error) { status(error.message, true); }
    }

    async function workspaceAction(action) {
        var routes = {
            'build': ['/custom-factors/api/workspace/build', {}],
            'sync': ['/custom-factors/api/workspace/sync', { branch_mode: 'force' }],
            'push': ['/custom-factors/api/workspace/push', { branch_mode: 'auto' }],
        };
        try {
            status('正在执行...');
            if (action === 'save-root') {
                await json('/custom-factors/api/source-root', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({source_root: document.getElementById('factor-source-root-input').value.trim()}),
                });
            } else {
                var route = routes[action];
                await json(route[0], {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(route[1])});
            }
            status('操作完成');
            await loadWorkspace();
            await loadFactors();
        } catch (error) { status(error.message, true); }
    }

    async function loadFactors() {
        var include = document.getElementById('include-subordinates').checked ? '?include_subordinates=1' : '';
        try {
            var payload = await json('/custom-factors/api/list' + include);
            factors = (payload.custom_factors || []).map(function(item) { return Object.assign({type: 'custom'}, item); })
                .concat((payload.public_factors || []).map(function(item) { return Object.assign({type: 'public'}, item); }));
            renderList();
        } catch (error) {
            document.getElementById('factor-list').innerHTML = '<div class="empty">加载失败</div>';
        }
    }

    function renderList() {
        var query = document.getElementById('factor-filter').value.trim().toLowerCase();
        var list = document.getElementById('factor-list');
        list.innerHTML = '';
        factors.filter(function(item) {
            return !query || [item.name, item.chinese_name, item.category, item.owner_alias, item.owner_username].join(' ').toLowerCase().indexOf(query) >= 0;
        }).forEach(function(item) {
            var key = item.type + ':' + (item.owner_username || '') + ':' + item.id;
            var button = document.createElement('button');
            button.className = 'factor-item' + (key === selectedKey ? ' active' : '');
            var name = document.createElement('span');
            name.className = 'factor-name';
            name.textContent = item.chinese_name ? (item.chinese_name + ' · ' + item.name) : item.name;
            var subtitle = document.createElement('span');
            subtitle.className = 'factor-subtitle';
            subtitle.textContent = [item.category || '未分类', item.owner_alias || item.owner_username || (item.type === 'public' ? '公共' : '我')].join(' / ');
            button.appendChild(name); button.appendChild(subtitle);
            button.addEventListener('click', function() { viewFactor(item, key); });
            list.appendChild(button);
        });
        if (!list.childNodes.length) list.innerHTML = '<div class="empty">没有匹配的因子</div>';
    }

    async function viewFactor(item, key) {
        selectedKey = key; renderList();
        try {
            var url = item.type === 'public'
                ? '/custom-factors/api/public-factor/' + encodeURIComponent(item.name || item.id)
                : '/custom-factors/api/get/' + encodeURIComponent(item.id) + '?owner_username=' + encodeURIComponent(item.owner_username || '');
            var detail = (await json(url)).factor;
            document.getElementById('factor-title').textContent = detail.chinese_name ? (detail.chinese_name + ' · ' + detail.name) : detail.name;
            document.getElementById('factor-category').textContent = detail.category || '未分类';
            document.getElementById('factor-meta').textContent = detail.description || '暂无说明';
            document.getElementById('source-empty').hidden = true;
            document.getElementById('source-view').hidden = false;
            var code = document.getElementById('source-code');
            code.textContent = detail.source_code || '';
            code.removeAttribute('data-highlighted');
            if (window.hljs) window.hljs.highlightElement(code);
        } catch (error) { status(error.message, true); }
    }

    document.querySelectorAll('[data-workspace-action]').forEach(function(button) {
        button.addEventListener('click', function() { workspaceAction(button.getAttribute('data-workspace-action')); });
    });
    document.getElementById('factor-filter').addEventListener('input', renderList);
    document.getElementById('include-subordinates').addEventListener('change', loadFactors);
    loadWorkspace(); loadFactors();
})();
