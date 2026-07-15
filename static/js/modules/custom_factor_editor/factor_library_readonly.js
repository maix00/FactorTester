(function() {
    var factors = [];
    var selectedKey = null;
    var selectedFactor = null;

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
        selectedKey = key; selectedFactor = item; renderList();
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
            loadResearchResults(detail);
        } catch (error) { status(error.message, true); }
    }

    function escapeHTML(value) {
        return String(value == null ? '' : value).replace(/[&<>"']/g, function(ch) {
            return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]);
        });
    }

    function factorFamilyName(detail) {
        return String((detail && (detail.name || detail.factor_family || detail.id)) || (selectedFactor && (selectedFactor.name || selectedFactor.id)) || '');
    }

    async function loadResearchResults(detail) {
        var panel = document.getElementById('research-panel');
        var statusEl = document.getElementById('research-status');
        var resultsEl = document.getElementById('research-results');
        var family = factorFamilyName(detail);
        if (!family) return;
        panel.hidden = false;
        statusEl.textContent = '正在加载研究结果...';
        resultsEl.innerHTML = '';
        var params = new URLSearchParams();
        params.set('factor_family_alias', family);
        params.set('factor_family', family);
        params.set('limit', '30');
        var start = document.getElementById('research-start-date').value;
        var end = document.getElementById('research-end-date').value;
        var metric = document.getElementById('research-metric').value.trim();
        if (start) params.set('start_date', start);
        if (end) params.set('end_date', end);
        if (metric) params.set('metric', metric);
        try {
            var payload = await json('/custom-factors/api/factor-library-research-runs?' + params.toString());
            var runs = payload.runs || [];
            statusEl.textContent = runs.length ? ('共 ' + runs.length + ' 条结果') : '暂无研究结果';
            renderResearchRuns(runs, metric);
        } catch (error) {
            statusEl.textContent = error.message;
            resultsEl.innerHTML = '';
        }
    }

    function renderResearchRuns(runs, metric) {
        var resultsEl = document.getElementById('research-results');
        if (!runs.length) {
            resultsEl.innerHTML = '<div class="empty">暂无匹配研究结果</div>';
            return;
        }
        var rows = runs.map(function(run) {
            var metrics = run.metrics || {};
            var displayMetric = metric || defaultResearchMetric(run, metrics);
            return '<tr>'
                + '<td>' + escapeHTML(run.factor_alias || '') + '</td>'
                + '<td>' + escapeHTML(run.test_type || '') + '</td>'
                + '<td>' + escapeHTML(run.product_group || '') + '</td>'
                + '<td>' + escapeHTML((run.start_date || '') + '..' + (run.end_date || '')) + '</td>'
                + '<td>' + escapeHTML(formatMetric(metrics[displayMetric])) + '</td>'
                + '<td>' + escapeHTML(run.report_path || run.artifact_path || '') + '</td>'
                + '</tr>';
        }).join('');
        resultsEl.innerHTML = '<table class="research-table"><thead><tr>'
            + '<th>因子</th><th>类型</th><th>产品组</th><th>时间段</th><th>指标</th><th>报告</th>'
            + '</tr></thead><tbody>' + rows + '</tbody></table>';
    }

    function defaultResearchMetric(run, metrics) {
        if ((run.test_type || '') === 'ic') return 'ic_mean';
        if ((run.test_type || '') === 'factor_type') return metrics.best_type_score != null ? 'best_type_score' : 'best_type';
        if ((run.test_type || '') === 'factor_evaluation') return metrics.product_count != null ? 'product_count' : 'series_count';
        if ((run.test_type || '') === 'bucket_label') return metrics.a1_a5_label_return_spread != null ? 'a1_a5_label_return_spread' : 'ic_mean';
        return metrics.ls_return != null ? 'ls_return' : 'a1_return';
    }

    function formatMetric(value) {
        if (value == null || value === '') return '';
        var num = Number(value);
        if (Number.isFinite(num)) return Math.abs(num) >= 100 ? num.toFixed(1) : num.toPrecision(4);
        return String(value);
    }

    document.querySelectorAll('[data-workspace-action]').forEach(function(button) {
        button.addEventListener('click', function() { workspaceAction(button.getAttribute('data-workspace-action')); });
    });
    document.getElementById('factor-filter').addEventListener('input', renderList);
    document.getElementById('include-subordinates').addEventListener('change', loadFactors);
    document.getElementById('research-refresh').addEventListener('click', function() { loadResearchResults(selectedFactor); });
    loadWorkspace(); loadFactors();
})();
