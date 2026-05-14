// ── 全因子概览 ──
let _scopeFactorsData = null;
let _allFactorsIncludeSubordinates = true;
let _allFactorsOrgFilter = '';
let _allFactorsUserFilter = '';

async function openAllFactorsOverlay() {
    document.getElementById('all-factors-overlay').classList.add('open');
    const body = document.getElementById('all-factors-body');
    body.innerHTML = '<p style="color:#888;">加载中...</p>';
    _allFactorsIncludeSubordinates = true;
    _allFactorsOrgFilter = '';
    _allFactorsUserFilter = '';
    await loadAllFactorsOverview();
}

async function loadAllFactorsOverview() {
    const body = document.getElementById('all-factors-body');
    try {
        const resp = await fetch('/custom-factors/api/param-factor-overview' + (_allFactorsIncludeSubordinates ? '?include_subordinates=1' : ''));
        const data = await resp.json();
        if (data.success) {
            const factors = (data.factors || []).sort(compareAllFactorsForDisplay);
            _scopeFactorsData = {
                success: true,
                factors,
                errors: data.errors || [],
                canFilterOrganization: !!data.can_filter_organization,
            };
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

    // 第一级：按 scope_key 分组
    const scopeGroups = {};
    visibleFactors.forEach(f => {
        const sk = f.scope_key || '默认';
        if (!scopeGroups[sk]) scopeGroups[sk] = [];
        scopeGroups[sk].push(f);
    });
    const scopeKeys = Object.keys(scopeGroups).sort((a, b) => {
        if (a === 'default' || a === '默认') return 1;
        if (b === 'default' || b === '默认') return -1;
        return a.localeCompare(b);
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
    html += '<div class="all-factors-stat">产品组: <strong>' + scopeKeys.length + '</strong></div>';
    html += '<div class="all-factors-stat">用户: <strong>' + ownersSeen.size + '</strong></div>';
    html += '<div class="all-factors-stat">配置: <strong>' + templatesSeen.size + '</strong></div>';
    html += '<div class="all-factors-stat">公共/自定义/未知: <strong>' + totalPublic + '/' + totalCustom + '/' + totalUnknown + '</strong></div>';
    html += '</div>';
    if (data.errors && data.errors.length) {
        html += '<div class="all-factors-warning">有 ' + data.errors.length + ' 条参数配置无法解析，已跳过。</div>';
    }
    if (!visibleFactors.length) {
        body.innerHTML = html + '<p style="color:#999;">当前所有者筛选下暂无参数配置因子</p>';
        return;
    }

    for (const sk of scopeKeys) {
        const scopeItems = scopeGroups[sk];
        // 第二级：按 group（因子家族前缀）分组
        const groups = {};
        scopeItems.forEach(f => {
            const group = getGroup(f.factor_family_alias || f.factor_family_name || f.factor_alias);
            if (!groups[group]) groups[group] = [];
            groups[group].push(f);
        });
        html += '<div class="collapsible-factor-node collapsible-factor-scope">';
        html += '<button class="collapsible-factor-header scope-header" type="button"><span class="caret">▶</span><span class="collapsible-factor-title">' +
            escHtml(sk) + '</span><span class="collapsible-factor-count">' + scopeItems.length + '</span></button><div class="collapsible-factor-body">';

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
        html += '</div></div>';
    }

    body.innerHTML = html;
    if (typeof bindCollapsibleFactorLists === 'function') bindCollapsibleFactorLists(body);
}

function renderAllFactorsControls() {
    const orgOptions = buildAllFactorOrgOptions();
    let html = '<div class="all-factors-controls">';
    html += '<label style="display:flex;align-items:center;gap:6px;font-size:13px;color:#667085;cursor:pointer;">' +
        '<input type="checkbox" onchange="toggleAllFactorsSubordinates(this.checked)" ' +
        (_allFactorsIncludeSubordinates ? 'checked' : '') + ' style="width:auto;margin:0;">包含下级用户的参数配置因子</label>';
    if (_scopeFactorsData?.canFilterOrganization) {
        html += '<label class="all-factors-owner-filter">机构 ';
        html += '<select onchange="setAllFactorsOrgFilter(this.value)">';
        html += '<option value="">全部机构</option>';
        orgOptions.forEach(opt => {
            html += '<option value="' + escAttr(opt.value) + '"' + (opt.value === _allFactorsOrgFilter ? ' selected' : '') + '>' + escHtml(opt.label) + '</option>';
        });
        html += '</select></label>';
    }
    html += '<label class="all-factors-owner-filter">用户 ';
    html += '<input id="all-factors-user-filter" type="search" value="' + escAttr(_allFactorsUserFilter) + '" placeholder="搜索用户名/别名" oninput="setAllFactorsUserFilter(this.value)">';
    html += '</label></div>';
    return html;
}

async function toggleAllFactorsSubordinates(checked) {
    _allFactorsIncludeSubordinates = !!checked;
    _allFactorsOrgFilter = '';
    _allFactorsUserFilter = '';
    document.getElementById('all-factors-body').innerHTML = renderAllFactorsControls() + '<p style="color:#888;">加载中...</p>';
    await loadAllFactorsOverview();
}

function setAllFactorsOrgFilter(value) {
    _allFactorsOrgFilter = value || '';
    renderScopeFactorsOverview();
}

function setAllFactorsUserFilter(value) {
    _allFactorsUserFilter = value || '';
    renderScopeFactorsOverview();
    setTimeout(() => {
        const input = document.getElementById('all-factors-user-filter');
        if (!input) return;
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
    }, 0);
}

function buildAllFactorOrgOptions() {
    const factors = (_scopeFactorsData && _scopeFactorsData.factors) || [];
    const orgs = new Map();
    factors.forEach(f => {
        const key = f.owner_organization_id || '';
        if (!key || orgs.has(key)) return;
        orgs.set(key, {
            value: key,
            label: f.owner_organization_name || key,
        });
    });
    return [...orgs.values()].sort((a, b) => a.label.localeCompare(b.label));
}

function filterAllFactorsByOwner(factors) {
    const userFilter = _allFactorsUserFilter.trim().toLowerCase();
    return factors.filter(f => {
        if (_allFactorsOrgFilter && (f.owner_organization_id || '') !== _allFactorsOrgFilter) return false;
        if (!userFilter) return true;
        const haystack = `${f.owner_username || ''} ${f.owner_alias || ''}`.toLowerCase();
        return haystack.includes(userFilter);
    });
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

// ── 通用因子选择表格（scope 分组 + 搜索过滤 + 选择按钮）──
// 供 factor_param_picker.js 和所有需要"从因子库选择因子"的场景复用

/**
 * 在 containerEl 内渲染带 scope 分组的因子选择表格
 * @param {Array} items - param-factor-overview 返回的 factor items
 * @param {HTMLElement} containerEl - 渲染目标容器
 * @param {Object} opts
 * @param {string}  opts.searchQuery - 当前搜索词（空字符串 = 不过滤）
 * @param {string}  opts.emptyMessage - 空结果提示，默认 "暂无可选因子"
 * @param {string}  opts.pickAttribute - 选择按钮的 data-* 属性名，默认 "shared-factor-param-pick"
 * @param {string}  opts.pickValue - 选择按钮的值取 item 的哪个字段，默认 "factor_alias"
 * @param {string}  opts.pickLabel - 选择按钮文字，默认 "选择"
 * @param {Function} opts.onRender - 渲染完成后回调，用于绑定事件
 */
function renderFactorPickerTable(items, containerEl, opts) {
    opts = opts || {};
    const searchQuery = (opts.searchQuery || '').trim().toLowerCase();
    const pickAttr = opts.pickAttribute || 'shared-factor-param-pick';
    const pickValueField = opts.pickValue || 'factor_alias';
    const pickLabel = opts.pickLabel || '选择';

    const visible = items.filter(function(item) {
        if (!searchQuery) return true;
        return [item.factor_alias, item.factor_family_alias, item.factor_family_name,
            item.chinese_name, item.owner_alias, item.owner_username, item.scope_key, item.category]
            .join(' ').toLowerCase().indexOf(searchQuery) !== -1;
    });

    if (!visible.length) {
        containerEl.innerHTML = '<div style="color:#888;text-align:center;padding:28px;">' +
            escHtml(opts.emptyMessage || '暂无可选因子。请先在因子库保存参数配置。') + '</div>';
        return;
    }

    // 按 scope_key 分组
    var scopes = {};
    visible.forEach(function(item) {
        var sk = item.scope_key || '默认';
        if (!scopes[sk]) scopes[sk] = [];
        scopes[sk].push(item);
    });
    var scopeKeys = Object.keys(scopes).sort(function(a, b) {
        if (a === 'default' || a === '默认') return 1;
        if (b === 'default' || b === '默认') return -1;
        return a.localeCompare(b);
    });

    var hasSearch = searchQuery.length > 0;
    var html = '';
    scopeKeys.forEach(function(sk, si) {
        var groupItems = scopes[sk];
        var expanded = hasSearch || (si === 0 && scopeKeys.length === 1);
        var caretClass = expanded ? 'caret-open' : 'caret-closed';
        var bodyStyle = expanded ? '' : 'display:none;';
        html += '<div class="picker-scope-node">';
        html += '<div class="picker-scope-header" data-scope-toggle="' + escHtml(sk) + '" style="display:flex;align-items:center;gap:8px;padding:8px 0;cursor:pointer;border-bottom:1px solid #f0f0f0;">';
        html += '<span class="picker-caret ' + caretClass + '" data-scope="' + escHtml(sk) + '"></span>';
        html += '<strong style="font-size:14px;color:#1e293b;">' + escHtml(sk) + '</strong>';
        html += '<span style="color:#888;font-size:12px;">(' + groupItems.length + ')</span>';
        html += '</div>';
        html += '<div class="picker-scope-body" data-scope-body="' + escHtml(sk) + '" style="' + bodyStyle + '">';
        html += '<table class="param-table" style="width:100%;"><thead><tr>';
        html += '<th>因子</th><th>家族</th><th>类别</th><th>参数</th><th>所有者</th><th>操作</th>';
        html += '</tr></thead><tbody>';
        groupItems.forEach(function(item) {
            var params = (item.params || []).map(function(p) {
                return '<span style="display:inline-block;margin:1px 4px 1px 0;color:#667085;">' +
                    escHtml(p.alias) + ':' + escHtml(p.value) + '</span>';
            }).join('');
            var pickVal = escAttr(item[pickValueField] || '');
            html += '<tr>';
            html += '<td><strong>' + escHtml(item.factor_alias) + '</strong></td>';
            html += '<td>' + escHtml(item.factor_family_alias || item.factor_family_name || '') +
                '<div style="color:#888;font-size:12px;">' + escHtml(item.chinese_name || '') + '</div></td>';
            html += '<td style="color:#667085;font-size:12px;">' + escHtml(item.category || '') + '</td>';
            html += '<td>' + (params || '<span style="color:#aaa;">无</span>') + '</td>';
            html += '<td>' + escHtml(item.owner_alias || item.owner_username || '') + '</td>';
            html += '<td><button type="button" class="param-btn" data-' + pickAttr + '="' + pickVal + '">' +
                escHtml(pickLabel) + '</button></td>';
            html += '</tr>';
        });
        html += '</tbody></table></div></div>';
    });
    containerEl.innerHTML = html;

    // 绑定折叠事件
    containerEl.querySelectorAll('[data-scope-toggle]').forEach(function(header) {
        header.addEventListener('click', function() {
            var sk = this.dataset.scopeToggle;
            var caret = containerEl.querySelector('.picker-caret[data-scope="' + sk.replace(/"/g, '\\"') + '"]');
            var scopeBody = containerEl.querySelector('[data-scope-body="' + sk.replace(/"/g, '\\"') + '"]');
            if (!scopeBody) return;
            var isOpen = scopeBody.style.display !== 'none';
            if (isOpen) {
                scopeBody.style.display = 'none';
                if (caret) { caret.classList.remove('caret-open'); caret.classList.add('caret-closed'); }
            } else {
                scopeBody.style.display = '';
                if (caret) { caret.classList.remove('caret-closed'); caret.classList.add('caret-open'); }
            }
        });
    });

    if (typeof opts.onRender === 'function') opts.onRender();
}

window.renderFactorPickerTable = renderFactorPickerTable;
