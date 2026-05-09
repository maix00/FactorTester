// ═══════════════════════════════════════════════════════════
// 可视化编辑器模式 — 算子面板 + 拖放画布
// ═══════════════════════════════════════════════════════════

let _visNodes = [];
let _visNextId = 1;
let _visSelectedNodeId = null;
let _visDragging = null;
let _visSourceFallback = '';
let _visGraphDirty = false;
let _visPendingConnection = null;
let _visLastGeneratedSource = '';
let _visGraphSnapshot = null;
let _visGraphSnapshotSource = '';
let _visGraphSnapshotNormalizedSource = '';

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
    const restoredSnapshot = previousMode === 'code' && restoreVisualGraphSnapshotIfMatches(_visSourceFallback);
    const shouldParseSource = !restoredSnapshot && (!_visNodes.length
        || (previousMode === 'code' && _visSourceFallback !== _visLastGeneratedSource)
        || (!_visGraphDirty && _visSourceFallback !== (renderVisualEditor._lastSource || '')));
    if (shouldParseSource) {
        _visGraphDirty = false;
        const graphLoaded = _validatedVisualGraph
            && _validatedSourceSnapshot === _visSourceFallback
            && loadVisualNodesFromGraph(_validatedVisualGraph, _visSourceFallback);
        if (!graphLoaded) loadVisualNodesFromSource(_visSourceFallback);
        renderVisualEditor._lastSource = _visSourceFallback;
    }

    ensureReturnNode();
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
        el.className = 'vis-node'
            + (node.key === 'Return' ? ' return-node' : '')
            + (isVisualSharedLeafSelected(node) ? ' shared-selected' : '')
            + (node.id === _visSelectedNodeId ? ' selected' : '');
        el.style.left = node.x + 'px';
        el.style.top = node.y + 'px';
        el.dataset.nodeId = node.id;
        el.innerHTML = `
            ${node.key === 'Return' ? '' : `<button class="btn-delete-node" onclick="deleteVisNode(${node.id});event.stopPropagation()">×</button>`}
            ${node.key === 'Return' ? '' : `<button class="btn-copy-node" title="复制节点" onclick="duplicateVisNode(${node.id});event.stopPropagation()">⧉</button>`}
            <div class="node-card-head">
                <div class="node-label">${escHtml(node.label)}</div>
                <div class="node-sub">${escHtml(getVisualNodeSubtitle(node))}</div>
            </div>
            ${renderVisualSharedLeafBadge(node)}
            ${getVisualUserIntermediateName(node) ? `<div class="node-intermediate-badge">中间因子 ${escHtml(getVisualUserIntermediateName(node))}</div>` : ''}
            ${renderVisualNodeSlots(node)}
            ${node.key === 'Return' ? '' : `<button class="node-output-port" title="点击后选择目标输入槽" onclick="startVisualConnection(${node.id});event.stopPropagation()"></button>`}
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
        output: '输出',
    };
    const labelEditor = isVisualParamNode(node) || node.key === 'Constant'
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

function duplicateVisNode(nodeId) {
    const node = _visNodes.find(n => n.id === nodeId);
    if (!node || node.key === 'Return') return;
    const cloneId = cloneVisualNodeTree(node.id, 28, 28);
    _dirty = true;
    _visGraphDirty = true;
    invalidateCodeValidation();
    renderAllVisNodes();
    selectVisNode(cloneId);
}

function cloneVisualNodeTree(rootId, dx = 28, dy = 28) {
    const idMap = new Map();
    const cloneNode = (oldId) => {
        if (idMap.has(oldId)) return idMap.get(oldId);
        const source = _visNodes.find(n => n.id === oldId);
        if (!source || source.key === 'Return') return null;
        const clone = JSON.parse(JSON.stringify(source));
        clone.id = _visNextId++;
        clone.x = (source.x || 0) + dx;
        clone.y = (source.y || 0) + dy;
        idMap.set(oldId, clone.id);
        clone.inputs = (source.inputs || []).map(inputId => inputId ? cloneNode(inputId) : null);
        _visNodes.push(clone);
        return clone.id;
    };
    return cloneNode(rootId);
}

function renderVisualSharedLeafBadge(node) {
    const key = getVisualLeafReferenceKey(node);
    if (!key) return '';
    const count = _visNodes.filter(n => getVisualLeafReferenceKey(n) === key).length;
    if (count <= 1) return '';
    return `<div class="node-shared-ref" title="画布中有多个叶节点引用同一个 ${escAttr(key)}">同源</div>`;
}

function getVisualLeafReferenceKey(node) {
    if (isVisualParamNode(node)) return `参数 ${getVisualParamAlias(node)}`;
    if (node.key === 'Constant') return `常数 ${node.params?.name || normalizeVisualConstValue(node.params?.value)}`;
    return '';
}

function isVisualSharedLeafSelected(node) {
    const selected = _visNodes.find(n => n.id === _visSelectedNodeId);
    const selectedKey = selected ? getVisualLeafReferenceKey(selected) : '';
    return !!selectedKey && getVisualLeafReferenceKey(node) === selectedKey && node.id !== _visSelectedNodeId;
}

function getVisualNodeSubtitle(node) {
    if (node.key === 'Return') return '最终返回值';
    if (isVisualParamNode(node)) return `${node.params?.type || 'DataColumnParam'}=${node.params?.default_value || ''}`;
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
    if (node.key === 'Return') return VIS_SYSTEM_OPERATORS[0];
    return Object.entries(OP_PALETTE).flatMap(([cat, ops]) => ops.map(op => ({...op, cat})))
        .find(op => op.key === node.key && op.cat === node.cat)
        || Object.entries(OP_PALETTE).flatMap(([cat, ops]) => ops.map(op => ({...op, cat})))
            .find(op => op.key === node.key)
        || null;
}

function isVisualInfixOperator(node) {
    return getVisualOperatorDef(node)?.syntax === 'infix'
        || ['+', '-', '*', '/', '**', '>', '<', '>=', '<=', '==', '!=', '&', '|'].includes(node.key);
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
    if (node.key === 'Return') return '';
    const intermediateControls = node.cat !== 'leaf' ? `
        <div class="field"><label>中间因子标记</label>
            <input value="${escHtml(getVisualUserIntermediateName(node))}" placeholder="如 SIG_YZ，不填则不标记"
                oninput="updateVisualParam(${node.id}, 'intermediate_name', this.value)">
        </div>
    ` : '';
    if (node.key === 'FactorFreqParam') {
        return `
            <div class="field"><label>系统参数</label><span>$F（因子信号频率，代码中变量名为 F）</span></div>
            <div class="field"><label>参数类型</label><span>FactorFreqParam</span></div>
            <div class="field"><label>默认值</label><span>${escHtml(node.params?.default_value || '1d')}</span></div>
        `;
    }
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
    if (key === 'intermediate_name') {
        node.params.intermediate_user_defined = !!String(value || '').trim();
        node.params.intermediate_canvas_defined = !!String(value || '').trim();
        if (value) node.label = value;
    }
    _dirty = true;
    _visGraphDirty = true;
    invalidateCodeValidation();
    renderAllVisNodes();
    updateVisualExprPreview();
}

function getVisualRootNode() {
    const returnNode = getVisualReturnNode();
    if (returnNode) return returnNode;
    const referenced = new Set(_visNodes.flatMap(node => (node.inputs || []).filter(Boolean)));
    const roots = [..._visNodes].filter(node => !referenced.has(node.id));
    const completeExpressionRoots = roots.filter(node => getVisualOperatorArity(node) > 0 && isVisualNodeComplete(node.id, new Set()));
    if (completeExpressionRoots.length) return completeExpressionRoots[completeExpressionRoots.length - 1];
    const expressionRoots = roots.filter(node => getVisualOperatorArity(node) > 0);
    if (expressionRoots.length) return expressionRoots[expressionRoots.length - 1];
    return roots[roots.length - 1] || _visNodes[_visNodes.length - 1];
}

function getVisualReturnNode() {
    return _visNodes.find(node => node.key === 'Return') || null;
}

function ensureReturnNode(inputId = null) {
    let returnNode = getVisualReturnNode();
    if (returnNode) {
        if (inputId) returnNode.inputs = [inputId];
        return returnNode.id;
    }
    const node = {
        id: _visNextId++,
        key: 'Return',
        cat: 'output',
        label: 'return',
        x: 760,
        y: 40,
        inputs: inputId ? [inputId] : [],
        params: {},
    };
    _visNodes.push(node);
    return node.id;
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

// ═══════════════════════════════════════════════════════════
