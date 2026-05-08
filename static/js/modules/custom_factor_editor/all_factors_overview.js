// ── 全因子概览 ──
let _scopeFactorsData = null;
let _allFactorsIncludeSubordinates = true;
let _allFactorsOwnerFilter = '';

async function openAllFactorsOverlay() {
    document.getElementById('all-factors-overlay').classList.add('open');
    const body = document.getElementById('all-factors-body');
    body.innerHTML = '<p style="color:#888;">加载中...</p>';
    _allFactorsIncludeSubordinates = true;
    _allFactorsOwnerFilter = '';
    await loadAllFactorsOverview();
}

async function loadAllFactorsOverview() {
    const body = document.getElementById('all-factors-body');
    try {
        const resp = await fetch('/custom-factors/api/param-factor-overview' + (_allFactorsIncludeSubordinates ? '?include_subordinates=1' : ''));
        const data = await resp.json();
        if (data.success) {
            const factors = (data.factors || []).sort(compareAllFactorsForDisplay);
            _scopeFactorsData = {success: true, factors, errors: data.errors || []};
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
        body.innerHTML = renderAllFactorsControls() + '<p style="color:#999;">暂无参数配置因子</p>';
        return;
    }

    const visibleFactors = filterAllFactorsByOwner(data.factors);
    const groups = {};
    visibleFactors.forEach(f => {
        const group = getGroup(f.factor_family_alias || f.factor_family_name || f.factor_alias);
        if (!groups[group]) groups[group] = [];
        groups[group].push(f);
    });
    let totalPublic = 0, totalCustom = 0, totalUnknown = 0;
    const ownersSeen = new Set();
    const templatesSeen = new Set();
    visibleFactors.forEach(f => {
        if (f.source === 'public') totalPublic++;
        else if (f.source === 'custom') totalCustom++;
        else totalUnknown++;
        ownersSeen.add(f.owner_username || '');
        templatesSeen.add((f.owner_username || '') + ':' + (f.factor_family_alias || '') + ':' + (f.template_id || ''));
    });

    let html = renderAllFactorsControls();
    html += '<div class="all-factors-stats">';
    html += '<div class="all-factors-stat">显示: <strong>' + visibleFactors.length + '</strong> / ' + data.factors.length + ' 个参数配置因子</div>';
    html += '<div class="all-factors-stat">用户: <strong>' + ownersSeen.size + '</strong></div>';
    html += '<div class="all-factors-stat">配置: <strong>' + templatesSeen.size + '</strong></div>';
    html += '<div class="all-factors-stat">因子家族: <strong>' + Object.keys(groups).length + '</strong></div>';
    html += '<div class="all-factors-stat">公共/自定义/未知: <strong>' + totalPublic + '/' + totalCustom + '/' + totalUnknown + '</strong></div>';
    html += '</div>';
    if (data.errors && data.errors.length) {
        html += '<div class="all-factors-warning">有 ' + data.errors.length + ' 条参数配置无法解析，已跳过。</div>';
    }
    if (!visibleFactors.length) {
        body.innerHTML = html + '<p style="color:#999;">当前所有者筛选下暂无参数配置因子</p>';
        return;
    }

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
            html += '<th>因子</th><th>因子家族</th><th>参数配置</th><th>参数</th><th>所有者</th><th>来源</th><th>更新时间</th>';
            html += '</tr></thead><tbody>';
            for (const f of ownerItems) {
                html += '<tr>';
                html += '<td><strong class="all-factors-alias">' + escHtml(f.factor_alias || '—') + '</strong></td>';
                html += '<td><div>' + escHtml(f.factor_family_alias || f.factor_family_name || '—') + '</div><div class="all-factors-subtext">' + escHtml(f.chinese_name || f.category || '') + '</div></td>';
                html += '<td><div>' + escHtml(f.template_name || '—') + '</div><div class="all-factors-subtext">第 ' + (Number(f.template_row_index || 0) + 1) + ' 行</div></td>';
                html += '<td>' + renderParamsSummary(f.params || []) + '</td>';
                html += '<td>' + escHtml(getAllFactorOwnerLabel(f)) + '</td>';
                const sourceLabel = getAllFactorOwnerLabel(f);
                const sourceClass = f.source === 'public' ? 'tag-public' : (f.source === 'custom' ? 'tag-custom' : 'tag-unknown');
                html += '<td><span class="tag ' + sourceClass + '">' + escHtml(f.source_label || sourceLabel) + '</span></td>';
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
    const ownerOptions = buildAllFactorOwnerOptions();
    let html = '<div class="all-factors-controls">';
    html += '<label style="display:flex;align-items:center;gap:6px;font-size:13px;color:#667085;cursor:pointer;">' +
        '<input type="checkbox" onchange="toggleAllFactorsSubordinates(this.checked)" ' +
        (_allFactorsIncludeSubordinates ? 'checked' : '') + ' style="width:auto;margin:0;">包含下级用户的参数配置因子</label>';
    html += '<label class="all-factors-owner-filter">所有者 ';
    html += '<select onchange="setAllFactorsOwnerFilter(this.value)">';
    html += '<option value="">全部所有者</option>';
    ownerOptions.forEach(opt => {
        html += '<option value="' + escAttr(opt.value) + '"' + (opt.value === _allFactorsOwnerFilter ? ' selected' : '') + '>' + escHtml(opt.label) + '</option>';
    });
    html += '</select></label></div>';
    return html;
}

async function toggleAllFactorsSubordinates(checked) {
    _allFactorsIncludeSubordinates = !!checked;
    _allFactorsOwnerFilter = '';
    document.getElementById('all-factors-body').innerHTML = renderAllFactorsControls() + '<p style="color:#888;">加载中...</p>';
    await loadAllFactorsOverview();
}

function setAllFactorsOwnerFilter(value) {
    _allFactorsOwnerFilter = value || '';
    renderScopeFactorsOverview();
}

function buildAllFactorOwnerOptions() {
    const factors = (_scopeFactorsData && _scopeFactorsData.factors) || [];
    const owners = new Map();
    factors.forEach(f => {
        const key = f.owner_username || '';
        if (!key || owners.has(key)) return;
        owners.set(key, {
            value: key,
            label: getAllFactorOwnerLabel(f),
        });
    });
    return [...owners.values()].sort((a, b) => a.label.localeCompare(b.label));
}

function filterAllFactorsByOwner(factors) {
    if (!_allFactorsOwnerFilter) return factors;
    return factors.filter(f => (f.owner_username || '') === _allFactorsOwnerFilter);
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
    return `${f.owner_organization_name || f.owner_organization_id || '未分机构'}/${f.owner_alias || f.owner_username || '未知用户'}`;
}

function getAllFactorOwnerLabel(f) {
    if (f.can_edit) return '我的配置';
    return `${f.owner_organization_name || f.owner_organization_id || '未分机构'} / ${f.owner_alias || f.owner_username || '未知用户'}`;
}

function renderParamsSummary(params) {
    if (!params.length) return '<span class="all-factors-subtext">无参数</span>';
    return params.map(p => '<span class="all-factors-param">' + escHtml(p.alias) + ':' + escHtml(p.value) + '</span>').join(' ');
}

function compareAllFactorsForDisplay(a, b) {
    return (
        getGroup(a.factor_family_alias || a.factor_family_name || a.factor_alias).localeCompare(getGroup(b.factor_family_alias || b.factor_family_name || b.factor_alias)) ||
        getAllFactorOwnerSortKey(a).localeCompare(getAllFactorOwnerSortKey(b)) ||
        (a.factor_family_alias || '').localeCompare(b.factor_family_alias || '') ||
        (a.factor_alias || '').localeCompare(b.factor_alias || '')
    );
}
