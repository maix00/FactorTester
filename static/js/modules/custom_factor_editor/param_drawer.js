// ═══════════════════════════════════════════════════════════
// 参数配置右侧抽屉 (照抄 parameter_module.html 的交互模式)
// ═══════════════════════════════════════════════════════════

let _paramFamilyAlias = '';              // 当前选中的因子家族名/ID
let _paramFamilyDef = null;              // 因子家族定义（含 params 数组）
let _paramAliases = [];              // 参数别名列表（列头）
let _paramRows = [];                 // 参数行数据 [{alias: value}, ...]
let _paramTemplates = [];             // 当前因子家族可见的参数配置（自己 + 下级只读）
let _paramConfigUsers = [];           // 因子库参数配置按用户索引返回
let _paramTemplateCanFilterOrganization = false;
let _selectedParamConfig = null;

// 打开因子家族参数抽屉
function openFactorFamilyParamDrawer(factorFamilyName) {
    const drawer = document.getElementById('param-drawer');
    const def = getFactorFamilyDef(factorFamilyName);
    if (!def) {
        showToast('未找到因子家族定义: ' + factorFamilyName, 'error');
        return;
    }
    _paramFamilyAlias = factorFamilyName;
    _paramFamilyDef = def;
    _selectedParamConfig = null;
    _paramAliases = (def.params && def.params.length)
        ? def.params.map(p => p.alias)
        : [];
    // 初始加载已有参数行；默认值只放在顶部新增行里，和单因子测试抽屉一致。
    if (def.existing_params && def.existing_params.length) {
        _paramRows = def.existing_params.map(obj => {
            const row = {};
            _paramAliases.forEach(a => { row[a] = obj[a] !== undefined ? String(obj[a]) : ''; });
            return row;
        });
    } else {
        _paramRows = [];
    }

    // 更新抽屉信息
    document.getElementById('param-drawer-title').textContent = '参数配置 — ' + factorFamilyName;
    document.getElementById('param-drawer-summary-text').textContent = _paramRows.length + ' 行参数';
    renderParamTable();
    const ownerFilter = document.getElementById('param-tpl-owner-filter');
    if (ownerFilter) {
        ownerFilter.value = '';
        ownerFilter.oninput = filterParamTemplatesByOwner;
    }
    const orgFilter = document.getElementById('param-tpl-org-filter');
    if (orgFilter) {
        orgFilter.value = '';
        orgFilter.onchange = filterParamTemplatesByOwner;
    }
    loadParamTemplatesIntoSelect(); // 加载该因子家族的模板列表

    // 数学公式 + 因子说明（共享 util）
    const mathBlock = document.getElementById('cfe-math-block');
    const descBlock = document.getElementById('cfe-desc-block');
    const descRendered = document.getElementById('cfe-desc-rendered');
    if (descBlock) document.getElementById('cfe-desc-content').style.display = 'none';
    renderDrawerMathAndDesc(def.math_expr, def.description, mathBlock, descBlock, descRendered);

    drawer.classList.add('open');
}

const openParamDrawer = openFactorFamilyParamDrawer;

function closeParamDrawer() {
    const drawer = document.getElementById('param-drawer');
    drawer.classList.remove('open');
}

function escAttr(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function getFactorFamilyDef(factorFamilyName) {
    if (!getFactorFamilies()) return null;
    if (_currentFactorFamilySource === 'public') {
        return getFactorFamilies().find(f => f.id === factorFamilyName && f.type === 'public') || null;
    }
    let pf = getFactorFamilies().find(f =>
            f.name === factorFamilyName
            && f.type === (_currentFactorFamilySource || 'custom')
            && ((f.owner_username || '') === (_currentFactorFamilyOwner || ''))
    );
    if (!pf) {
        pf = getFactorFamilies().find(f => f.id === factorFamilyName && f.type === 'custom');
    }
    return pf || null;
}

function getDefaultParamRow() {
    const def = _paramFamilyDef;
    const row = {};
    _paramAliases.forEach(alias => {
        if (def && def.params) {
            const pd = def.params.find(p => p.alias === alias);
            row[alias] = pd ? getParamDefaultValue(pd) : '';
        } else {
            row[alias] = '';
        }
    });
    return row;
}

// ── 渲染参数表格到抽屉 ──
function renderParamTable() {
    if (!window.ClientParamTable) return;
    ClientParamTable.render({
        theadId: 'param-table-head',
        tbodyId: 'param-table-body',
        familyAlias: _paramFamilyAlias,
        params: _paramFamilyDef?.params || [],
        rows: _paramRows,
        callbacks: {
            add: addParamRow,
            delete: deleteParamRow,
            reorder: reorderParamRows,
        },
    });
    document.getElementById('param-drawer-summary-text').textContent = _paramRows.length + ' 行参数';
}

function updateParamCell(idx, alias, val) {
    if (_paramRows[idx] !== undefined) {
        _paramRows[idx][alias] = val;
    }
}

function buildParamRowAlias(row) {
    const parts = [];
    _paramAliases.forEach(alias => {
        const val = row[alias] !== undefined ? String(row[alias]) : '';
        if (val !== '') parts.push(alias + ':' + val);
    });
    return parts.length ? _paramFamilyAlias + '|' + parts.join('|') : _paramFamilyAlias;
}

async function addParamRow() {
    const row = ClientParamTable.collectAddRow('param-new-', _paramAliases, _paramFamilyDef?.params || []);
    _paramRows.push(row);
    renderParamTable();
    await persistCurrentParamConfig('新增成功');
}

async function deleteParamRow(idx) {
    _paramRows.splice(idx, 1);
    renderParamTable();
    await persistCurrentParamConfig('删除成功');
}

async function reorderParamRows(fromIdx, targetIdx) {
    const [row] = _paramRows.splice(fromIdx, 1);
    _paramRows.splice(targetIdx, 0, row);
    renderParamTable();
    await persistCurrentParamConfig('排序已保存');
}

// ── 构建 params_list（供模板保存 & 使用） ──
function buildParamConfigParamsList() {
    return _paramRows.map(row => {
        const params = {};
        _paramAliases.forEach(alias => {
            params[alias] = row[alias] !== undefined ? row[alias] : '';
        });
        return params;
    });
}

function applySavedFactorAliases(factors) {
    (factors || []).forEach(factor => {
        const idx = Number(factor.template_row_index || 0);
        if (_paramRows[idx]) {
            _paramRows[idx].__factor_alias = factor.factor_alias || '';
        }
    });
}

async function persistCurrentParamConfig(successMessage) {
    const status = document.getElementById('param-tpl-status');
    try {
        if (!_paramRows.length) {
            const resp = await fetch('/custom-factors/api/param-configs/' + encodeURIComponent(_paramFamilyAlias), {
                method: 'DELETE'
            });
            const data = await resp.json();
            if (!data.success && resp.status !== 404) {
                if (status) status.textContent = '保存失败: ' + (data.error || '');
                return false;
            }
            _selectedParamConfig = null;
            if (status) status.textContent = '✓ 已清空我的配置';
            await loadParamTemplatesIntoSelect();
            return true;
        }
        const resp = await fetch('/custom-factors/api/param-configs/' + encodeURIComponent(_paramFamilyAlias), {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ params_list: buildParamConfigParamsList() })
        });
        const data = await resp.json();
        if (data.success) {
            applySavedFactorAliases(data.factors || []);
            renderParamTable();
            if (status) status.textContent = '✓ ' + (successMessage || '已保存我的配置');
            await loadParamTemplatesIntoSelect();
            return true;
        }
        if (status) status.textContent = '保存失败: ' + (data.error || '');
    } catch(e) {
        if (status) status.textContent = '网络错误';
    }
    return false;
}

// ── 抽屉内模板管理 ──
function updateParamTemplateNameLabel() {
    const label = document.getElementById('param-tpl-name-label');
    if (!label) return;
    if (!_selectedParamConfig) {
        label.style.display = 'none';
        label.textContent = '';
        label.title = '当前参数配置';
        return;
    }
    label.textContent = `${_selectedParamConfig.owner_alias || _selectedParamConfig.owner_username || ''} / ${_selectedParamConfig.name || ''}`;
    label.title = _selectedParamConfig.editable
        ? '自己的参数配置，可更新或删除'
        : '下级用户的参数配置，只能查看';
    label.style.display = '';
}

async function loadParamTemplatesIntoSelect() {
    const status = document.getElementById('param-tpl-status');
    _paramTemplates = [];
    _paramConfigUsers = [];
    _selectedParamConfig = null;
    _paramTemplateCanFilterOrganization = false;
    renderParamTemplateOptions();
    try {
        // 因子库这里的 scope 是“当前用户配置 + 可见下级用户只读配置”，不是单因子测试的模板导入。
        const resp = await fetch('/custom-factors/api/param-configs/' + encodeURIComponent(_paramFamilyAlias));
        const data = await resp.json();
        if (data.success && data.users) {
            _paramConfigUsers = data.users;
            _paramTemplates = flattenParamConfigUsers(data.users);
            _paramTemplateCanFilterOrganization = !!data.can_filter_organization;
            loadOwnParamConfigFromUsers(data.users);
        }
        renderParamTemplateOptions();
    } catch(e) {
        if (status) status.textContent = '加载模板列表失败';
    }
}

function loadOwnParamConfigFromUsers(users) {
    const own = (users || []).find(user => user.editable && user.config && Array.isArray(user.config.params_list));
    if (!own) return;
    _paramRows = own.config.params_list.map((obj, idx) => {
        const row = {};
        _paramAliases.forEach(a => { row[a] = obj[a] !== undefined ? String(obj[a]) : ''; });
        const factor = (own.factors || []).find(f => Number(f.template_row_index || 0) === idx);
        if (factor) row.__factor_alias = factor.factor_alias || '';
        return row;
    });
    renderParamTable();
}

function renderParamTemplateOptions() {
    const list = document.getElementById('param-config-results');
    const orgSel = document.getElementById('param-tpl-org-filter');
    const orgRow = document.getElementById('param-tpl-org-filter-row');
    const orgFilter = orgSel?.value || '';
    const userFilter = (document.getElementById('param-tpl-owner-filter')?.value || '').trim().toLowerCase();
    if (!list) return;
    renderParamTemplateOrgOptions(orgSel, orgRow, orgFilter);
    const items = [];
    _paramTemplates.forEach(t => {
        if (orgFilter && (t.owner_organization_id || '') !== orgFilter) return;
        const ownerText = `${t.owner_alias || ''} ${t.owner_username || ''}`;
        const haystack = ownerText.toLowerCase();
        if (userFilter && !haystack.includes(userFilter)) return;
        items.push(t);
    });

    if (!items.length) {
        list.innerHTML = '<div class="factor-config-empty">未找到该用户的参数配置因子</div>';
        _selectedParamConfig = null;
        updateParamTemplateNameLabel();
        return;
    }
    list.innerHTML = items.map((item, idx) => renderParamConfigResult(item, idx)).join('');
    list.querySelectorAll('[data-param-config-idx]').forEach(btn => {
        btn.addEventListener('click', () => selectAndLoadParamConfig(items[Number(btn.dataset.paramConfigIdx)]));
    });
    if (_selectedParamConfig && !items.some(item => isSameParamConfig(item, _selectedParamConfig))) {
        _selectedParamConfig = null;
    }
    updateParamTemplateNameLabel();
}

function renderParamConfigResult(item, idx) {
    const readonly = item.editable ? '' : '（只读）';
    const selected = _selectedParamConfig && isSameParamConfig(item, _selectedParamConfig) ? ' style="border-color:#0078d4;background:#eef6ff;"' : '';
    return '<button type="button" class="factor-config-result" data-param-config-idx="' + idx + '"' + selected + '>' +
        '<span><span class="factor-config-result-title">' + escHtml(item.factor_alias || item.name || '') + '</span>' +
        '<span class="factor-config-result-meta">' + escHtml((item.owner_alias || item.owner_username || '') + ' / ' + (item.name || '') + readonly) + '</span></span>' +
        '<span class="factor-config-result-meta">第 ' + (Number(item.template_row_index || 0) + 1) + ' 行</span>' +
        '</button>';
}

function isSameParamConfig(a, b) {
    return a && b && a.id === b.id && a.owner_username === b.owner_username;
}

function flattenParamConfigUsers(users) {
    const result = [];
    users.forEach(user => {
        (user.factors || []).forEach(factor => {
            result.push({
                id: user.owner_username || factor.template_id,
                name: factor.template_name || user.owner_username || '',
                factor_alias: factor.factor_alias,
                template_row_index: factor.template_row_index,
                updated_at: factor.updated_at || '',
                owner_username: user.owner_username || '',
                owner_alias: user.owner_alias || user.owner_username || '',
                owner_organization_id: user.owner_organization_id || '',
                owner_organization_name: user.owner_organization_name || '',
                editable: !!user.editable,
            });
        });
    });
    return result;
}

function renderParamTemplateOrgOptions(orgSel, orgRow, selectedOrg) {
    if (!orgSel || !orgRow) return;
    orgRow.style.display = _paramTemplateCanFilterOrganization ? '' : 'none';
    if (!_paramTemplateCanFilterOrganization) {
        orgSel.value = '';
        return;
    }
    const orgs = new Map();
    _paramTemplates.forEach(t => {
        const id = t.owner_organization_id || '';
        if (!id || orgs.has(id)) return;
        orgs.set(id, t.owner_organization_name || id);
    });
    orgSel.innerHTML = '<option value="">全部机构</option>' + [...orgs.entries()]
        .sort((a, b) => a[1].localeCompare(b[1]))
        .map(([id, name]) => '<option value="' + escAttr(id) + '">' + escHtml(name) + '</option>')
        .join('');
    if ([...orgSel.options].some(opt => opt.value === selectedOrg)) {
        orgSel.value = selectedOrg;
    }
}

function filterParamTemplatesByOwner() {
    renderParamTemplateOptions();
}

async function selectAndLoadParamConfig(config) {
    _selectedParamConfig = config;
    renderParamTemplateOptions();
    await loadParamTemplate();
}

async function loadParamTemplate() {
    const status = document.getElementById('param-tpl-status');
    if (!_selectedParamConfig) {
        if (status) status.textContent = '请先搜索并选择参数配置因子';
        return;
    }
    const tplName = _selectedParamConfig.name;
    const ownerUsername = _selectedParamConfig.owner_username || '';
    if (status) status.textContent = '加载中...';
    try {
        const resp = await fetch('/custom-factors/api/param-configs/' + encodeURIComponent(_paramFamilyAlias) + '/' + encodeURIComponent(ownerUsername));
        const data = await resp.json();
        if (data.success && data.config && data.config.params_list) {
            _paramRows = data.config.params_list.map(obj => {
                const row = {};
                _paramAliases.forEach(a => { row[a] = obj[a] !== undefined ? String(obj[a]) : ''; });
                return row;
            });
            _paramTemplates
                .filter(item => item.owner_username === ownerUsername)
                .forEach(item => {
                    const idx = Number(item.template_row_index || 0);
                    if (_paramRows[idx]) _paramRows[idx].__factor_alias = item.factor_alias || '';
                });
            renderParamTable();
            updateParamTemplateNameLabel();
            if (status) status.textContent = '✓ 已查看配置: ' + tplName;
            document.getElementById('param-drawer-summary-text').textContent = _paramRows.length + ' 行参数';
        } else {
            if (status) status.textContent = '加载失败';
        }
    } catch(e) {
        if (status) status.textContent = '网络错误';
    }
}

async function saveParamTemplate() {
    const status = document.getElementById('param-tpl-status');
    if (status) status.textContent = '保存中...';
    await persistCurrentParamConfig('已保存我的配置');
}

async function updateParamTemplate() {
    const status = document.getElementById('param-tpl-status');
    if (!_selectedParamConfig) {
        await saveParamTemplate();
        return;
    }
    const tplName = _selectedParamConfig.name;
    if (!_selectedParamConfig.editable) {
        if (status) status.textContent = '下级用户的配置只能查看，不能更新';
        return;
    }
    if (status) status.textContent = '更新中...';
    await persistCurrentParamConfig('已更新: ' + tplName);
}

async function deleteParamTemplate() {
    const status = document.getElementById('param-tpl-status');
    if (!_selectedParamConfig) {
        if (status) status.textContent = '请先搜索并选择参数配置因子';
        return;
    }
    const tplName = _selectedParamConfig.name;
    if (!_selectedParamConfig.editable) {
        if (status) status.textContent = '下级用户的配置只能查看，不能删除';
        return;
    }
    if (!confirm('确定删除参数配置「' + tplName + '」？')) return;
    if (status) status.textContent = '删除中...';
    try {
        const resp = await fetch('/custom-factors/api/param-configs/' + encodeURIComponent(_paramFamilyAlias), {
            method: 'DELETE'
        });
        const data = await resp.json();
        if (data.success) {
            if (status) status.textContent = '✓ 已删除';
            _selectedParamConfig = null;
            await loadParamTemplatesIntoSelect();
        } else {
            if (status) status.textContent = '删除失败: ' + (data.error || '');
        }
    } catch(e) {
        if (status) status.textContent = '网络错误';
    }
}
