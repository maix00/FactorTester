// ── 全因子概览 ──
let _scopeFactorsData = null;
let _allFactorsIncludeSubordinates = false;

async function openAllFactorsOverlay() {
    document.getElementById('all-factors-overlay').classList.add('open');
    const body = document.getElementById('all-factors-body');
    body.innerHTML = '<p style="color:#888;">加载中...</p>';
    _allFactorsIncludeSubordinates = false;
    await loadAllFactorsOverview();
}

async function loadAllFactorsOverview() {
    const body = document.getElementById('all-factors-body');
    try {
        const resp = await fetch('/custom-factors/api/list' + (_allFactorsIncludeSubordinates ? '?include_subordinates=1' : ''));
        const data = await resp.json();
        if (data.success) {
            const factors = [
                ...(data.public_factors || []).map(f => ({...f, type: 'public', source: 'public'})),
                ...(data.custom_factors || []).map(f => ({...f, type: 'custom', source: 'custom'})),
            ].sort(compareAllFactorsForDisplay);
            _scopeFactorsData = {success: true, factors};
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
    if (!data || !data.factors || !data.factors.length) {
        body.innerHTML = renderAllFactorsControls() + '<p style="color:#999;">暂无因子</p>';
        return;
    }

    const groups = {};
    data.factors.forEach(f => {
        const group = getGroup(f.name || f.id);
        if (!groups[group]) groups[group] = [];
        groups[group].push(f);
    });
    let totalPublic = 0, totalCustom = 0, totalUnknown = 0;
    data.factors.forEach(f => {
        if (f.source === 'public') totalPublic++;
        else if (f.source === 'custom') totalCustom++;
        else totalUnknown++;
    });

    let html = renderAllFactorsControls();
    html += '<div class="all-factors-stats">';
    html += '<div class="all-factors-stat">总计: <strong>' + data.factors.length + '</strong> 个因子</div>';
    html += '<div class="all-factors-stat">公共: <strong>' + totalPublic + '</strong></div>';
    html += '<div class="all-factors-stat">自定义: <strong>' + totalCustom + '</strong></div>';
    html += '<div class="all-factors-stat">家族: <strong>' + Object.keys(groups).length + '</strong></div>';
    html += '</div>';

    for (const group of Object.keys(groups).sort()) {
        const items = groups[group].sort(compareAllFactorsForDisplay);
        const owners = {};
        items.forEach(f => {
            const ownerKey = getAllFactorOwnerSortKey(f);
            if (!owners[ownerKey]) owners[ownerKey] = [];
            owners[ownerKey].push(f);
        });
        html += '<div class="collapsible-factor-node collapsible-factor-group">';
        html += '<button class="collapsible-factor-header" type="button"><span class="caret">▶</span><span class="collapsible-factor-title">' +
            escHtml(group) + '</span><span class="collapsible-factor-count">' + items.length + '</span></button><div class="collapsible-factor-body">';
        for (const ownerKey of Object.keys(owners).sort()) {
            const ownerItems = owners[ownerKey];
            html += '<div class="collapsible-factor-node collapsible-factor-owner">';
            html += '<button class="collapsible-factor-header" type="button"><span class="caret">▶</span><span class="collapsible-factor-title">' +
                escHtml(getAllFactorOwnerLabel(ownerItems[0])) + '</span><span class="collapsible-factor-count">' + ownerItems.length + '</span></button><div class="collapsible-factor-body">';
            html += '<table class="all-factors-table"><thead><tr>';
            html += '<th>因子名</th><th>中文名</th><th>类别</th><th>参数数量</th><th>来源</th><th>更新时间</th>';
            html += '</tr></thead><tbody>';
            for (const f of ownerItems) {
                html += '<tr>';
                html += '<td><strong>' + escHtml(f.name || f.id) + '</strong></td>';
                html += '<td>' + escHtml(f.chinese_name || '—') + '</td>';
                html += '<td>' + escHtml(f.category || '—') + '</td>';
                html += '<td>' + ((f.params && f.params.length) || f.params_count || 0) + '</td>';
                const sourceLabel = getAllFactorOwnerLabel(f);
                const sourceClass = f.source === 'public' ? 'tag-public' : (f.source === 'custom' ? 'tag-custom' : 'tag-unknown');
                html += '<td><span class="tag ' + sourceClass + '">' + escHtml(sourceLabel) + '</span></td>';
                html += '<td style="color:#888;font-size:12px;">' + escHtml(f.updated_at || '—') + '</td>';
                html += '</tr>';
            }
            html += '</tbody></table></div></div>';
        }
        html += '</div></div>';
    }

    body.innerHTML = html;
    if (typeof bindCollapsibleFactorLists === 'function') bindCollapsibleFactorLists(body);
}

function renderAllFactorsControls() {
    return '<label style="display:flex;align-items:center;gap:6px;margin-bottom:12px;font-size:13px;color:#667085;cursor:pointer;">' +
        '<input type="checkbox" onchange="toggleAllFactorsSubordinates(this.checked)" ' +
        (_allFactorsIncludeSubordinates ? 'checked' : '') + ' style="width:auto;margin:0;">查看下级用户因子</label>';
}

async function toggleAllFactorsSubordinates(checked) {
    _allFactorsIncludeSubordinates = !!checked;
    document.getElementById('all-factors-body').innerHTML = renderAllFactorsControls() + '<p style="color:#888;">加载中...</p>';
    await loadAllFactorsOverview();
}

function getGroup(name) {
    let group = '';
    let upperCount = 0;
    for (const c of String(name || '')) {
        if (c === c.toUpperCase() && c !== c.toLowerCase()) {
            upperCount++;
            if (upperCount === 1) group += c;
            else if (upperCount === 2) break;
            else group += c;
        } else if (upperCount === 1) {
            group += c;
        }
    }
    return group || name || '';
}

function getAllFactorOwnerSortKey(f) {
    if (f.source === 'public') return '公共';
    return `${f.owner_organization_name || f.owner_organization_id || '未分机构'}/${f.owner_alias || f.owner_username || '未知用户'}`;
}

function getAllFactorOwnerLabel(f) {
    if (f.source === 'public') return '公共';
    if (f.can_edit) return '我的因子';
    return `${f.owner_organization_name || f.owner_organization_id || '未分机构'} / ${f.owner_alias || f.owner_username || '未知用户'}`;
}

function compareAllFactorsForDisplay(a, b) {
    return (
        getGroup(a.name || a.id).localeCompare(getGroup(b.name || b.id)) ||
        getAllFactorOwnerSortKey(a).localeCompare(getAllFactorOwnerSortKey(b)) ||
        (a.name || a.id || '').localeCompare(b.name || b.id || '')
    );
}
