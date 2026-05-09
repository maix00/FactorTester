// ═══════════════════════════════════════════════════════════
// 可视化编辑器模式 — 算子面板 + 拖放画布
// ═══════════════════════════════════════════════════════════

// 算子定义
let _visualOperatorGroups = [];
let OP_PALETTE = {
    leaf: [
        { key: 'DataColumnParam', label: '参数', desc: '数据列/窗口/时间参数', arity: 0 },
        { key: 'Constant', label: '常数', desc: '数值常量', arity: 0 },
    ],
    ts: [
        { key: 'rolling_mean', label: '均值', desc: 'X.rolling_mean(N)', arity: 2 },
        { key: 'rolling_std', label: '标准差', desc: 'X.rolling_std(N)', arity: 2 },
        { key: 'rolling_min', label: '最小值', desc: 'X.rolling_min(N)', arity: 2 },
        { key: 'rolling_max', label: '最大值', desc: 'X.rolling_max(N)', arity: 2 },
        { key: 'shift', label: '平移', desc: 'X.shift(N)', arity: 2 },
        { key: 'delta', label: '差分', desc: 'X.delta(N)', arity: 2 },
        { key: 'log', label: '对数', desc: 'X.log()', arity: 1 },
        { key: 'abs', label: '绝对值', desc: 'X.abs()', arity: 1 },
    ],
    cs: [
        { key: 'cs_rank', label: '截面排名', desc: 'X.cs_rank()', arity: 1 },
        { key: 'cs_zscore', label: '截面标准化', desc: 'X.cs_zscore()', arity: 1 },
    ],
    arith: [
        { key: '+', label: '+', desc: 'A + B', arity: 2 },
        { key: '-', label: '-', desc: 'A - B', arity: 2 },
        { key: '*', label: '*', desc: 'A * B', arity: 2 },
        { key: '/', label: '/', desc: 'A / B', arity: 2 },
    ]
};
const VIS_FACTOR_PARAM_TYPES = ['FactorFreqParam', 'ReturnFreqParam', 'ReverseParam'];
const VIS_PARAMETER_TYPES = ['DataColumnParam', 'WindowParam', 'DateOrTimeParam', 'TimeDeltaParam', 'FactorParam', 'TypeParam'];

let _visNodes = [];
let _visNextId = 1;
let _visSelectedNodeId = null;
let _visDragging = null;
let _visSourceFallback = '';
let _visGraphDirty = false;
let _visPendingConnection = null;
let _visLastGeneratedSource = '';

async function loadVisualOperatorRegistry() {
    try {
        const res = await fetch('/custom-factors/api/visual-operators');
        const data = await res.json();
        if (data.success && Array.isArray(data.groups)) {
            _visualOperatorGroups = data.groups;
            OP_PALETTE = Object.fromEntries(
                data.groups.map(group => [group.key, [
                    ...(Array.isArray(group.operators) ? group.operators : []),
                    ...(Array.isArray(group.more_operators) ? group.more_operators : []),
                ]])
            );
        }
    } catch(e) {
        _visualOperatorGroups = [];
    }
}

function renderVisualEditor(factor) {
    const previousMode = _currentMode;
    _currentMode = 'visual';
    const body = document.getElementById('editor-body');
    const footer = document.getElementById('editor-footer');
    const title = document.getElementById('editor-title');
    title.textContent = _isNew ? '新建因子（可视化）' : (factor.name || '未命名因子（可视化）');
    setEditorModeTabsVisible(true);
    setActiveEditorModeTab('visual');
    footer.style.display = '';
    _visSourceFallback = factor.source_code || '';
    const shouldParseSource = !_visNodes.length
        || (previousMode === 'code' && _visSourceFallback !== _visLastGeneratedSource)
        || (!_visGraphDirty && _visSourceFallback !== (renderVisualEditor._lastSource || ''));
    if (shouldParseSource) {
        _visGraphDirty = false;
        loadVisualNodesFromSource(_visSourceFallback);
        renderVisualEditor._lastSource = _visSourceFallback;
    }

    body.innerHTML = `
        <div class="visual-layout">
            <div class="op-palette" id="op-palette">${renderPalette()}</div>
            <div class="visual-canvas-wrap" id="visual-canvas-wrap"
                 ondragover="event.preventDefault()" ondrop="onCanvasDrop(event)" onclick="onCanvasClick(event)">
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
                    <button class="btn-validate" id="btn-validate-custom" onclick="validateCustomExpr('${escAttr(factor.name || factor.id || '')}')"
                        style="width:100%; padding:8px; font-size:13px;">校验表达式树</button>
                    <button class="btn-validate" id="btn-param-config" onclick="openOrValidateParamDrawer('${escAttr(factor.name || factor.id || '')}')"
                        style="width:100%; padding:8px; font-size:13px; margin-top:8px;">校验后配置参数</button>
                    <div id="param-config-status" style="font-size:12px;color:#999;margin-top:6px;">请先校验表达式树</div>
                </div>
                <div class="config-section" style="margin-top:16px;">
                    <h3>基本信息</h3>
                    <div class="field"><label>类名</label><input type="text" id="cfg-name-vis" value="${escHtml(factor.name || '')}" placeholder="如 MyFactor" oninput="_dirty=true;_visGraphDirty=true"></div>
                    <div class="field"><label>中文名称</label><input type="text" id="cfg-cn-vis" value="${escHtml(factor.chinese_name || '')}" oninput="_dirty=true"></div>
                    <div class="field"><label>分类</label><input type="text" id="cfg-cat-vis" value="${escHtml(factor.category || '自编')}" oninput="_dirty=true"></div>
                    <div class="field"><label>描述 (Markdown)</label><textarea id="cfg-desc-vis" oninput="_dirty=true">${escHtml(factor.description || '')}</textarea></div>
                </div>
                <div style="margin-top:12px;">
                    <button class="btn-validate" onclick="visualToExpr()" style="width:100%">生成表达式</button>
                    <button class="btn-validate" onclick="autoLayoutVisualNodes()" style="width:100%; margin-top:8px;">自动整理</button>
                </div>
                <div style="margin-top:8px;font-size:12px;color:#888;" id="visual-expr-preview"></div>
                <div style="margin-top:8px;font-size:12px;color:#888;" id="visual-connect-hint">点击卡牌右侧端口，再点击目标卡牌的输入槽完成连接。</div>
            </div>
        </div>
    `;

    initPaletteDrag();
    layoutVisualExpressionTree();
    renderAllVisNodes();
    requestAnimationFrame(() => {
        layoutVisualExpressionTree({measure: true});
        renderAllVisNodes();
        updateVisualExprPreview();
    });
    invalidateCodeValidation();
}

function renderPalette() {
    const fallbackLabels = { leaf: '参数/常数', ts: '时序算子', cs: '横截面算子', arith: '算术运算' };
    const groups = getVisualOperatorGroupsForRender();
    let html = '';
    for (const group of groups) {
        const cat = group.key;
        const ops = group.operators || [];
        html += `<details class="visual-op-group" ${group.collapsed ? '' : 'open'}>
            <summary>${escHtml(group.label || fallbackLabels[cat] || cat)}</summary>`;
        html += renderVisualOperatorBlocks(cat, ops);
        if (Array.isArray(group.more_operators) && group.more_operators.length) {
            html += `<details class="visual-op-more">
                <summary>${escHtml(group.more_label || '更多')}</summary>
                ${renderVisualOperatorBlocks(cat, group.more_operators)}
            </details>`;
        }
        html += '</details>';
    }
    return html;
}

function renderVisualOperatorBlocks(cat, ops) {
    return (ops || []).map(op => `<div class="op-block ${cat}" draggable="true"
        data-op-key="${escHtml(op.key)}" data-op-cat="${escHtml(cat)}" ondragstart="onOpDragStart(event)">
        <strong>${escHtml(op.label)}</strong><div class="op-desc">${escHtml(op.desc)}</div>
    </div>`).join('');
}

function getVisualOperatorGroupsForRender() {
    if (_visualOperatorGroups.length) return _visualOperatorGroups;
    return Object.entries(OP_PALETTE).map(([key, operators]) => ({
        key,
        label: key,
        collapsed: false,
        operators,
    }));
}

function initPaletteDrag() {
    document.querySelectorAll('.op-block').forEach(el => el.addEventListener('dragstart', onOpDragStart));
}

function onOpDragStart(e) {
    const block = e.target.closest('.op-block');
    e.dataTransfer.setData('text/plain', JSON.stringify({ key: block.dataset.opKey, cat: block.dataset.opCat }));
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
    const params = defaultVisualNodeParams(op);
    const node = {
        id: _visNextId++,
        key: op.key,
        cat: op.cat,
        label: params.alias || params.name || op.key,
        x: Math.max(0, x),
        y: Math.max(0, y),
        inputs: [],
        params,
    };
    _visNodes.push(node);
    _dirty = true;
    _visGraphDirty = true;
    invalidateCodeValidation();
    renderAllVisNodes();
    selectVisNode(node.id);
}

function onCanvasClick(e) {
    if (e.target.closest('.vis-node')) return;
    _visPendingConnection = null;
    _visSelectedNodeId = null;
    renderAllVisNodes();
    document.getElementById('node-props').innerHTML = '<span style="color:#888;">点击画布上的节点查看属性</span>';
    document.getElementById('visual-expr-preview').textContent = '';
    const hint = document.getElementById('visual-connect-hint');
    if (hint) hint.textContent = '点击卡牌右侧端口，再点击目标卡牌的输入槽完成连接。';
}

function renderAllVisNodes() {
    const canvas = document.getElementById('visual-canvas');
    const svg = document.getElementById('vis-edges');
    if (!canvas) return;
    canvas.querySelectorAll('.vis-node').forEach(n => n.remove());
    canvas.querySelectorAll('.vis-edge-delete').forEach(n => n.remove());
    for (const node of _visNodes) {
        const el = document.createElement('div');
        el.className = 'vis-node' + (node.id === _visSelectedNodeId ? ' selected' : '');
        el.style.left = node.x + 'px';
        el.style.top = node.y + 'px';
        el.dataset.nodeId = node.id;
        el.innerHTML = `
            <button class="btn-delete-node" onclick="deleteVisNode(${node.id});event.stopPropagation()">×</button>
            <div class="node-card-head">
                <div class="node-label">${escHtml(node.label)}</div>
                <div class="node-sub">${escHtml(getVisualNodeSubtitle(node))}</div>
            </div>
            ${node.params?.intermediate_name ? `<div class="node-intermediate-badge">中间因子 ${escHtml(node.params.intermediate_name)}</div>` : ''}
            ${renderVisualNodeSlots(node)}
            <button class="node-output-port" title="点击后选择目标输入槽" onclick="startVisualConnection(${node.id});event.stopPropagation()"></button>
        `;
        el.addEventListener('mousedown', (event) => onVisNodeMouseDown(event, node.id));
        el.addEventListener('click', (event) => { event.stopPropagation(); selectVisNode(node.id); });
        canvas.appendChild(el);
    }
    if (svg) renderVisEdges(svg);
}

function onVisNodeMouseDown(e, nodeId) {
    if (e.target.closest('button') || e.target.closest('.node-slot')) return;
    e.preventDefault();
    e.stopPropagation();
    const node = _visNodes.find(n => n.id === nodeId);
    if (!node) return;
    _visDragging = { nodeId, startX: node.x, startY: node.y, mouseX: e.clientX, mouseY: e.clientY };
    document.addEventListener('mousemove', onVisMouseMove);
    document.addEventListener('mouseup', onVisMouseUp);
}

function onVisMouseMove(e) {
    if (!_visDragging) return;
    const node = _visNodes.find(n => n.id === _visDragging.nodeId);
    if (!node) return;
    node.x = Math.max(0, _visDragging.startX + e.clientX - _visDragging.mouseX);
    node.y = Math.max(0, _visDragging.startY + e.clientY - _visDragging.mouseY);
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
    const props = document.getElementById('node-props');
    const catNames = {
        leaf: '参数/常数',
        ts: '时序算子',
        cs: '横截算子',
        arith: '算术',
        arithUnary: '算数一元',
        arithBinary: '算数二元',
        arithVariadic: '算数多元',
        arithTernary: '算数三元',
    };
    const labelEditor = node.key === 'DataColumnParam' || node.key === 'Constant'
        ? ''
        : `<div class="field"><label>标签</label><input type="text" value="${escHtml(node.label)}" oninput="updateVisNodeLabel(${nodeId}, this.value)"></div>`;
    props.innerHTML = `
        <div class="field"><label>类型</label><span>${catNames[node.cat] || node.cat}</span></div>
        <div class="field"><label>算子</label><span>${escHtml(node.key)}</span></div>
        ${labelEditor}
        ${renderVisualNodeParamControls(node)}
        ${renderVisualInputSelectors(node)}
    `;
    updateVisualExprPreview();
}

function updateVisNodeLabel(nodeId, newLabel) {
    const node = _visNodes.find(n => n.id === nodeId);
    if (!node) return;
    node.label = newLabel;
    if (node.key === 'DataColumnParam') node.params.alias = newLabel;
    if (node.key === 'Constant') node.params.name = newLabel;
    renderAllVisNodes();
    updateVisualExprPreview();
    _dirty = true;
    _visGraphDirty = true;
}

function startVisualConnection(fromNodeId) {
    const from = _visNodes.find(n => n.id === fromNodeId);
    if (!from) return;
    _visPendingConnection = {fromNodeId};
    const hint = document.getElementById('visual-connect-hint');
    if (hint) hint.textContent = `正在连接 ${from.label}：点击目标卡牌的输入槽。`;
    renderAllVisNodes();
}

function completeVisualConnection(toNodeId, inputIndex) {
    if (!_visPendingConnection) return;
    const fromNodeId = _visPendingConnection.fromNodeId;
    if (fromNodeId === toNodeId) {
        showToast('不能连接到自身', 'error');
        return;
    }
    if (wouldCreateVisualCycle(fromNodeId, toNodeId)) {
        showToast('该连接会形成环，已取消', 'error');
        _visPendingConnection = null;
        renderAllVisNodes();
        return;
    }
    const target = _visNodes.find(n => n.id === toNodeId);
    if (!target) return;
    target.inputs = target.inputs || [];
    target.inputs[inputIndex] = fromNodeId;
    _visPendingConnection = null;
    _dirty = true;
    _visGraphDirty = true;
    invalidateCodeValidation();
    renderAllVisNodes();
    selectVisNode(toNodeId);
    updateVisualExprPreview();
    const hint = document.getElementById('visual-connect-hint');
    if (hint) hint.textContent = '点击卡牌右侧端口，再点击目标卡牌的输入槽完成连接。';
}

function wouldCreateVisualCycle(fromNodeId, toNodeId) {
    const stack = [fromNodeId];
    const seen = new Set();
    while (stack.length) {
        const id = stack.pop();
        if (id === toNodeId) return true;
        if (seen.has(id)) continue;
        seen.add(id);
        const node = _visNodes.find(n => n.id === id);
        (node?.inputs || []).forEach(childId => stack.push(childId));
    }
    return false;
}

function deleteVisNode(nodeId) {
    _visNodes = _visNodes.filter(n => n.id !== nodeId);
    _visNodes.forEach(node => {
        node.inputs = (node.inputs || []).map(id => id === nodeId ? null : id);
    });
    if (_visSelectedNodeId === nodeId) _visSelectedNodeId = null;
    if (_visPendingConnection?.fromNodeId === nodeId) _visPendingConnection = null;
    renderAllVisNodes();
    _dirty = true;
    _visGraphDirty = true;
    updateVisualExprPreview();
}

function visualToExpr() {
    if (_visNodes.length === 0) {
        document.getElementById('visual-expr-preview').textContent = '（无节点）';
        return '';
    }
    const root = getVisualRootNode();
    const expr = root ? buildExprFromNode(root, new Set(), {root: true}) : '';
    document.getElementById('visual-expr-preview').textContent = expr || '（无法生成表达式）';
    return expr;
}

function buildExprFromNode(node, seen, options = {}) {
    if (!node || seen.has(node.id)) return '';
    seen.add(node.id);
    if (node.key === 'DataColumnParam') return node.params?.alias || node.label || 'P';
    if (node.key === 'Constant') {
        const name = (node.params?.name || '').trim();
        const value = normalizeVisualConstValue(node.params?.value);
        if (name) return options.root ? `ConstExpr(${name})` : name;
        return options.root ? `ConstExpr(${value})` : value;
    }
    const arity = getVisualOperatorArity(node);
    const inputIds = (node.inputs || []).slice(0, arity);
    if (arity && (inputIds.length < arity || inputIds.some(id => !id))) return '';
    const inputs = inputIds.map(id => _visNodes.find(n => n.id === id));
    const exprs = inputs.map(child => buildExprFromNode(child, new Set(seen)));
    if (exprs.some(expr => !expr)) return '';
    let expr = '';
    if (isVisualInfixOperator(node)) {
        expr = exprs.length >= getVisualOperatorArity(node) ? `(${exprs[0]} ${node.key} ${exprs[1]})` : '';
    } else if (node.key === '~') {
        expr = exprs.length >= 1 ? `(~${exprs[0]})` : '';
    } else if (node.key === 'expr_max' || node.key === 'expr_min') {
        expr = exprs.length >= getVisualOperatorArity(node) ? `${node.key}(${exprs.join(', ')})` : '';
    } else if (node.key === 'max' || node.key === 'min') {
        expr = exprs.length >= 2 ? `${exprs[0]}.${node.key}(${exprs[1]})` : '';
    } else if (node.key === 'rolling_corr') {
        expr = exprs.length >= 3 ? `${exprs[0]}.rolling_corr(${exprs[1]}, ${exprs[2]})` : '';
    } else {
        if (!exprs.length) return '';
        const rest = exprs.slice(1).join(', ');
        expr = `${exprs[0]}.${node.key}(${rest})`;
    }
    const intermediateName = node.params?.intermediate_name || '';
    if (expr && intermediateName) return `(${expr}).as_intermediate(${JSON.stringify(intermediateName)})`;
    return expr;
}

function updateVisualExprPreview() {
    const preview = document.getElementById('visual-expr-preview');
    if (!preview) return;
    preview.textContent = visualToExpr() || '';
}

function defaultVisualNodeParams(op) {
    if (op.key === 'DataColumnParam') return { alias: nextVisualParamAlias(), type: 'DataColumnParam', default_value: 'CA' };
    if (op.key === 'Constant') return { name: '', value: '1' };
    return {};
}

function nextVisualParamAlias(base = 'P') {
    const used = new Set(_visNodes
        .filter(n => n.key === 'DataColumnParam')
        .map(n => n.params?.alias || n.label)
        .filter(Boolean));
    if (!used.has(base)) return base;
    for (let i = 2; i < 1000; i++) {
        const candidate = `${base}${i}`;
        if (!used.has(candidate)) return candidate;
    }
    return `${base}${Date.now()}`;
}

function normalizeVisualConstValue(value) {
    const text = String(value ?? '').trim();
    return text || '1';
}

function getVisualNodeSubtitle(node) {
    if (node.key === 'DataColumnParam') return `${node.params?.type || 'DataColumnParam'}=${node.params?.default_value || ''}`;
    if (node.key === 'Constant') return node.params?.name ? `${node.params.name}=${node.params?.value ?? ''}` : (node.params?.value ?? '');
    return `${(node.inputs || []).length}/${getVisualOperatorArity(node)} 输入`;
}

function renderVisualNodeSlots(node) {
    const labels = getVisualSlotLabels(node);
    if (!labels.length) return '';
    const rows = labels.map((label, index) => {
        const inputNode = _visNodes.find(n => n.id === (node.inputs || [])[index]);
        const awaiting = _visPendingConnection && _visPendingConnection.fromNodeId !== node.id;
        return `<div class="node-slot ${inputNode ? 'filled' : ''} ${awaiting ? 'awaiting' : ''}"
            onclick="completeVisualConnection(${node.id}, ${index});event.stopPropagation()"
            title="${awaiting ? '点击连接到此输入槽' : '先点击另一个卡牌的输出端口'}">
            <span class="node-input-port" aria-hidden="true"></span>
            <span class="node-slot-name">${escHtml(label)}</span>
            <span class="node-slot-value">${escHtml(inputNode ? inputNode.label : '未连接')}</span>
            ${inputNode ? `<button class="node-disconnect" title="取消连接" onclick="disconnectVisualInput(${node.id}, ${index});event.stopPropagation()">×</button>` : ''}
        </div>`;
    }).join('');
    return `<div class="node-slots">${rows}</div>`;
}

function getVisualSlotLabels(node) {
    return getVisualOperatorDef(node)?.slots || [];
}

function getVisualOperatorArity(node) {
    return getVisualOperatorDef(node)?.arity || 0;
}

function getVisualOperatorDef(node) {
    return Object.entries(OP_PALETTE).flatMap(([cat, ops]) => ops.map(op => ({...op, cat})))
        .find(op => op.key === node.key && op.cat === node.cat)
        || Object.entries(OP_PALETTE).flatMap(([cat, ops]) => ops.map(op => ({...op, cat})))
            .find(op => op.key === node.key)
        || null;
}

function isVisualInfixOperator(node) {
    return getVisualOperatorDef(node)?.syntax === 'infix';
}

function renderVisualInputSelectors(node) {
    const arity = getVisualOperatorArity(node);
    if (!arity) return '';
    const labels = getVisualSlotLabels(node);
    let html = '<div class="field"><label>输入连接</label>';
    for (let i = 0; i < arity; i++) {
        const current = (node.inputs || [])[i] || '';
        html += `<select onchange="updateVisualNodeInput(${node.id}, ${i}, this.value)">
            <option value="">选择${labels[i] || `输入 ${i + 1}`}</option>
            ${_visNodes.filter(n => n.id !== node.id).map(n => `
                <option value="${n.id}" ${String(current) === String(n.id) ? 'selected' : ''}>${escHtml(n.label)} #${n.id}</option>
            `).join('')}
        </select>`;
    }
    return html + '</div>';
}

function renderVisualNodeParamControls(node) {
    const intermediateControls = node.cat !== 'leaf' ? `
        <div class="field"><label>中间因子标记</label>
            <input value="${escHtml(node.params?.intermediate_name || '')}" placeholder="如 SIG_YZ，不填则不标记"
                oninput="updateVisualParam(${node.id}, 'intermediate_name', this.value)">
        </div>
    ` : '';
    if (node.key === 'DataColumnParam') {
        return `
            <div class="field"><label>参数别名/标签</label><input value="${escHtml(node.params?.alias || node.label || 'P')}" oninput="updateVisualParam(${node.id}, 'alias', this.value)"></div>
            <div class="field"><label>参数类型</label>
                <select onchange="updateVisualParam(${node.id}, 'type', this.value)">
                    ${[...VIS_PARAMETER_TYPES, ...VIS_FACTOR_PARAM_TYPES].map(t => `<option value="${t}" ${node.params?.type === t ? 'selected' : ''}>${t}</option>`).join('')}
                </select>
            </div>
            <div class="field"><label>默认值</label><input value="${escHtml(node.params?.default_value || '')}" oninput="updateVisualParam(${node.id}, 'default_value', this.value)"></div>
        `;
    }
    if (node.key === 'Constant') {
        return `
            <div class="field"><label>常数名称（可空）</label><input value="${escHtml(node.params?.name || '')}" placeholder="如 N，不填则直接内联数值" oninput="updateVisualParam(${node.id}, 'name', this.value)"></div>
            <div class="field"><label>常数值</label><input value="${escHtml(normalizeVisualConstValue(node.params?.value))}" oninput="updateVisualParam(${node.id}, 'value', this.value)"></div>
        `;
    }
    return intermediateControls;
}

function updateVisualNodeInput(nodeId, index, value) {
    const node = _visNodes.find(n => n.id === nodeId);
    if (!node) return;
    node.inputs = node.inputs || [];
    node.inputs[index] = value ? Number(value) : null;
    _dirty = true;
    _visGraphDirty = true;
    invalidateCodeValidation();
    renderAllVisNodes();
    selectVisNode(nodeId);
}

function disconnectVisualInput(nodeId, index) {
    const node = _visNodes.find(n => n.id === nodeId);
    if (!node) return;
    node.inputs = node.inputs || [];
    node.inputs[index] = null;
    _dirty = true;
    _visGraphDirty = true;
    invalidateCodeValidation();
    renderAllVisNodes();
    selectVisNode(nodeId);
    updateVisualExprPreview();
}

function autoLayoutVisualNodes() {
    layoutVisualExpressionTree({measure: true});
    renderAllVisNodes();
    requestAnimationFrame(() => {
        layoutVisualExpressionTree({measure: true});
        renderAllVisNodes();
        updateVisualExprPreview();
    });
}

function updateVisualParam(nodeId, key, value) {
    const node = _visNodes.find(n => n.id === nodeId);
    if (!node) return;
    node.params = node.params || {};
    node.params[key] = value;
    if (key === 'alias' || key === 'name') node.label = value || (node.key === 'Constant' ? 'Constant' : node.label);
    if (key === 'intermediate_name' && value) node.label = value;
    _dirty = true;
    _visGraphDirty = true;
    invalidateCodeValidation();
    renderAllVisNodes();
    updateVisualExprPreview();
}

function getVisualRootNode() {
    const referenced = new Set(_visNodes.flatMap(node => (node.inputs || []).filter(Boolean)));
    const roots = [..._visNodes].filter(node => !referenced.has(node.id));
    const completeExpressionRoots = roots.filter(node => getVisualOperatorArity(node) > 0 && isVisualNodeComplete(node.id, new Set()));
    if (completeExpressionRoots.length) return completeExpressionRoots[completeExpressionRoots.length - 1];
    const expressionRoots = roots.filter(node => getVisualOperatorArity(node) > 0);
    if (expressionRoots.length) return expressionRoots[expressionRoots.length - 1];
    return roots[roots.length - 1] || _visNodes[_visNodes.length - 1];
}

function isVisualNodeComplete(nodeId, seen) {
    if (seen.has(nodeId)) return false;
    seen.add(nodeId);
    const node = _visNodes.find(n => n.id === nodeId);
    if (!node) return false;
    const arity = getVisualOperatorArity(node);
    if (!arity) return true;
    const inputIds = (node.inputs || []).slice(0, arity);
    if (inputIds.length < arity || inputIds.some(id => !id)) return false;
    return inputIds.every(id => isVisualNodeComplete(id, new Set(seen)));
}

function renderVisEdges(svg) {
    svg.innerHTML = '';
    const canvas = document.getElementById('visual-canvas');
    canvas?.querySelectorAll('.vis-edge-delete').forEach(n => n.remove());
    for (const node of _visNodes) {
        for (const [index, inputId] of (node.inputs || []).entries()) {
            const from = _visNodes.find(n => n.id === inputId);
            if (!from) continue;
            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            const fromPoint = getVisualOutputPoint(from.id);
            const toPoint = getVisualInputPoint(node.id, index);
            const x1 = fromPoint.x;
            const y1 = fromPoint.y;
            const x2 = toPoint.x;
            const y2 = toPoint.y;
            const mid = (x1 + x2) / 2;
            path.setAttribute('d', `M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`);
            path.setAttribute('stroke', '#94a3b8');
            path.setAttribute('stroke-width', '2');
            path.setAttribute('fill', 'none');
            svg.appendChild(path);
            if (canvas) {
                const btn = document.createElement('button');
                btn.className = 'vis-edge-delete';
                btn.type = 'button';
                btn.textContent = '×';
                btn.title = '取消这条连接';
                btn.style.left = `${mid - 8}px`;
                btn.style.top = `${((y1 + y2) / 2) - 8}px`;
                btn.onclick = (event) => {
                    event.stopPropagation();
                    disconnectVisualInput(node.id, index);
                };
                canvas.appendChild(btn);
            }
        }
    }
}

function getVisualOutputPoint(nodeId) {
    const canvas = document.getElementById('visual-canvas');
    const port = document.querySelector(`.vis-node[data-node-id="${nodeId}"] .node-output-port`);
    if (canvas && port) {
        const canvasRect = canvas.getBoundingClientRect();
        const rect = port.getBoundingClientRect();
        return {
            x: rect.left - canvasRect.left + rect.width / 2,
            y: rect.top - canvasRect.top + rect.height / 2,
        };
    }
    const node = _visNodes.find(n => n.id === nodeId);
    return {x: (node?.x || 0) + 150, y: (node?.y || 0) + 36};
}

function getVisualInputPoint(nodeId, inputIndex) {
    const canvas = document.getElementById('visual-canvas');
    const slot = document.querySelector(`.vis-node[data-node-id="${nodeId}"] .node-slot:nth-child(${inputIndex + 1}) .node-input-port`);
    if (canvas && slot) {
        const canvasRect = canvas.getBoundingClientRect();
        const rect = slot.getBoundingClientRect();
        return {
            x: rect.left - canvasRect.left + rect.width / 2,
            y: rect.top - canvasRect.top + rect.height / 2,
        };
    }
    const node = _visNodes.find(n => n.id === nodeId);
    return {x: node?.x || 0, y: (node?.y || 0) + 54 + inputIndex * 30};
}

function layoutVisualExpressionTree(options = {}) {
    if (!_visNodes.length) return;
    const root = getVisualRootNode();
    if (!root) return;
    const roots = [root, ..._visNodes.filter(node => node.id !== root.id && !isReachableFromRoot(node.id, root.id))];
    const state = { nextY: 64, maxX: 0, maxY: 0 };
    roots.forEach((node, index) => {
        if (index > 0) state.nextY += 60;
        state.totalDepth = getVisualTreeDepth(node.id, new Set());
        layoutVisualSubtree(node.id, 0, state, new Set(), options);
    });
    const canvas = document.getElementById('visual-canvas');
    if (canvas) {
        canvas.style.width = Math.max(1200, state.maxX + 360) + 'px';
        canvas.style.height = Math.max(900, state.maxY + 220) + 'px';
    }
}

function layoutVisualSubtree(nodeId, depth, state, path, options) {
    const node = _visNodes.find(n => n.id === nodeId);
    if (!node || path.has(nodeId)) return { top: state.nextY, bottom: state.nextY + estimateVisualNodeSize(node, options).height };
    path.add(nodeId);
    const size = estimateVisualNodeSize(node, options);
    const childIds = (node.inputs || []).filter(Boolean);
    const childBoxes = childIds.map(id => layoutVisualSubtree(id, depth + 1, state, new Set(path), options));

    let centerY;
    if (childBoxes.length) {
        centerY = (childBoxes[0].top + childBoxes[childBoxes.length - 1].bottom) / 2;
    } else {
        centerY = state.nextY + size.height / 2;
        state.nextY += size.height + 34;
    }

    node.x = 70 + Math.max(0, (state.totalDepth || 0) - depth) * 270;
    node.y = Math.max(30, centerY - size.height / 2);
    state.maxX = Math.max(state.maxX, node.x + size.width);
    state.maxY = Math.max(state.maxY, node.y + size.height);
    path.delete(nodeId);
    return {
        top: Math.min(node.y, ...childBoxes.map(box => box.top)),
        bottom: Math.max(node.y + size.height, ...childBoxes.map(box => box.bottom)),
    };
}

function estimateVisualNodeSize(node, options = {}) {
    if (options.measure) {
        const el = document.querySelector(`.vis-node[data-node-id="${node.id}"]`);
        if (el) {
            const rect = el.getBoundingClientRect();
            if (rect.width && rect.height) return {width: rect.width, height: rect.height};
        }
    }
    const slots = getVisualSlotLabels(node).length;
    const hasIntermediate = !!node.params?.intermediate_name;
    return {
        width: 190,
        height: 72 + slots * 30 + (hasIntermediate ? 26 : 0),
    };
}

function getVisualTreeDepth(nodeId, seen) {
    if (seen.has(nodeId)) return 0;
    seen.add(nodeId);
    const node = _visNodes.find(n => n.id === nodeId);
    if (!node || !(node.inputs || []).length) return 0;
    return 1 + Math.max(...node.inputs.map(id => getVisualTreeDepth(id, new Set(seen))));
}

function isReachableFromRoot(targetId, rootId) {
    const stack = [rootId];
    const seen = new Set();
    while (stack.length) {
        const id = stack.pop();
        if (id === targetId) return true;
        if (seen.has(id)) continue;
        seen.add(id);
        const node = _visNodes.find(n => n.id === id);
        (node?.inputs || []).forEach(childId => stack.push(childId));
    }
    return false;
}

function visualToSource(options = {}) {
    if (_currentMode !== 'visual') return document.getElementById('code-source')?.value || '';
    if (!_visGraphDirty && _visSourceFallback.trim()) return _visSourceFallback;
    const expr = visualToExpr();
    if (!expr) {
        if (!options.silent) showToast('请先完成可视化表达式连接', 'error');
        return '';
    }
    const className = document.getElementById('cfg-name-vis')?.value?.trim() || extractClassNameFromSource(_visSourceFallback) || 'MyFactor';
    const paramNodes = _visNodes.filter(n => n.key === 'DataColumnParam');
    const paramTypes = [...new Set(paramNodes.map(n => n.params?.type || 'DataColumnParam'))];
    const factorParamTypes = paramTypes.filter(t => VIS_FACTOR_PARAM_TYPES.includes(t));
    const regularParamTypes = paramTypes.filter(t => !VIS_FACTOR_PARAM_TYPES.includes(t));
    const factorImports = ['FactorFamily', ...factorParamTypes];
    if (expr.includes('ConstExpr(')) factorImports.push('ConstExpr');
    if (expr.includes('expr_max(')) factorImports.push('expr_max');
    if (expr.includes('expr_min(')) factorImports.push('expr_min');
    const imports = [
        `from tools.factors import ${[...new Set(factorImports)].join(', ')}`,
        regularParamTypes.length ? `from tools.parameters import ${regularParamTypes.join(', ')}` : '',
    ].filter(Boolean).join('\n');
    const uniqueParamNodes = [];
    const seenParamAliases = new Set();
    paramNodes.forEach(n => {
        const alias = n.params?.alias || n.label || 'P';
        if (seenParamAliases.has(alias)) return;
        seenParamAliases.add(alias);
        uniqueParamNodes.push(n);
    });
    const paramLines = uniqueParamNodes.map(n => {
        const alias = n.params?.alias || n.label || 'P';
        const type = n.params?.type || 'DataColumnParam';
        const dv = n.params?.default_value || '';
        return `        ${alias} = ${type}('${alias}', default_value=${JSON.stringify(dv)})`;
    }).join('\n');
    const constLines = getNamedVisualConstNodes().map(n => {
        const name = n.params?.name?.trim();
        return `        ${name} = ${normalizeVisualConstValue(n.params?.value)}`;
    }).join('\n');
    const setupLines = [paramLines, constLines].filter(Boolean).join('\n');
    const setupBlock = setupLines ? `${setupLines}\n` : '';
    const source = `${imports}\n\n\nclass ${className}(FactorFamily):\n    @staticmethod\n    def factor_expr():\n${setupBlock}        return ${expr}\n`;
    _visLastGeneratedSource = source;
    _visSourceFallback = source;
    return source;
}

function getNamedVisualConstNodes() {
    const seen = new Set();
    const nodes = [];
    _visNodes.filter(n => n.key === 'Constant').forEach(n => {
        const name = n.params?.name?.trim();
        if (!name || seen.has(name)) return;
        seen.add(name);
        nodes.push(n);
    });
    return nodes;
}

function loadVisualNodesFromSource(source) {
    _visNodes = [];
    _visNextId = 1;
    _visSelectedNodeId = null;
    const params = parseParamNodesFromSource(source);
    const nodeByAlias = new Map();
    params.forEach((param, index) => {
        nodeByAlias.set(param.alias, param);
    });
    if (!_visNodes.length) {
        nodeByAlias.set('P', { alias: 'P', type: 'DataColumnParam', default_value: 'CA' });
    }
    const returnExpr = parseReturnExprFromSource(source);
    const assignments = parseAssignmentsFromSource(source);
    if (returnExpr) {
        buildVisualGraphFromExpression(returnExpr, assignments, nodeByAlias);
    } else {
        for (const param of nodeByAlias.values()) {
            addVisualNodeFromParsed('DataColumnParam', 'leaf', param.alias, 0, 0, [], {...param});
        }
    }
}

function parseParamNodesFromSource(source) {
    const params = [];
    const regex = /^\s*(\w+)\s*=\s*(\w+Param)\(\s*['"]([^'"]+)['"]\s*,\s*default_value\s*=\s*([^)\n]+)\)/gm;
    let match;
    while ((match = regex.exec(source || '')) !== null) {
        params.push({
            alias: match[1] || match[3],
            type: match[2],
            default_value: String(match[4] || '').trim().replace(/^['"]|['"]$/g, ''),
        });
    }
    return params;
}

function parseReturnExprFromSource(source) {
    const match = String(source || '').match(/^\s*return\s+(.+)$/m);
    return match ? match[1].trim() : '';
}

function parseAssignmentsFromSource(source) {
    const assignments = new Map();
    const regex = /^\s*(\w+)\s*=\s*(.+)$/gm;
    let match;
    while ((match = regex.exec(source || '')) !== null) {
        if (/Param\s*\(/.test(match[2])) continue;
        assignments.set(match[1], match[2].trim());
    }
    return assignments;
}

function buildVisualGraphFromExpression(expr, assignments, nodeByAlias, x = 0, y = 0, labelHint = '') {
    const trimmed = stripOuterParens(String(expr || '').trim());
    if (!trimmed) return null;
    if (nodeByAlias.has(trimmed)) {
        const param = nodeByAlias.get(trimmed);
        return addVisualNodeFromParsed('DataColumnParam', 'leaf', param.alias, 0, 0, [], {...param});
    }
    if (assignments.has(trimmed)) {
        const assigned = assignments.get(trimmed);
        if (/^-?\d+(\.\d+)?([eE][+-]?\d+)?$/.test(stripOuterParens(assigned))) {
            return addVisualNodeFromParsed('Constant', 'leaf', trimmed, x, y, [], { name: trimmed, value: stripOuterParens(assigned) });
        }
        return buildVisualGraphFromExpression(assigned, assignments, nodeByAlias, x, y, trimmed);
    }
    const constExpr = trimmed.match(/^ConstExpr\((.*)\)$/);
    if (constExpr) {
        const args = splitTopLevelArgs(constExpr[1]);
        const value = args[0] || '1';
        return addVisualNodeFromParsed('Constant', 'leaf', labelHint || '', x, y, [], { name: labelHint || '', value });
    }
    const intermediate = parseIntermediateExpression(trimmed);
    if (intermediate) {
        const nodeId = buildVisualGraphFromExpression(intermediate.expr, assignments, nodeByAlias, x, y, intermediate.name || labelHint);
        const node = _visNodes.find(n => n.id === nodeId);
        if (node && node.cat !== 'leaf') {
            node.params = node.params || {};
            node.params.intermediate_name = intermediate.name || labelHint || node.label;
            node.label = node.params.intermediate_name;
        }
        return nodeId;
    }
    if (/^-?\d+(\.\d+)?([eE][+-]?\d+)?$/.test(trimmed)) {
        return addVisualNodeFromParsed('Constant', 'leaf', labelHint || '', x, y, [], { name: labelHint || '', value: trimmed });
    }

    const fnCall = parseFunctionExpression(trimmed);
    if (fnCall) {
        const inputIds = fnCall.args.map((arg, index) =>
            buildVisualGraphFromExpression(arg, assignments, nodeByAlias, x - 220, y + index * 90)
        ).filter(Boolean);
        const cat = getVisualOperatorCatByKey(fnCall.name) || 'arithVariadic';
        return addVisualNodeFromParsed(fnCall.name, cat, labelHint || fnCall.name, x, y, inputIds);
    }

    const method = parseMethodExpression(trimmed);
    if (method) {
        const baseId = buildVisualGraphFromExpression(method.base, assignments, nodeByAlias, x - 220, y);
        const inputIds = baseId ? [baseId] : [];
        method.args.forEach((arg, index) => {
            const argId = buildVisualGraphFromExpression(arg, assignments, nodeByAlias, x - 220, y + (index + 1) * 90);
            if (argId) inputIds.push(argId);
        });
        const cat = getVisualOperatorCatByKey(method.name) || 'ts';
        return addVisualNodeFromParsed(method.name, cat, labelHint || method.name, x, y, inputIds);
    }

    const binary = parseBinaryExpression(trimmed);
    if (binary) {
        const leftId = buildVisualGraphFromExpression(binary.left, assignments, nodeByAlias, x - 220, y - 60);
        const rightId = buildVisualGraphFromExpression(binary.right, assignments, nodeByAlias, x - 220, y + 60);
        return addVisualNodeFromParsed(binary.op, getVisualOperatorCatByKey(binary.op) || 'arithBinary', labelHint || binary.op, x, y, [leftId, rightId].filter(Boolean));
    }

    return addVisualNodeFromParsed('Constant', 'leaf', labelHint || '', x, y, [], { name: labelHint || '', value: trimmed });
}

function addVisualNodeFromParsed(key, cat, label, x = 0, y = 0, inputs = [], params = {}) {
    const opKeys = new Set(Object.values(OP_PALETTE).flat().map(op => op.key));
    const intermediateName = cat !== 'leaf' && label && !opKeys.has(label) ? label : '';
    const node = {
        id: _visNextId++,
        key,
        cat,
        label,
        x: Math.max(0, x),
        y: Math.max(0, y),
        inputs,
        params: intermediateName ? {...params, intermediate_name: intermediateName} : params,
    };
    _visNodes.push(node);
    return node.id;
}

function parseIntermediateExpression(expr) {
    const match = expr.match(/^(.+)\.as_intermediate\((.*)\)$/);
    if (!match) return null;
    const args = splitTopLevelArgs(match[2]);
    const rawName = (args[0] || '').trim();
    return {
        expr: match[1].trim(),
        name: rawName.replace(/^['"]|['"]$/g, ''),
    };
}

function parseMethodExpression(expr) {
    const methodKeys = Object.values(OP_PALETTE).flat()
        .filter(op => !op.syntax && !['DataColumnParam', 'Constant'].includes(op.key))
        .map(op => op.key)
        .sort((a, b) => b.length - a.length)
        .map(escapeRegExp)
        .join('|');
    const match = expr.match(new RegExp(`^(.+)\\.(${methodKeys})\\((.*)\\)$`));
    if (!match) return null;
    const args = splitTopLevelArgs(match[3]);
    return { base: match[1].trim(), name: match[2], args };
}

function parseFunctionExpression(expr) {
    const functionKeys = Object.values(OP_PALETTE).flat()
        .filter(op => op.syntax === 'function')
        .map(op => op.key)
        .sort((a, b) => b.length - a.length)
        .map(escapeRegExp)
        .join('|');
    if (!functionKeys) return null;
    const match = expr.match(new RegExp(`^(${functionKeys})\\((.*)\\)$`));
    if (!match) return null;
    return { name: match[1], args: splitTopLevelArgs(match[2]) };
}

function parseBinaryExpression(expr) {
    for (const ops of [['|'], ['&'], ['==', '!=', '>=', '<=', '>', '<'], ['+', '-'], ['*', '/'], ['**']]) {
        let depth = 0;
        for (let i = expr.length - 1; i >= 0; i--) {
            const ch = expr[i];
            if (ch === ')') depth++;
            if (ch === '(') depth--;
            if (depth !== 0 || i <= 0) continue;
            for (const op of ops) {
                const start = i - op.length + 1;
                if (start <= 0 || expr.slice(start, i + 1) !== op) continue;
                if ((op === '+' || op === '-') && /[eE]/.test(expr[start - 1] || '')) continue;
                return { left: expr.slice(0, start).trim(), op, right: expr.slice(i + 1).trim() };
            }
        }
    }
    return null;
}

function getVisualOperatorCatByKey(key) {
    for (const [cat, ops] of Object.entries(OP_PALETTE)) {
        if (ops.some(op => op.key === key)) return cat;
    }
    return '';
}

function escapeRegExp(text) {
    return String(text).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function splitTopLevelArgs(argText) {
    const args = [];
    let depth = 0;
    let start = 0;
    for (let i = 0; i < argText.length; i++) {
        const ch = argText[i];
        if (ch === '(') depth++;
        if (ch === ')') depth--;
        if (ch === ',' && depth === 0) {
            args.push(argText.slice(start, i).trim());
            start = i + 1;
        }
    }
    const tail = argText.slice(start).trim();
    if (tail) args.push(tail);
    return args;
}

function stripOuterParens(expr) {
    let text = expr;
    while (text.startsWith('(') && text.endsWith(')')) {
        let depth = 0;
        let wraps = true;
        for (let i = 0; i < text.length; i++) {
            if (text[i] === '(') depth++;
            if (text[i] === ')') depth--;
            if (depth === 0 && i < text.length - 1) {
                wraps = false;
                break;
            }
        }
        if (!wraps) break;
        text = text.slice(1, -1).trim();
    }
    return text;
}

// ═══════════════════════════════════════════════════════════
