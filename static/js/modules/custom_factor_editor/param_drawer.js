// ═══════════════════════════════════════════════════════════
// 参数配置右侧抽屉 (照抄 parameter_module.html 的交互模式)
// ═══════════════════════════════════════════════════════════

let _paramFamilyAlias = '';              // 当前选中的因子家族名/ID
let _paramFamilyDef = null;              // 因子家族定义（含 params 数组）
let _paramAliases = [];              // 参数别名列表（列头）
let _paramRows = [];                 // 参数行数据 [{alias: value}, ...]
let _paramDragSrcIdx = null;         // 拖拽源索引

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
    const tbody = document.getElementById('param-table-body');
    if (!tbody) return;

    // 先更新表头
    const thead = document.getElementById('param-table-head');
    if (thead) {
        thead.innerHTML = '<tr>' +
            '<th style="min-width:100px;">因子(家族)名</th>' +
            _paramAliases.map(a => '<th>' + escHtml(a) + '</th>').join('') +
            '<th style="min-width:80px;">操作</th>' +
            '</tr>';
    }

    let html = '';

    // 新增行（对齐单因子测试参数抽屉：默认值填入 value，新增行置顶）
    html += '<tr id="add_row">';
    html += '<td>' + escHtml(_paramFamilyAlias) + '</td>';
    _paramAliases.forEach(alias => {
        const defVal = escHtml(getDefaultParamRow()[alias] || '');
        html += '<td><input type="text" id="param-new-' + escHtml(alias) + '" ' +
            'value="' + defVal + '" ' +
            'onkeydown="if(event.key===\'Enter\'){event.preventDefault();addParamRow()}" ' +
            '></td>';
    });
    html += '<td style="text-align:center;">' +
        '<button class="param-btn" onclick="addParamRow()">新增</button>' +
        '</td>';
    html += '</tr>';

    _paramRows.forEach((row, i) => {
        html += '<tr class="param-row" draggable="true" data-idx="' + i + '" ondragstart="onParamDragStart(event,' + i + ')" ondragover="onParamDragOver(event)" ondrop="onParamDrop(event,' + i + ')" ondragend="onParamDragEnd()">';
        html += '<td>' + escHtml(buildParamRowAlias(row)) + '</td>';
        _paramAliases.forEach(alias => {
            const val = row[alias] !== undefined ? row[alias] : '';
            html += '<td>' + escHtml(val) + '</td>';
        });
        html += '<td style="text-align:center;">' +
            '<button class="param-btn param-btn-danger" onclick="deleteParamRow(' + i + ')">删除</button>' +
            '</td>';
        html += '</tr>';
    });

    tbody.innerHTML = html;

    // 更新摘要
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
        if (val !== '') parts.push(alias + '_' + val);
    });
    return parts.length ? _paramFamilyAlias + '|' + parts.join('|') : _paramFamilyAlias;
}

function addParamRow() {
    const row = {};
    _paramAliases.forEach(alias => {
        const input = document.getElementById('param-new-' + alias);
        row[alias] = (input && input.value) ? input.value : getDefaultParamRow()[alias] || '';
    });
    _paramRows.push(row);
    renderParamTable();
}

function deleteParamRow(idx) {
    _paramRows.splice(idx, 1);
    renderParamTable();
}

// ── 拖拽重排行 ──
function onParamDragStart(e, idx) {
    _paramDragSrcIdx = idx;
    e.target.style.opacity = '0.4';
    e.dataTransfer.effectAllowed = 'move';
}
function onParamDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
}
function onParamDrop(e, targetIdx) {
    e.preventDefault();
    if (_paramDragSrcIdx !== null && _paramDragSrcIdx !== targetIdx) {
        const [row] = _paramRows.splice(_paramDragSrcIdx, 1);
        _paramRows.splice(targetIdx, 0, row);
        renderParamTable();
    }
}
function onParamDragEnd() {
    _paramDragSrcIdx = null;
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

// ── 抽屉内模板管理 ──
async function loadParamTemplatesIntoSelect() {
    const sel = document.getElementById('param-tpl-select');
    const status = document.getElementById('param-tpl-status');
    if (!sel) return;
    sel.innerHTML = '<option value="">— 选择参数配置 —</option>';
    try {
        const resp = await fetch('/api/params_templates/' + encodeURIComponent(_paramFamilyAlias) + '?include_visible=1');
        const data = await resp.json();
        if (data.success && data.templates) {
            data.templates.forEach(t => {
                const owner = t.owner_alias ? `${t.owner_alias} / ` : '';
                const editable = t.editable ? '1' : '0';
                sel.innerHTML += '<option value="' + escAttr(t.id) + '" data-owner="' + escAttr(t.owner_username || '') + '" data-editable="' + editable + '">' +
                    escHtml(owner + t.name + (t.editable ? '' : '（只读）')) + '</option>';
            });
        }
    } catch(e) {
        if (status) status.textContent = '加载模板列表失败';
    }
}

async function loadParamTemplate() {
    const sel = document.getElementById('param-tpl-select');
    const status = document.getElementById('param-tpl-status');
    if (!sel || !sel.value) {
        if (status) status.textContent = '请先选择参数配置';
        return;
    }
    const tplId = sel.value;
    const tplName = sel.options[sel.selectedIndex].text;
    const ownerUsername = sel.options[sel.selectedIndex].dataset.owner || '';
    if (status) status.textContent = '加载中...';
    try {
        const ownerParam = ownerUsername ? '?owner_username=' + encodeURIComponent(ownerUsername) : '';
        const resp = await fetch('/api/params_templates/' + encodeURIComponent(_paramFamilyAlias) + '/' + tplId + ownerParam);
        const data = await resp.json();
        if (data.success && data.template && data.template.params_list) {
            _paramRows = data.template.params_list.map(obj => {
                const row = {};
                _paramAliases.forEach(a => { row[a] = obj[a] !== undefined ? String(obj[a]) : ''; });
                return row;
            });
            renderParamTable();
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
    const name = prompt('配置名称 (用于保存当前参数配置):');
    if (!name) return;
    const status = document.getElementById('param-tpl-status');
    if (status) status.textContent = '保存中...';
    try {
        const resp = await fetch('/api/params_templates/' + encodeURIComponent(_paramFamilyAlias), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name, params_list: buildParamConfigParamsList() })
        });
        const data = await resp.json();
        if (data.success) {
            if (status) status.textContent = '✓ 已保存: ' + name;
            await loadParamTemplatesIntoSelect();
        } else {
            if (status) status.textContent = '保存失败: ' + (data.error || '');
        }
    } catch(e) {
        if (status) status.textContent = '网络错误';
    }
}

async function updateParamTemplate() {
    const sel = document.getElementById('param-tpl-select');
    const status = document.getElementById('param-tpl-status');
    if (!sel || !sel.value) {
        if (status) status.textContent = '请先选择参数配置';
        return;
    }
    const tplId = sel.value;
    const tplName = sel.options[sel.selectedIndex].text;
    const editable = sel.options[sel.selectedIndex].dataset.editable === '1';
    if (!editable) {
        if (status) status.textContent = '下级用户的配置只能查看，不能更新';
        return;
    }
    if (status) status.textContent = '更新中...';
    try {
        const resp = await fetch('/api/params_templates/' + encodeURIComponent(_paramFamilyAlias) + '/' + tplId, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ params_list: buildParamConfigParamsList() })
        });
        const data = await resp.json();
        if (data.success) {
            if (status) status.textContent = '✓ 已更新: ' + tplName;
        } else {
            if (status) status.textContent = '更新失败: ' + (data.error || '');
        }
    } catch(e) {
        if (status) status.textContent = '网络错误';
    }
}

async function deleteParamTemplate() {
    const sel = document.getElementById('param-tpl-select');
    const status = document.getElementById('param-tpl-status');
    if (!sel || !sel.value) {
        if (status) status.textContent = '请先选择参数配置';
        return;
    }
    const tplId = sel.value;
    const tplName = sel.options[sel.selectedIndex].text;
    const editable = sel.options[sel.selectedIndex].dataset.editable === '1';
    if (!editable) {
        if (status) status.textContent = '下级用户的配置只能查看，不能删除';
        return;
    }
    if (!confirm('确定删除参数配置「' + tplName + '」？')) return;
    if (status) status.textContent = '删除中...';
    try {
        const resp = await fetch('/api/params_templates/' + encodeURIComponent(_paramFamilyAlias) + '/' + tplId, {
            method: 'DELETE'
        });
        const data = await resp.json();
        if (data.success) {
            if (status) status.textContent = '✓ 已删除';
            await loadParamTemplatesIntoSelect();
        } else {
            if (status) status.textContent = '删除失败: ' + (data.error || '');
        }
    } catch(e) {
        if (status) status.textContent = '网络错误';
    }
}
