// ── 全因子概览（按 scope 统一模板的因子列表） ──
let _scopeFactorsData = null;
let _currentScopeKey = '';

async function openAllFactorsOverlay() {
    document.getElementById('all-factors-overlay').classList.add('open');
    const body = document.getElementById('all-factors-body');
    body.innerHTML = '<p style="color:#888;">加载中...</p>';

    // 获取当前用户名作为 scope_key
    let scopeKey = _currentScopeKey;
    if (!scopeKey) {
        try {
            const meResp = await fetch('/api/me');
            const meData = await meResp.json();
            scopeKey = meData.username || '';
            _currentScopeKey = scopeKey;
        } catch(e) {
            scopeKey = '';
        }
    }

    if (!scopeKey) {
        body.innerHTML = '<p style="color:#999;">无法获取当前用户信息</p>';
        return;
    }

    try {
        const resp = await fetch('/api/global_templates/' + encodeURIComponent(scopeKey) + '/factors');
        const data = await resp.json();
        if (data.success) {
            _scopeFactorsData = data;
            renderScopeFactorsOverview();
        } else {
            body.innerHTML = '<p style="color:#999;">加载失败: ' + (data.error || '未知错误') + '</p>';
        }
    } catch(e) {
        body.innerHTML = '<p style="color:#999;">网络错误: ' + e.message + '</p>';
    }
}

function closeAllFactorsOverlay() {
    document.getElementById('all-factors-overlay').classList.remove('open');
}

function renderScopeFactorsOverview() {
    const body = document.getElementById('all-factors-body');
    const data = _scopeFactorsData;
    if (!data || !data.groups || !data.groups.length) {
        body.innerHTML = '<p style="color:#999;">该 scope 下暂无已配置的因子</p>';
        return;
    }

    const groups = data.groups;
    let totalPublic = 0, totalCustom = 0, totalUnknown = 0;
    groups.forEach(g => {
        g.factors.forEach(f => {
            if (f.source === 'public') totalPublic++;
            else if (f.source === 'custom') totalCustom++;
            else totalUnknown++;
        });
    });

    let html = '<div class="all-factors-stats">';
    html += '<div class="all-factors-stat">总计: <strong>' + data.total_factors + '</strong> 个因子</div>';
    html += '<div class="all-factors-stat">公共: <strong>' + totalPublic + '</strong></div>';
    html += '<div class="all-factors-stat">自定义: <strong>' + totalCustom + '</strong></div>';
    html += '<div class="all-factors-stat">家族: <strong>' + groups.length + '</strong></div>';
    html += '</div>';

    html += '<table class="all-factors-table">';
    html += '<thead><tr>';
    html += '<th>因子名</th><th>中文名</th><th>类别</th><th>参数数量</th><th>来源</th><th>更新时间</th>';
    html += '</tr></thead><tbody>';

    for (const g of groups) {
        const items = g.factors;
        html += '<tr class="all-factors-family-group"><td colspan="6">📁 ' + escHtml(g.family) + ' (' + items.length + ')</td></tr>';
        for (const f of items) {
            html += '<tr>';
            html += '<td><strong>' + escHtml(f.name || f.id) + '</strong></td>';
            html += '<td>' + escHtml(f.chinese_name || '—') + '</td>';
            html += '<td>' + escHtml(f.category || '—') + '</td>';
            html += '<td>' + (f.params_count || 0) + '</td>';
            const sourceLabel = f.source === 'public' ? '公共' : (f.source === 'custom' ? '自定义' : '未知');
            const sourceClass = f.source === 'public' ? 'tag-public' : (f.source === 'custom' ? 'tag-custom' : 'tag-unknown');
            html += '<td><span class="tag ' + sourceClass + '">' + sourceLabel + '</span></td>';
            html += '<td style="color:#888;font-size:12px;">' + escHtml(f.updated_at || '—') + '</td>';
            html += '</tr>';
        }
    }

    html += '</tbody></table>';
    body.innerHTML = html;
}
