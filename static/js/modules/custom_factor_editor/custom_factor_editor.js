// ═══════════════════════════════════════════════════════════
// 全局状态
// ═══════════════════════════════════════════════════════════
let _currentMode = 'code';
let _currentFactorFamilyId = null;   // 正在编辑的因子家族 ID（null = 无）
let _currentFactorFamilySource = 'custom'; // 'custom' | 'public'
let _currentFactorFamilyOwner = null;
let _isNew = false;            // 是否为新建
let _dirty = false;
let _factorFamilies = [];  // {name, id, type:'custom'|'public', chinese_name, category, updated_at, is_public, params, ...}
let _groupedFactorFamilies = {};  // {group: [...]}
let _validatedFactorDraft = null;
let _validatedSourceSnapshot = '';
let _editingOriginalParamAliases = '';

// ═══════════════════════════════════════════════════════════
// 初始化
// ═══════════════════════════════════════════════════════════
async function init() {
    await loadFactorFamilyList();
}

let _isAdmin = false;

async function loadFactorFamilyList() {
    try {
        const includeSubordinates = document.getElementById('include-subordinate-factors')?.checked;
        const res = await fetch('/custom-factors/api/list' + (includeSubordinates ? '?include_subordinates=1' : ''));
        const data = await res.json();
        const custom = (data.custom_factors || []).map(f => ({...f, type: 'custom'}));
        const publicF = (data.public_factors || []).map(f => ({...f, type: 'public'}));
        _factorFamilies = [...custom, ...publicF];
        _groupedFactorFamilies = groupByCamel(_factorFamilies);
        _isAdmin = !!data.is_admin;
        renderFactorFamilyList();
    } catch(e) {
        document.getElementById('factor-family-list').innerHTML =
            '<div class="factor-family-list-empty" style="color:#d40000">加载失败</div>';
    }
}

function getGroup(name) {
    let group = '';
    let upperCount = 0;
    for (const c of name) {
        if (c === c.toUpperCase() && c !== c.toLowerCase()) {
            upperCount++;
            if (upperCount === 1) group += c;
            else if (upperCount === 2) break;
            else group += c;
        } else {
            if (upperCount === 1) group += c;
        }
    }
    return group || name;
}

function groupByCamel(factors) {
    const groups = {};
    for (const f of factors) {
        const g = getGroup(f.name || f.id);
        if (!groups[g]) groups[g] = [];
        groups[g].push(f);
    }
    // 每组内排序：自定义优先，然后按 name 字典序
    for (const g in groups) {
        groups[g].sort((a, b) => {
            const typeOrder = {custom: 0, public: 1};
            const ta = typeOrder[a.type] ?? 1;
            const tb = typeOrder[b.type] ?? 1;
            if (ta !== tb) return ta - tb;
            return (a.name || '').localeCompare(b.name || '');
        });
    }
    return groups;
}

function filterFactorFamilyList() {
    renderFactorFamilyList();
}

function renderFactorFamilyList() {
    const list = document.getElementById('factor-family-list');
    const filterText = (document.getElementById('factor-family-filter')?.value || '').toLowerCase();

    // 收集所有因子并按分组过滤
    const filtered = {};
    const groupKeys = Object.keys(_groupedFactorFamilies).sort();
    for (const g of groupKeys) {
        const items = _groupedFactorFamilies[g].filter(f => {
            if (!filterText) return true;
            const name = (f.name || '').toLowerCase();
            const cn = (f.chinese_name || '').toLowerCase();
            return name.includes(filterText) || cn.includes(filterText);
        });
        if (items.length > 0) filtered[g] = items;
    }

    if (Object.keys(filtered).length === 0) {
        list.innerHTML = '<div class="factor-family-list-empty">' +
            (filterText ? '无匹配因子' : '暂无因子<br><br>点击上方按钮创建自定义因子') +
            '</div>';
        return;
    }

    let html = '';
    for (const g of Object.keys(filtered).sort()) {
        const groupItems = filtered[g].slice().sort(compareFactorFamiliesForDisplay);
        const ownerGroups = {};
        groupItems.forEach(f => {
            const ownerKey = getFactorFamilyOwnerSortKey(f);
            if (!ownerGroups[ownerKey]) ownerGroups[ownerKey] = [];
            ownerGroups[ownerKey].push(f);
        });
        html += `<div class="collapsible-factor-node collapsible-factor-group">
            <button class="collapsible-factor-header" type="button">
                <span class="caret">▶</span>
                <span class="collapsible-factor-title">${escHtml(g)}</span>
                <span class="collapsible-factor-count">${groupItems.length}</span>
            </button>
            <div class="collapsible-factor-body">`;
        for (const ownerKey of Object.keys(ownerGroups).sort()) {
            const ownerItems = ownerGroups[ownerKey];
            html += `<div class="collapsible-factor-node collapsible-factor-owner">
                <button class="collapsible-factor-header" type="button">
                    <span class="caret">▶</span>
                    <span class="collapsible-factor-title">${escHtml(getFactorFamilyOwnerLabel(ownerItems[0]))}</span>
                    <span class="collapsible-factor-count">${ownerItems.length}</span>
                </button>
                <div class="collapsible-factor-body">`;
            for (const f of ownerItems) {
            const ownerUsername = f.owner_username || '';
            const active = (
                f.id === _currentFactorFamilyId
                && f.type === (_currentFactorFamilySource || 'custom')
                && (f.type === 'public' || ownerUsername === (_currentFactorFamilyOwner || ''))
            ) ? ' active' : '';
            const name = escHtml(f.name || f.id);
            const cn = escHtml(f.chinese_name || '');
            const cat = f.type === 'custom'
                ? escHtml(f.category || '自编')
                : '公共';
            const metaParts = [cn, cat];
            if (f.type === 'custom' && f.owner_alias) {
                metaParts.push(f.can_edit ? '我的因子' : `来自 ${escHtml(f.owner_alias)}`);
            }
            if (f.type === 'custom' && f.updated_at) {
                metaParts.push(escHtml((f.updated_at || '').slice(0, 16)));
            }
            const meta = metaParts.filter(Boolean).join(' · ');
            const sourceTag = f.type === 'custom'
                ? `<span class="source-tag custom">${f.can_edit ? '我' : escHtml(f.owner_alias || '下级')}</span>`
                : '<span class="source-tag public">公共</span>';
                html += `<div class="factor-family-list-item${active}" onclick="selectFactorFamily('${escAttr(f.id)}', '${escAttr(f.type)}', '${escAttr(ownerUsername)}')">
                <div class="info">
                    <div class="name">${name}${sourceTag}</div>
                    <div class="meta">${meta}</div>
                </div>
            </div>`;
            }
            html += '</div></div>';
        }
        html += '</div></div>';
    }
    list.innerHTML = html;
    if (typeof bindCollapsibleFactorLists === 'function') bindCollapsibleFactorLists(list);
}

function getFactorFamilyOwnerSortKey(f) {
    if (f.type === 'public') return '公共';
    return `${f.owner_organization_name || f.owner_organization_id || '未分机构'}/${f.owner_alias || f.owner_username || '未知用户'}`;
}

function getFactorFamilyOwnerLabel(f) {
    if (f.type === 'public') return '公共';
    if (f.can_edit) return '我的因子';
    return `${f.owner_organization_name || f.owner_organization_id || '未分机构'} / ${f.owner_alias || f.owner_username || '未知用户'}`;
}

function compareFactorFamiliesForDisplay(a, b) {
    return (
        getGroup(a.name || a.id).localeCompare(getGroup(b.name || b.id)) ||
        getFactorFamilyOwnerSortKey(a).localeCompare(getFactorFamilyOwnerSortKey(b)) ||
        (a.name || a.id || '').localeCompare(b.name || b.id || '')
    );
}

function escHtml(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
}

function escAttr(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function getFactorFamilies() {
    return _factorFamilies;
}

// ═══════════════════════════════════════════════════════════
// 因子家族选择 / 新建 / 模式切换
// ═══════════════════════════════════════════════════════════

async function selectFactorFamily(factorFamilyId, factorFamilySource, ownerUsername) {
    _currentFactorFamilySource = factorFamilySource || 'custom';
    _currentFactorFamilyOwner = ownerUsername || '';
    let factor;
    if (_currentFactorFamilySource === 'public') {
        // 公共因子家族：fetch 详情
        try {
            const res = await fetch(`/custom-factors/api/public-factor/${encodeURIComponent(factorFamilyId)}`);
            const data = await res.json();
            if (data.success && data.factor) {
                factor = data.factor;
                factor.type = 'public';
            }
        } catch(e) {}
        if (!factor) return;
    } else {
        // 自定义因子家族：fetch 详情获取 source_code
        try {
            const ownerParam = _currentFactorFamilyOwner ? `?owner_username=${encodeURIComponent(_currentFactorFamilyOwner)}` : '';
            const res = await fetch(`/custom-factors/api/get/${encodeURIComponent(factorFamilyId)}${ownerParam}`);
            const data = await res.json();
            if (data.success && data.factor) {
                factor = data.factor;
                factor.type = 'custom';
            }
        } catch(e) {}
        if (!factor) return;
    }
    // 合并列表中的额外字段
    const listFactorFamily = _factorFamilies.find(f =>
        f.id === factorFamilyId
        && f.type === _currentFactorFamilySource
        && (f.type === 'public' || (f.owner_username || '') === (_currentFactorFamilyOwner || ''))
    );
    if (listFactorFamily) {
        factor.chinese_name = factor.chinese_name || listFactorFamily.chinese_name;
        factor.category = factor.category || listFactorFamily.category;
        factor.updated_at = factor.updated_at || listFactorFamily.updated_at;
        factor.description = factor.description || listFactorFamily.description;
        factor.math_expr = factor.math_expr || listFactorFamily.math_expr;
        factor.params = (factor.params && factor.params.length) ? factor.params : listFactorFamily.params;
        factor.owner_username = factor.owner_username || listFactorFamily.owner_username;
        factor.owner_alias = factor.owner_alias || listFactorFamily.owner_alias;
        factor.can_edit = factor.can_edit || listFactorFamily.can_edit;
    }
    _currentFactorFamilyId = factorFamilyId;
    _isNew = false;
    _dirty = false;
    renderFactorFamilyList();
    // 自定义和公共因子家族都默认使用只读视图
    renderFactorFamilyReadonlyView(factor);
}

// ═══════════════════════════════════════════════════════════
// 因子只读视图（公共 + 自定义通用）
// ═══════════════════════════════════════════════════════════
function renderFactorFamilyReadonlyView(factor) {
    const isPublic = factor.type === 'public';
    const typeLabel = isPublic ? '公共因子' : '自定义因子';
    const ownerText = !isPublic && factor.owner_alias ? ` / ${factor.owner_alias}` : '';
    document.getElementById('editor-title').textContent = `${factor.name}（${typeLabel}${ownerText} — 只读）`;
    document.getElementById('editor-footer').style.display = 'none';
    const sourceCode = factor.source_code || '';
    const canEditSource = (!isPublic && factor.can_edit) || (isPublic && _isAdmin);
    const canDelete = !isPublic && factor.can_edit && _isAdmin;
    document.getElementById('editor-body').innerHTML = `
        <div class="code-pane" style="overflow:hidden; display:flex; flex-direction:column;">
            <div class="code-area" style="display:flex; flex-direction:column;">
                <div style="margin-bottom:6px; display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-size:13px; color:#888;">源码 (${escHtml(factor.name)}.py) — 只读</span>
                    <button class="btn-validate" id="btn-validate-public" onclick="validateReadonlyExpr('${escAttr(factor.name)}', ${isPublic})"
                        style="font-size:12px; padding:4px 12px;">校验表达式树</button>
                </div>
                <div class="code-editor-shell readonly">
                    <pre id="code-source-readonly-lines" class="code-line-gutter">${renderCodeLineNumbers(sourceCode)}</pre>
                    <pre id="code-source-readonly-highlight" class="code-editor-highlight" onscroll="syncReadonlyCodeScroll()">${highlightPython(sourceCode)}</pre>
                </div>
                <div id="readonly-tree-repr" style="margin-top:6px; display:none; background:#f0f4f8; border:1px solid #e2e8f0;
                    border-radius:6px; padding:10px 14px; font-family:'SF Mono','Fira Code',monospace;
                    font-size:12px; color:#333; max-height:180px; overflow:auto; white-space:pre; line-height:1.5;"></div>
            </div>
        </div>
        <div class="editor-resize-handle" title="拖拽调整代码区域宽度"></div>
        <div class="config-pane">
            <div class="config-section">
                <h3>${escHtml(factor.chinese_name || factor.name)}</h3>
                <div id="readonly-math-block" style="display:none;background:#fafbfc;border-radius:6px;padding:16px;font-size:18px;margin:8px 0 12px;text-align:center;"></div>
                <div id="readonly-desc-block" style="display:none;margin-top:8px;">
                    <div class="setting-summary-row" onclick="toggleReadonlyDesc()">
                        <span class="setting-summary-label">📖 因子说明</span>
                        <span class="setting-summary-value">有说明</span>
                        <span class="readonly-desc-toggle" style="font-size:12px;color:#4a90d9;flex-shrink:0;padding:2px 8px;border:1px solid #d0d5dd;border-radius:10px;">▼ 展开</span>
                    </div>
                    <div id="readonly-desc-content" style="display:none;margin-top:6px;border:1px solid #e5e7eb;border-radius:10px;background:#ffffff;padding:18px;">
                        <div id="readonly-desc-rendered" style="font-size:14px;line-height:1.75;color:#374151;"></div>
                    </div>
                </div>
            </div>
            ${(factor.params && factor.params.length > 0) ? `
            <div class="config-section">
                <h3>参数列表</h3>
                <table class="param-info-table">
                    <thead><tr>
                        <th>别名</th>
                        <th>类型</th>
                        <th>默认值</th>
                    </tr></thead>
                    <tbody>
                        ${factor.params.map(p => `
                            <tr>
                            <td title="${escAttr(getParamAliasTitle(p))}">${escHtml(p.alias)}</td>
                            <td title="${escAttr(p.value_space_desc || '')}">${escHtml(p.type || '—')}</td>
                            <td>${escHtml(getParamDefaultValue(p))}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
            ` : ''}
            <div class="config-section">
                <button class="btn-validate" onclick="openFactorFamilyParamDrawer('${escAttr(factor.name)}')"
                    style="width:100%; padding:8px; font-size:13px;">⚙️ 参数配置</button>
            </div>
            <div style="margin-top:12px;">
                ${canEditSource ? `<button class="btn-edit-public" onclick="enterEditMode('${escAttr(factor.name)}', ${isPublic})"
                    style="width:100%; padding:8px; font-size:13px; background:#4a90d9; color:#fff; border:none; border-radius:6px; cursor:pointer;">✏️ 编辑源码</button>` : ''}
                ${canDelete ? `<button class="btn-delete-factor" onclick="deleteFactor('${escAttr(factor.id)}')"
                    style="width:100%; padding:8px; font-size:13px; background:#d40000; color:#fff; border:none; border-radius:6px; cursor:pointer; margin-top:6px;">🗑 删除因子</button>` : ''}
                ${isPublic ? '<p style="margin-top:8px;color:#999;font-size:12px;">💡 公共因子不可删除。</p>' : ''}
            </div>
        </div>
    `;
    renderFactorFamilyReadonlyMathAndDesc(factor);
    initCodePaneResizer();
    requestAnimationFrame(updateAllCodeLineNumbers);
}

function renderFactorFamilyReadonlyMathAndDesc(factor) {
    const mathBlock = document.getElementById('readonly-math-block');
    const descBlock = document.getElementById('readonly-desc-block');
    const descContent = document.getElementById('readonly-desc-content');
    const descRendered = document.getElementById('readonly-desc-rendered');
    if (descContent) descContent.style.display = 'none';
    if (typeof renderDrawerMathAndDesc === 'function') {
        renderDrawerMathAndDesc(factor.math_expr, factor.description, mathBlock, descBlock, descRendered);
    }
}

function toggleReadonlyDesc() {
    const content = document.getElementById('readonly-desc-content');
    const toggle = document.querySelector('.readonly-desc-toggle');
    if (!content) return;
    const isOpen = content.style.display !== 'none';
    content.style.display = isOpen ? 'none' : '';
    if (toggle) toggle.textContent = isOpen ? '▼ 展开' : '▲ 收起';
}

// 进入编辑模式（从只读视图切到代码编辑器）
function enterEditMode(factorName, isPublic) {
    // 直接进入编辑器：已有 factor family id 在 _currentFactorFamilyId 中，fetch 最新源码
    const fetchUrl = isPublic
        ? `/custom-factors/api/public-factor/${encodeURIComponent(factorName)}`
        : `/custom-factors/api/get/${encodeURIComponent(_currentFactorFamilyId)}`;
    fetch(fetchUrl)
        .then(r => r.json())
        .then(data => {
            if (data.success && data.factor) {
                data.factor.type = isPublic ? 'public' : 'custom';
                // 如果是公共因子，允许管理员保存为自定义副本（不能覆盖公共）
                renderCodeEditor(data.factor);
                document.getElementById('editor-title').textContent =
                    `${factorName}（${isPublic ? '公共因子' : '自定义因子'} — 编辑模式）`;
            }
        });
}

// 只读视图的校验
async function validateReadonlyExpr(factorName, isPublic) {
    const btn = document.getElementById('btn-validate-public');
    const treeDiv = document.getElementById('readonly-tree-repr');
    btn.textContent = '校验中...';
    btn.className = 'btn-validate';
    try {
        const res = await fetch('/custom-factors/api/validate', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ factor_name: factorName, is_public: isPublic })
        });
        const data = await res.json();
        if (data.valid && data.tree_repr) {
            btn.textContent = '✓ 表达式树';
            btn.className = 'btn-validate ok';
            treeDiv.style.display = 'block';
            treeDiv.textContent = data.tree_repr;
        } else {
            btn.textContent = '✗ ' + (data.error || '校验失败');
            btn.className = 'btn-validate err';
            treeDiv.style.display = 'none';
        }
    } catch(e) {
        btn.textContent = '校验失败';
        btn.className = 'btn-validate err';
    }
}

// 删除自定义因子
async function deleteFactor(factorFamilyId) {
    if (!confirm('确定删除此因子？此操作不可恢复！')) return;
    try {
        const res = await fetch('/custom-factors/api/delete/' + factorFamilyId, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast('因子已删除', 'success');
            _currentFactorFamilyId = null;
            _isNew = false;
            _dirty = false;
            await loadFactorFamilyList();
            document.getElementById('editor-body').innerHTML =
                '<div class="editor-placeholder">← 从左侧选择因子，或点击「新建因子」</div>';
            document.getElementById('editor-footer').style.display = 'none';
            document.getElementById('editor-title').textContent = '选择一个因子开始编辑';
        } else {
            showToast(data.error || '删除失败', 'error');
        }
    } catch(e) {
        showToast('网络错误', 'error');
    }
}

function renderMarkdown(md) {
    if (!md) return '';
    try {
        return (typeof marked !== 'undefined') ? marked.parse(String(md)) : '<pre>' + escHtml(md) + '</pre>';
    } catch(e) {
        return '<pre>' + escHtml(md) + '</pre>';
    }
}

function getParamDefaultValue(paramDef) {
    if (!paramDef) return '';
    const value = paramDef.default_value ?? '';
    return value === null || value === undefined ? '' : String(value);
}

function getParamAliasTitle(paramDef) {
    if (!paramDef) return '';
    const name = paramDef.name || paramDef.alias || '';
    const desc = paramDef.desc || '';
    return desc && desc !== name ? name + '\n' + desc : name;
}

function createNew() {
    _currentFactorFamilyId = null;
    _isNew = true;
    _dirty = false;
    renderFactorFamilyList();
    renderCodeEditor({
        name: '', chinese_name: '', description: '', category: '自编',
        source_code: getDefaultFactorTemplate(), type: 'custom'
    });
}

function switchMode(mode) {
    _currentMode = mode;
    document.querySelectorAll('.mode-tab').forEach(t => {
        t.classList.toggle('active', t.textContent.includes(mode === 'code' ? '代码' : '可视'));
    });
    if (_currentFactorFamilyId && _currentFactorFamilySource === 'custom') {
        const factor = _factorFamilies.find(f => f.id === _currentFactorFamilyId && f.type === 'custom');
        if (factor) {
            if (mode === 'code') renderCodeEditor(factor);
            else renderVisualEditor(factor);
            return;
        }
    }
    if (_isNew) createNew();
}

// ═══════════════════════════════════════════════════════════
// 代码编辑器模式
// ═══════════════════════════════════════════════════════════

function renderCodeEditor(factor) {
    const body = document.getElementById('editor-body');
    const footer = document.getElementById('editor-footer');
    const title = document.getElementById('editor-title');
    const isPublic = factor.type === 'public';
    if (isPublic) {
        title.textContent = `${factor.name}（公共因子 — 编辑模式）`;
    } else {
        title.textContent = _isNew ? '新建因子' : (factor.name || '未命名因子');
    }
    footer.style.display = '';
    _currentMode = 'code';

    const sourceCode = factor.source_code || '';
    const desc = factor.description || '';
    const cn = factor.chinese_name || '';
    const cat = factor.category || '自编';
    _editingOriginalParamAliases = Array.isArray(factor.params) ? factor.params.map(p => p.alias).join('|') : '';

    body.innerHTML = `
        <div class="code-pane" style="overflow:hidden; display:flex; flex-direction:column;">
            <div class="code-area" style="display:flex; flex-direction:column;">
                <div style="margin-bottom:6px; display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-size:13px; color:#888;">Python 源码编辑器</span>
                    <div>
                        <button class="btn-validate" id="btn-validate-custom" onclick="validateCustomExpr('${escAttr(factor.name || factor.id)}')"
                            style="font-size:12px; padding:4px 12px; margin-right:4px;">校验表达式树</button>
                        <button class="btn-validate" onclick="insertTemplate('factor_class')"
                            style="font-size:12px; padding:4px 8px;">📋 模板</button>
                    </div>
                </div>
                <div class="code-editor-shell">
                    <pre id="code-source-lines" class="code-line-gutter">${renderCodeLineNumbers(sourceCode)}</pre>
                    <pre id="code-source-highlight" class="code-editor-highlight">${highlightPython(sourceCode)}</pre>
                    <textarea id="code-source" placeholder="输入完整 Python class 源码..."
                        spellcheck="false" oninput="handleCodeInput()" onscroll="syncCodeEditorScroll()" onkeydown="handleCodeEditorKeydown(event)">${escHtml(sourceCode)}</textarea>
                </div>
            </div>
        </div>
        <div class="editor-resize-handle" title="拖拽调整代码区域宽度"></div>
        <div class="config-pane">
            <div class="config-section">
                <h3>基本信息</h3>
                <div class="field">
                    <label>中文名称</label>
                    <input type="text" id="cfg-cn" value="${escHtml(cn)}" placeholder="如 我的动量因子" oninput="_dirty=true">
                </div>
                <div class="field">
                    <label>分类</label>
                    <input type="text" id="cfg-cat" value="${escHtml(cat)}" placeholder="如 动量" oninput="_dirty=true">
                </div>
                <div class="field">
                    <label>描述 (Markdown)</label>
                    <textarea id="cfg-desc" oninput="_dirty=true">${escHtml(desc)}</textarea>
                </div>
            </div>

            <div class="config-section">
                <button class="btn-validate" id="btn-param-config" onclick="openOrValidateParamDrawer('${escAttr(factor.name || factor.id)}')"
                    style="width:100%; padding:8px; font-size:13px;">校验后配置参数</button>
                <div id="param-config-status" style="font-size:12px;color:#999;margin-top:6px;">请先校验表达式树</div>
            </div>

            <div class="config-section">
                <h3>算子/参数面板</h3>
                ${renderOperatorPalette()}
            </div>
        </div>
    `;

    // 重置自定义校验按钮
    const btnCustom = document.getElementById('btn-validate-custom');
    if (btnCustom) {
        btnCustom.className = 'btn-validate';
        btnCustom.textContent = '校验表达式树';
    }
    invalidateCodeValidation();
    syncPythonHighlight();
    initCodePaneResizer();
    requestAnimationFrame(updateAllCodeLineNumbers);
}

function handleCodeInput() {
    _dirty = true;
    invalidateCodeValidation();
    syncPythonHighlight();
}

function invalidateCodeValidation() {
    _validatedFactorDraft = null;
    _validatedSourceSnapshot = '';
    const btn = document.getElementById('btn-param-config');
    const status = document.getElementById('param-config-status');
    if (btn) btn.textContent = '校验后配置参数';
    if (status) status.textContent = '请先校验表达式树';
    const drawer = document.getElementById('param-drawer');
    if (drawer?.classList.contains('open') && typeof closeParamDrawer === 'function') {
        closeParamDrawer();
    }
}

function setValidatedFactorDraft(data, sourceCode) {
    const params = Array.isArray(data.params) ? data.params : [];
    const aliases = params.map(p => p.alias).join('|');
    const oldAliases = _validatedFactorDraft?.params?.map(p => p.alias).join('|') || _editingOriginalParamAliases;
    const factorName = data.factor_name || _currentFactorFamilyId || 'ValidatedFactor';
    _validatedFactorDraft = upsertValidatedFactorFamilyDef(factorName, params);
    _validatedSourceSnapshot = sourceCode;
    const btn = document.getElementById('btn-param-config');
    const status = document.getElementById('param-config-status');
    if (btn) btn.textContent = '参数配置';
    if (status) {
        status.textContent = oldAliases && oldAliases !== aliases
            ? '参数依赖已变化，当前参数表会按新表达式重建'
            : `校验通过：${params.length} 个参数`;
    }
}

function upsertValidatedFactorFamilyDef(factorName, params) {
    const type = _currentFactorFamilySource || 'custom';
    const owner = _currentFactorFamilyOwner || '';
    let def = _factorFamilies.find(f =>
        f.type === type
        && (f.id === _currentFactorFamilyId || f.name === factorName)
        && (type === 'public' || ((f.owner_username || '') === owner))
    );
    if (!def) {
        def = {
            id: _currentFactorFamilyId || factorName,
            name: factorName,
            type,
            owner_username: owner,
            can_edit: true,
        };
        _factorFamilies.push(def);
    }
    def.name = factorName;
    def.params = params;
    def.description = document.getElementById('cfg-desc')?.value || def.description || '';
    def.chinese_name = document.getElementById('cfg-cn')?.value || def.chinese_name || '';
    def.category = document.getElementById('cfg-cat')?.value || def.category || '自编';
    return def;
}

function openValidatedParamDrawer() {
    const sourceCode = document.getElementById('code-source')?.value || '';
    if (!_validatedFactorDraft || sourceCode !== _validatedSourceSnapshot) {
        showToast('请先校验当前源码，再配置参数', 'error');
        invalidateCodeValidation();
        return;
    }
    openFactorFamilyParamDrawer(_validatedFactorDraft.name);
}

async function openOrValidateParamDrawer(factorName) {
    const sourceCode = document.getElementById('code-source')?.value || '';
    if (_validatedFactorDraft && sourceCode === _validatedSourceSnapshot) {
        openValidatedParamDrawer();
        return;
    }
    const ok = await validateCustomExpr(factorName, {openParamsOnSuccess: true});
    if (!ok) showToast('表达式树校验未通过，无法配置参数', 'error');
}

function syncPythonHighlight() {
    const ta = document.getElementById('code-source');
    const pre = document.getElementById('code-source-highlight');
    const lines = document.getElementById('code-source-lines');
    if (!ta || !pre) return;
    pre.innerHTML = highlightPython(ta.value);
    if (lines) {
        lines.innerHTML = renderCodeLineNumbers(ta.value, measureCodeLineHeights(ta.value, ta));
    }
    syncCodeEditorScroll();
}

function syncCodeEditorScroll() {
    const ta = document.getElementById('code-source');
    const pre = document.getElementById('code-source-highlight');
    const lines = document.getElementById('code-source-lines');
    if (!ta || !pre) return;
    pre.scrollTop = ta.scrollTop;
    pre.scrollLeft = ta.scrollLeft;
    if (lines) lines.scrollTop = ta.scrollTop;
}

function syncReadonlyCodeScroll() {
    const pre = document.getElementById('code-source-readonly-highlight');
    const lines = document.getElementById('code-source-readonly-lines');
    if (pre && lines) lines.scrollTop = pre.scrollTop;
}

function renderCodeLineNumbers(code) {
    const rows = String(code || '').split('\n');
    const heights = arguments.length > 1 ? arguments[1] : [];
    return rows.map((_, index) => {
        const height = Number(heights[index]);
        const style = Number.isFinite(height) ? ` style="height:${height}px"` : '';
        return `<span class="code-line-gutter-row"${style}>${index + 1}</span>`;
    }).join('') || '<span class="code-line-gutter-row">1</span>';
}

function measureCodeLineHeights(code, referenceEl) {
    if (!referenceEl) return [];
    const style = getComputedStyle(referenceEl);
    const contentWidth = Math.max(
        20,
        referenceEl.clientWidth - parseFloat(style.paddingLeft || 0) - parseFloat(style.paddingRight || 0)
    );
    const measurer = document.createElement('div');
    measurer.style.position = 'absolute';
    measurer.style.visibility = 'hidden';
    measurer.style.pointerEvents = 'none';
    measurer.style.whiteSpace = 'pre-wrap';
    measurer.style.overflowWrap = 'anywhere';
    measurer.style.wordBreak = 'break-word';
    measurer.style.boxSizing = 'border-box';
    measurer.style.width = contentWidth + 'px';
    measurer.style.fontFamily = style.fontFamily;
    measurer.style.fontSize = style.fontSize;
    measurer.style.lineHeight = style.lineHeight;
    measurer.style.tabSize = style.tabSize;
    document.body.appendChild(measurer);
    const heights = String(code || '').split('\n').map(line => {
        measurer.textContent = line || ' ';
        return Math.max(parseFloat(style.lineHeight || 0), measurer.scrollHeight);
    });
    measurer.remove();
    return heights;
}

function updateAllCodeLineNumbers() {
    const ta = document.getElementById('code-source');
    const editableLines = document.getElementById('code-source-lines');
    if (ta && editableLines) {
        editableLines.innerHTML = renderCodeLineNumbers(ta.value, measureCodeLineHeights(ta.value, ta));
    }
    const readonlyPre = document.getElementById('code-source-readonly-highlight');
    const readonlyLines = document.getElementById('code-source-readonly-lines');
    if (readonlyPre && readonlyLines) {
        const code = readonlyPre.textContent || '';
        readonlyLines.innerHTML = renderCodeLineNumbers(code, measureCodeLineHeights(code, readonlyPre));
    }
}

const CFE_CODE_WIDTH_STORAGE_KEY = 'custom_factor_editor.codePaneWidthPct.v2';
let _codeLineNumberResizeListenerBound = false;

function initCodePaneResizer() {
    const body = document.getElementById('editor-body');
    const handle = body?.querySelector('.editor-resize-handle');
    if (!body || !handle) return;

    const saved = Number(localStorage.getItem(CFE_CODE_WIDTH_STORAGE_KEY));
    if (Number.isFinite(saved)) {
        setCodePaneWidth(saved);
    }

    let dragging = false;
    function onPointerMove(event) {
        if (!dragging) return;
        const rect = body.getBoundingClientRect();
        if (!rect.width) return;
        const pct = ((event.clientX - rect.left) / rect.width) * 100;
        setCodePaneWidth(pct);
    }
    function onPointerUp() {
        if (!dragging) return;
        dragging = false;
        handle.classList.remove('dragging');
        body.classList.remove('resizing');
        const current = parseFloat(body.style.getPropertyValue('--cfe-code-pane-width'));
        if (Number.isFinite(current)) {
            localStorage.setItem(CFE_CODE_WIDTH_STORAGE_KEY, String(current));
        }
        document.removeEventListener('pointermove', onPointerMove);
        document.removeEventListener('pointerup', onPointerUp);
    }

    handle.onpointerdown = function(event) {
        event.preventDefault();
        dragging = true;
        handle.classList.add('dragging');
        body.classList.add('resizing');
        document.addEventListener('pointermove', onPointerMove);
        document.addEventListener('pointerup', onPointerUp);
    };
    if (!_codeLineNumberResizeListenerBound) {
        _codeLineNumberResizeListenerBound = true;
        window.addEventListener('resize', () => requestAnimationFrame(updateAllCodeLineNumbers));
    }
}

function setCodePaneWidth(pct) {
    const body = document.getElementById('editor-body');
    if (!body) return;
    const clamped = Math.max(36, Math.min(68, Number(pct)));
    body.style.setProperty('--cfe-code-pane-width', clamped.toFixed(1) + '%');
    requestAnimationFrame(updateAllCodeLineNumbers);
}

function handleCodeEditorKeydown(event) {
    if (event.key !== 'Tab') return;
    event.preventDefault();
    const ta = event.target;
    if (event.shiftKey) {
        outdentCodeSelection(ta);
    } else {
        indentCodeSelection(ta);
    }
    handleCodeInput();
}

function indentCodeSelection(ta) {
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const value = ta.value;
    const lineStart = value.lastIndexOf('\n', start - 1) + 1;
    const selected = value.slice(lineStart, end);

    if (!selected.includes('\n') && start === end) {
        ta.setRangeText('    ', start, end, 'end');
        return;
    }

    const indented = selected.replace(/^/gm, '    ');
    ta.setRangeText(indented, lineStart, end, 'select');
    ta.selectionStart = start + 4;
    ta.selectionEnd = end + (indented.length - selected.length);
}

function outdentCodeSelection(ta) {
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const value = ta.value;
    const lineStart = value.lastIndexOf('\n', start - 1) + 1;
    const selected = value.slice(lineStart, end);
    const outdented = selected.replace(/^( {1,4}|\t)/gm, match => match === '\t' ? '' : match.slice(Math.min(4, match.length)));
    ta.setRangeText(outdented, lineStart, end, 'select');
    ta.selectionStart = Math.max(lineStart, start - Math.min(4, start - lineStart));
    ta.selectionEnd = Math.max(ta.selectionStart, end - (selected.length - outdented.length));
}

function highlightPython(code) {
    let html = escHtml(code || '');
    const protectedParts = [];
    function protect(regex, cls) {
        html = html.replace(regex, match => {
            const key = `\uE000${String.fromCharCode(0xE100 + protectedParts.length)}\uE001`;
            protectedParts.push(`<span class="${cls}">${match}</span>`);
            return key;
        });
    }
    protect(/("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')/g, 'py-string');
    protect(/#.*$/gm, 'py-comment');
    html = html
        .replace(/\b(class|def|return|from|import|as|if|elif|else|for|while|try|except|finally|with|lambda|staticmethod|None|True|False|and|or|not|in|is)\b/g, '<span class="py-keyword">$1</span>')
        .replace(/\b(FactorFamily|DataColumnParam|WindowParam|FactorFreqParam|ReturnFreqParam|ReverseParam|FactorExpr|DataColumn)\b/g, '<span class="py-builtin">$1</span>')
        .replace(/\b(\d+(?:\.\d+)?)\b/g, '<span class="py-number">$1</span>')
        .replace(/(@\w+)/g, '<span class="py-decorator">$1</span>');
    protectedParts.forEach((part, index) => {
        html = html.replace(`\uE000${String.fromCharCode(0xE100 + index)}\uE001`, part);
    });
    return html || ' ';
}

// ═══════════════════════════════════════════════════════════
// 算子/参数面板
// ═══════════════════════════════════════════════════════════
function renderOperatorPalette() {
    const categories = [
        {
            title: '📦 默认代码',
            items: [
                { label: '完整因子类', code: getDefaultFactorTemplate() },
                { label: '基础导入', code: 'from tools.factors import FactorFamily\nfrom tools.parameters import DataColumnParam, WindowParam' },
                { label: '扩展导入', code: 'from tools.factors import FactorFamily, FactorExpr\nfrom tools.factors import FactorFreqParam, ReturnFreqParam, ReverseParam\nfrom tools.parameters import DataColumnParam, WindowParam, TimeDeltaParam, FactorParam, TypeParam' },
            ]
        },
        {
            title: '🔧 参数定义模板',
            items: [
                { label: '价格 + 窗口', code: "P = DataColumnParam('P', default_value='CA')\nN = WindowParam('N', default_value='20d')" },
                { label: 'OHLC 参数', code: "O = DataColumnParam('O', default_value='OA')\nH = DataColumnParam('H', default_value='HA')\nL = DataColumnParam('L', default_value='LA')\nC = DataColumnParam('C', default_value='CA')" },
                { label: '收益步长 RF', code: "RF = WindowParam('RF', default_value='1d')" },
                { label: '长短窗口', code: "NS = WindowParam('NS', default_value='10d')\nNL = WindowParam('NL', default_value='30d')" },
                { label: '系统参数', code: "# FactorFamily 会自动追加 $F 和 $Rev；收益测试常用 $RF\n# from tools.factors import FactorFreqParam, ReturnFreqParam, ReverseParam" },
            ]
        },
        {
            title: '⏱ 时序算子',
            items: [
                { label: 'rolling_mean', code: 'res = P.rolling_mean(N)' },
                { label: 'rolling_std', code: 'res = P.rolling_std(N)' },
                { label: 'rolling_var', code: 'res = P.rolling_var(N)' },
                { label: 'rolling_min', code: 'res = P.rolling_min(N)' },
                { label: 'rolling_max', code: 'res = P.rolling_max(N)' },
                { label: 'rolling_sum', code: 'res = P.rolling_sum(N)' },
                { label: 'rolling_ema', code: 'res = P.rolling_ema(N)' },
                { label: 'rolling_corr', code: 'res = P.rolling_corr(V, N)' },
                { label: 'rolling_skew', code: 'res = P.rolling_skew(N)' },
                { label: 'rolling_argmax', code: 'res = P.rolling_argmax(N)' },
                { label: 'rolling_argmin', code: 'res = P.rolling_argmin(N)' },
                { label: 'shift / delta', code: 'ret = P.delta(RF) / P.shift(RF)' },
            ]
        },
        {
            title: '📊 截面算子',
            items: [
                { label: 'cs_rank', code: 'res = P.cs_rank()' },
                { label: 'cs_zscore', code: 'res = P.cs_zscore()' },
                { label: 'cs_spearman', code: 'res = P.cs_spearman(V)' },
            ]
        },
        {
            title: '🔗 组合/辅助',
            items: [
                { label: 'log / abs / sqrt', code: 'res = P.log().abs().sqrt()' },
                { label: 'sign / neg', code: 'res = P.sign() * P.neg()' },
                { label: '逐元素 max/min', code: 'res = H.max(C) - L.min(C)' },
                { label: '中间变量', code: "signal = res.as_intermediate('SIGNAL')" },
                { label: 'return 语句', code: 'return res' },
                { label: '收益率表达式', code: 'ret = P.delta(RF) / P.shift(RF)' },
            ]
        },
    ];

    let html = '';
    categories.forEach((cat, index) => {
        html += `<details class="operator-palette-group" ${index === 0 ? 'open' : ''}>
            <summary>${cat.title}</summary>
            <div class="operator-palette-items">`;
        cat.items.forEach(item => {
            html += `<button class="btn-palette-item" onclick="insertSnippet(\`${escAttr(item.code)}\`)"
                title="${escHtml(item.code)}">${escHtml(item.label)}</button>`;
        });
        html += `</div></details>`;
    });
    return html;
}

function getDefaultFactorTemplate() {
    return `from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MyFactor(FactorFamily):
    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        N = WindowParam('N', default_value='20d')
        signal = P.rolling_mean(N)
        return signal
`;
}

function insertTemplate(name) {
    if (name === 'factor_class') {
        const ta = document.getElementById('code-source');
        if (!ta) return;
        const tpl = getDefaultFactorTemplate();
        if (ta.value.trim() && !confirm('当前源码不为空，是否用默认代码模板覆盖？')) return;
        ta.setRangeText(tpl, 0, ta.value.length, 'end');
        _dirty = true;
        invalidateCodeValidation();
        syncPythonHighlight();
        ta.focus();
    }
}

function insertSnippet(code) {
    const ta = document.getElementById('code-source');
    if (!ta) return;
    // 在光标位置插入，或追加到末尾
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const before = ta.value.substring(0, start);
    const needsNewline = before.length > 0 && !before.endsWith('\n');
    const inserted = (needsNewline ? '\n' : '') + code;
    ta.setRangeText(inserted, start, end, 'end');
    ta.focus();
    _dirty = true;
    invalidateCodeValidation();
    syncPythonHighlight();
}

// ═══════════════════════════════════════════════════════════
// 校验 / 保存 / 取消
// ═══════════════════════════════════════════════════════════

async function validateCustomExpr(factorName, options = {}) {
    const sourceCode = document.getElementById('code-source')?.value || '';
    const btn = document.getElementById('btn-validate-custom');
    if (!btn) return;
    btn.textContent = '校验中...';
    btn.className = 'btn-validate';
    try {
        const res = await fetch('/custom-factors/api/validate', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ source_code: sourceCode, factor_name: factorName })
        });
        const data = await res.json();
        if (data.valid) {
            btn.textContent = '✓ 校验通过';
            btn.className = 'btn-validate ok';
            setValidatedFactorDraft(data, sourceCode);
            if (data.tree_repr && !options.openParamsOnSuccess) {
                showTreeReprPopup(data.factor_name || factorName, data.tree_repr);
            }
            if (options.openParamsOnSuccess) {
                openValidatedParamDrawer();
            }
            return true;
        } else {
            btn.textContent = '✗ ' + (data.error || '无效');
            btn.className = 'btn-validate err';
            invalidateCodeValidation();
            return false;
        }
    } catch(e) {
        btn.textContent = '校验失败';
        btn.className = 'btn-validate err';
        invalidateCodeValidation();
        return false;
    }
}

function showTreeReprPopup(factorName, treeRepr) {
    // 移除旧的
    const old = document.querySelector('.tree-repr-overlay');
    if (old) old.remove();
    const overlay = document.createElement('div');
    overlay.className = 'tree-repr-overlay';
    overlay.innerHTML = `<div class="tree-repr-content"><pre style="white-space:pre-wrap; font-size:13px; line-height:1.6;">${escHtml(treeRepr)}</pre><button style="margin-top:10px; padding:6px 16px;" onclick="this.closest('.tree-repr-overlay').remove()">关闭</button></div>`;
    overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);
}

async function saveFactor() {
    const chinese_name = document.getElementById('cfg-cn')?.value?.trim() || '';
    const description = document.getElementById('cfg-desc')?.value?.trim() || '';
    const category = document.getElementById('cfg-cat')?.value?.trim() || '自编';
    const source_code = document.getElementById('code-source')?.value?.trim() || '';

    if (!source_code) { showToast('请输入源码', 'error'); return; }

    const payload = { source_code, chinese_name, description, category };

    try {
        let res;
        if (_isNew || !_currentFactorFamilyId) {
            res = await fetch('/custom-factors/api/create', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
        } else {
            res = await fetch('/custom-factors/api/update/' + _currentFactorFamilyId, {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
        }
        const data = await res.json();
        if (data.success) {
            _dirty = false;
            _currentFactorFamilyId = data.factor.id;
            _isNew = false;
            showToast('保存成功', 'success');
            await loadFactorFamilyList();
            // 重新 fetch 因子数据并渲染编辑器
            const factor = data.factor;
            renderCodeEditor(factor);
        } else {
            showToast(data.error || '保存失败', 'error');
        }
    } catch(e) {
        showToast('网络错误', 'error');
    }
}

function discardEdit() {
    if (_dirty && !confirm('有未保存的修改，确定放弃？')) return;
    _currentFactorFamilyId = null;
    _isNew = false;
    _dirty = false;
    renderFactorFamilyList();
    const body = document.getElementById('editor-body');
    body.innerHTML = '<div class="editor-placeholder">← 从左侧选择因子，或点击「新建因子」</div>';
    document.getElementById('editor-footer').style.display = 'none';
    document.getElementById('editor-title').textContent = '选择一个因子开始编辑';
}

// ═══════════════════════════════════════════════════════════
// 可视化编辑器模式 — 算子面板 + 拖放画布
// ═══════════════════════════════════════════════════════════

// 算子定义
const OP_PALETTE = {
    leaf: [
        { key:'OPEN', label:'OPEN', desc:'开盘价' },
        { key:'HIGH', label:'HIGH', desc:'最高价' },
        { key:'LOW', label:'LOW', desc:'最低价' },
        { key:'CLOSE', label:'CLOSE', desc:'收盘价' },
        { key:'CLOSE_ADJUSTED', label:'CLOSE_ADJ', desc:'复权收盘价' },
        { key:'VOLUME', label:'VOLUME', desc:'成交量' },
        { key:'AMOUNT', label:'AMOUNT', desc:'成交额' },
    ],
    ts: [
        { key:'MA($X,$N)', label:'MA', desc:'移动平均 MA(X,N)' },
        { key:'STD($X,$N)', label:'STD', desc:'标准差 STD(X,N)' },
        { key:'REF($X,$N)', label:'REF', desc:'前移 REF(X,N)' },
        { key:'DELTA($X,$N)', label:'DELTA', desc:'差分 DELTA(X,N)' },
        { key:'LOG($X)', label:'LOG', desc:'对数 LOG(X)' },
        { key:'ABS($X)', label:'ABS', desc:'绝对值 ABS(X)' },
    ],
    cs: [
        { key:'CS_RANK($X)', label:'CS_RANK', desc:'横截面排名' },
        { key:'CS_ZSCORE($X)', label:'CS_ZSCORE', desc:'横截面标准化' },
    ],
    arith: [
        { key:'+', label:'+', desc:'加法' },
        { key:'-', label:'-', desc:'减法' },
        { key:'*', label:'*', desc:'乘法' },
        { key:'/', label:'/', desc:'除法' },
    ]
};

// 画布上的节点
let _visNodes = [];
let _visNextId = 1;
let _visSelectedNodeId = null;
let _visDragging = null;  // { nodeId, startX, startY, mouseX, mouseY }

function renderVisualEditor(factor) {
    _currentMode = 'visual';
    const body = document.getElementById('editor-body');
    const footer = document.getElementById('editor-footer');
    const title = document.getElementById('editor-title');
    title.textContent = _isNew ? '新建因子（可视化）' : (factor.name || '未命名因子（可视化）');
    footer.style.display = '';

    // 尝试从 func_expr 回解析出节点
    _visNodes = [];
    _visNextId = 1;
    _visSelectedNodeId = null;
    if (factor.func_expr) {
        // 简化为从头开始（回解析太复杂）
    }

    body.innerHTML = `
        <div class="visual-layout">
            <div class="op-palette" id="op-palette">
                ${renderPalette()}
            </div>
            <div class="visual-canvas-wrap" id="visual-canvas-wrap"
                 ondragover="event.preventDefault()"
                 ondrop="onCanvasDrop(event)"
                 onclick="onCanvasClick(event)">
                <div class="visual-canvas" id="visual-canvas">
                    <svg class="vis-edges" id="vis-edges"></svg>
                </div>
            </div>
            <div class="visual-config-pane">
                <div class="config-section">
                    <h3>节点属性</h3>
                    <div id="node-props" style="font-size:12px;color:#888;">点击画布上的节点查看属性</div>
                </div>
                <div class="config-section" style="margin-top:16px;">
                    <h3>基本信息</h3>
                    <div class="field">
                        <label>因子名称</label>
                        <input type="text" id="cfg-name-vis" value="${escHtml(factor.name || '')}" oninput="_dirty=true">
                    </div>
                    <div class="field">
                        <label>中文名称</label>
                        <input type="text" id="cfg-cn-vis" value="${escHtml(factor.chinese_name || '')}" oninput="_dirty=true">
                    </div>
                    <div class="field">
                        <label>分类</label>
                        <input type="text" id="cfg-cat-vis" value="${escHtml(factor.category || '自编')}" oninput="_dirty=true">
                    </div>
                </div>
                <div style="margin-top:12px;">
                    <button class="btn-validate" onclick="visualToExpr()" style="width:100%">🔄 生成表达式</button>
                </div>
                <div style="margin-top:8px;font-size:12px;color:#888;" id="visual-expr-preview"></div>
            </div>
        </div>
    `;

    // 让算子面板中的元素可拖拽
    initPaletteDrag();
}

function renderPalette() {
    const labels = { leaf:'📊 数据列', ts:'⏱ 时序算子', cs:'📐 横截面算子', arith:'➕ 算术运算' };
    let html = '';
    for (const [cat, ops] of Object.entries(OP_PALETTE)) {
        html += `<h3>${labels[cat]}</h3>`;
        for (const op of ops) {
            html += `<div class="op-block ${cat}" draggable="true"
                data-op-key="${escHtml(op.key)}" data-op-cat="${cat}"
                ondragstart="onOpDragStart(event)">
                <strong>${escHtml(op.label)}</strong>
                <div class="op-desc">${escHtml(op.desc)}</div>
            </div>`;
        }
    }
    return html;
}

function initPaletteDrag() {
    document.querySelectorAll('.op-block').forEach(el => {
        el.addEventListener('dragstart', onOpDragStart);
    });
}

function onOpDragStart(e) {
    e.dataTransfer.setData('text/plain', JSON.stringify({
        key: e.target.closest('.op-block').dataset.opKey,
        cat: e.target.closest('.op-block').dataset.opCat,
    }));
    e.dataTransfer.effectAllowed = 'copy';
}

function onCanvasDrop(e) {
    e.preventDefault();
    const raw = e.dataTransfer.getData('text/plain');
    if (!raw) return;
    const op = JSON.parse(raw);
    const wrap = document.getElementById('visual-canvas-wrap');
    const rect = wrap.getBoundingClientRect();
    const x = e.clientX - rect.left + wrap.scrollLeft - 50;
    const y = e.clientY - rect.top + wrap.scrollTop - 18;

    const node = {
        id: _visNextId++,
        key: op.key,
        cat: op.cat,
        label: op.key,
        x: Math.max(0, x),
        y: Math.max(0, y),
        params: {},
    };
    _visNodes.push(node);
    renderAllVisNodes();
    _dirty = true;
    selectVisNode(node.id);
}

function onCanvasClick(e) {
    if (e.target.closest('.vis-node')) return;
    _visSelectedNodeId = null;
    renderAllVisNodes();
    document.getElementById('node-props').innerHTML =
        '<span style="color:#888;">点击画布上的节点查看属性</span>';
    document.getElementById('visual-expr-preview').textContent = '';
}

function renderAllVisNodes() {
    const canvas = document.getElementById('visual-canvas');
    // remove old nodes
    canvas.querySelectorAll('.vis-node').forEach(n => n.remove());

    for (const node of _visNodes) {
        const el = document.createElement('div');
        el.className = 'vis-node' + (node.id === _visSelectedNodeId ? ' selected' : '');
        el.style.left = node.x + 'px';
        el.style.top = node.y + 'px';
        el.dataset.nodeId = node.id;
        el.innerHTML = `
            <button class="btn-delete-node" onclick="deleteVisNode(${node.id});event.stopPropagation()">×</button>
            <div class="node-label">${escHtml(node.label)}</div>
            <div class="node-sub">${escHtml(node.key)}</div>
        `;
        el.addEventListener('mousedown', (e) => onVisNodeMouseDown(e, node.id));
        el.addEventListener('click', (e) => { e.stopPropagation(); selectVisNode(node.id); });
        canvas.appendChild(el);
    }
}

function onVisNodeMouseDown(e, nodeId) {
    e.preventDefault();
    e.stopPropagation();
    const node = _visNodes.find(n => n.id === nodeId);
    if (!node) return;
    _visDragging = {
        nodeId,
        startX: node.x,
        startY: node.y,
        mouseX: e.clientX,
        mouseY: e.clientY,
    };
    document.addEventListener('mousemove', onVisMouseMove);
    document.addEventListener('mouseup', onVisMouseUp);
}

function onVisMouseMove(e) {
    if (!_visDragging) return;
    const node = _visNodes.find(n => n.id === _visDragging.nodeId);
    if (!node) return;
    const dx = e.clientX - _visDragging.mouseX;
    const dy = e.clientY - _visDragging.mouseY;
    node.x = Math.max(0, _visDragging.startX + dx);
    node.y = Math.max(0, _visDragging.startY + dy);
    renderAllVisNodes();
    _dirty = true;
}

function onVisMouseUp() {
    _visDragging = null;
    document.removeEventListener('mousemove', onVisMouseMove);
    document.removeEventListener('mouseup', onVisMouseUp);
}

function selectVisNode(nodeId) {
    _visSelectedNodeId = nodeId;
    renderAllVisNodes();
    const node = _visNodes.find(n => n.id === nodeId);
    if (!node) return;

    // 显示节点属性面板
    const props = document.getElementById('node-props');
    const catNames = { leaf:'数据列', ts:'时序算子', cs:'横截面算子', arith:'算术' };
    props.innerHTML = `
        <div class="field"><label>类型</label><span>${catNames[node.cat] || node.cat}</span></div>
        <div class="field"><label>算子</label><span>${escHtml(node.key)}</span></div>
        <div class="field"><label>标签</label><input type="text" id="vis-node-label" value="${escHtml(node.label)}" oninput="updateVisNodeLabel(${nodeId}, this.value)"></div>
    `;

    updateVisualExprPreview();
}

function updateVisNodeLabel(nodeId, newLabel) {
    const node = _visNodes.find(n => n.id === nodeId);
    if (node) { node.label = newLabel; renderAllVisNodes(); _dirty = true; }
}

function deleteVisNode(nodeId) {
    _visNodes = _visNodes.filter(n => n.id !== nodeId);
    if (_visSelectedNodeId === nodeId) _visSelectedNodeId = null;
    renderAllVisNodes();
    _dirty = true;
    updateVisualExprPreview();
}

// 从可视化节点生成 func_expr 字符串
function visualToExpr() {
    if (_visNodes.length === 0) {
        document.getElementById('visual-expr-preview').textContent = '（无节点）';
        return '';
    }
    // 简单串行连接：按拓扑？这里先用最后一个节点作为根
    // 实际复杂的树状连接需要连线，先做简单版：把所有节点按 key 拼接
    const root = _visNodes[_visNodes.length - 1];
    const expr = buildExprFromNode(root);
    document.getElementById('visual-expr-preview').textContent = expr || '（无法生成表达式）';
    return expr;
}

function buildExprFromNode(node) {
    return node.key;  // 简化版直接返回 key
}

function updateVisualExprPreview() {
    const expr = visualToExpr();
    document.getElementById('visual-expr-preview').textContent = expr || '';
}

// 覆盖保存：可视化模式也收集 func_expr
// saveFactor 中读取 code-expr，可视化模式需要从 _visNodes 生成
// 我们修改 saveFactor 的判断逻辑
const _origSaveFactor = saveFactor;
saveFactor = async function() {
    if (_currentMode === 'visual') {
        const expr = visualToExpr();
        // 把可视化表达式写入隐藏字段，让原来的保存逻辑拿得到
        const codeTextarea = document.getElementById('code-expr');
        if (!codeTextarea) {
            // 创建临时 textarea
            const tmp = document.createElement('textarea');
            tmp.id = 'code-expr';
            tmp.style.display = 'none';
            tmp.value = expr;
            document.getElementById('editor-body').appendChild(tmp);
        } else {
            codeTextarea.value = expr;
        }
        // 可视化模式下用 visual 表单的字段
        const nameEl = document.getElementById('cfg-name-vis');
        const cnEl = document.getElementById('cfg-cn-vis');
        const catEl = document.getElementById('cfg-cat-vis');
        if (nameEl && !document.getElementById('cfg-name')) {
            // 创建隐藏的 code 字段
            ['cfg-name','cfg-cn','cfg-cat','cfg-desc'].forEach(id => {
                const vis = document.getElementById(id + '-vis');
                if (vis && !document.getElementById(id)) {
                    const h = document.createElement('input');
                    h.type = 'hidden'; h.id = id; h.value = vis.value;
                    document.getElementById('editor-body').appendChild(h);
                }
            });
        }
    }
    return await _origSaveFactor();
};

// ═══════════════════════════════════════════════════════════
// Toast
// ═══════════════════════════════════════════════════════════

function showToast(msg, type) {
    const c = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = 'toast ' + type;
    el.textContent = msg;
    c.appendChild(el);
    setTimeout(() => el.remove(), 2000);
}

// startup
init();
