// 可视化表达式与 Python 源码互转
//
// 业务规范：
// 1. 代码 -> 画布的主表达式只允许来自后端执行 factor_expr() 后得到的 FactorExpr visual_graph。
// 2. 代码 -> 画布只允许做两类源码字符串检查：
//    - 扫描 factor_expr() 中的 Param(...) 声明，用于补回孤立参数。
//    - 检查“上一轮画布生成过的孤立表达式代码行”是否仍存在，存在才恢复快照分支。
// 3. 不允许从源码字符串解析 return/assignment 来推导表达式树或孤立表达式。
// 4. 画布 -> 代码可以自动生成 Python 局部变量名，但不能自动调用 as_intermediate()。
// 5. as_intermediate() 只代表用户显式创建的中间因子；它会影响后端运算逻辑和 LaTeX 展示。

function visualToExpr() {
    if (_visNodes.length === 0) {
        document.getElementById('visual-expr-preview').textContent = '（无节点）';
        return '';
    }
    ensureReturnNode();
    const root = getVisualRootNode();
    const expr = root ? buildExprFromNode(root, new Set(), {root: true}) : '';
    document.getElementById('visual-expr-preview').textContent = expr || '（无法生成表达式）';
    return expr;
}

function buildExprFromNode(node, seen, options = {}) {
    if (!node || seen.has(node.id)) return '';
    seen.add(node.id);
    if (node.key === 'Return') {
        const returnInputId = (node.inputs || [])[0];
        const returnInput = _visNodes.find(n => n.id === returnInputId);
        return returnInput ? buildExprFromNode(returnInput, new Set(seen), {root: true}) : '';
    }
    if (isVisualParamNode(node)) return getVisualParamVariableName(node);
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
    const intermediateName = getVisualUserIntermediateName(node);
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
    if (op.key === 'FactorFreqParam') return { alias: '$F', type: 'FactorFreqParam', default_value: '1d', locked: true };
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

function isVisualParamNode(node) {
    return node?.key === 'DataColumnParam' || node?.key === 'FactorFreqParam';
}

function getVisualParamAlias(node) {
    return node?.params?.alias || node?.label || 'P';
}

function getVisualParamVariableName(node) {
    const alias = getVisualParamAlias(node);
    return String(alias).replace(/^\$/, '') || 'P';
}

function visualToSource(options = {}) {
    if (_currentMode !== 'visual') return document.getElementById('code-source')?.value || '';
    const plan = buildVisualSourcePlan();
    if (!plan.returnExpr) {
        if (!options.silent) showToast('请先完成可视化表达式连接', 'error');
        return '';
    }
    const className = document.getElementById('cfg-name-vis')?.value?.trim() || extractClassNameFromSource(_visSourceFallback) || 'MyFactor';
    const paramNodes = _visNodes.filter(isVisualParamNode);
    const paramTypes = [...new Set(paramNodes.map(n => n.params?.type || 'DataColumnParam'))];
    const factorParamTypes = paramTypes.filter(t => VIS_FACTOR_PARAM_TYPES.includes(t));
    const regularParamTypes = paramTypes.filter(t => !VIS_FACTOR_PARAM_TYPES.includes(t));
    const factorImports = ['FactorFamily', ...factorParamTypes];
    const generatedBodyText = `${plan.assignmentLines.join('\n')}\n${plan.returnExpr}`;
    if (generatedBodyText.includes('ConstExpr(')) factorImports.push('ConstExpr');
    if (generatedBodyText.includes('expr_max(')) factorImports.push('expr_max');
    if (generatedBodyText.includes('expr_min(')) factorImports.push('expr_min');
    const imports = [
        `from tools.factors import ${[...new Set(factorImports)].join(', ')}`,
        regularParamTypes.length ? `from tools.parameters import ${regularParamTypes.join(', ')}` : '',
    ].filter(Boolean).join('\n');
    const uniqueParamNodes = [];
    const seenParamAliases = new Set();
    paramNodes.forEach(n => {
        const alias = getVisualParamAlias(n);
        if (seenParamAliases.has(alias)) return;
        seenParamAliases.add(alias);
        uniqueParamNodes.push(n);
    });
    const paramLines = uniqueParamNodes.map(n => {
        const alias = getVisualParamAlias(n);
        const varName = getVisualParamVariableName(n);
        const type = n.params?.type || 'DataColumnParam';
        const dv = n.params?.default_value || '';
        return `        ${varName} = ${type}('${alias}', default_value=${JSON.stringify(dv)})`;
    }).join('\n');
    const constLines = getNamedVisualConstNodes().map(n => {
        const name = n.params?.name?.trim();
        return `        ${name} = ${normalizeVisualConstValue(n.params?.value)}`;
    }).join('\n');
    const exprLines = plan.assignmentLines.map(line => `        ${line}`).join('\n');
    const setupLines = [paramLines, constLines, exprLines].filter(Boolean).join('\n');
    const setupBlock = setupLines ? `${setupLines}\n` : '';
    const source = `${imports}\n\n\nclass ${className}(FactorFamily):\n    @staticmethod\n    def factor_expr():\n${setupBlock}        return ${plan.returnExpr}\n`;
    _visLastGeneratedSource = source;
    _visSourceFallback = source;
    rememberVisualGraphSnapshot(source, plan.detachedBranches);
    return source;
}

function buildVisualSourcePlan() {
    ensureReturnNode();
    const returnNode = getVisualReturnNode();
    const returnInputId = (returnNode?.inputs || [])[0];
    const returnInput = _visNodes.find(n => n.id === returnInputId);
    const nameByNodeId = assignVisualVariableNames();
    const assignmentLines = [];
    const assignmentLineByNodeId = new Map();
    const emitted = new Set();

    const emitNode = (node) => {
        if (!node || node.key === 'Return' || emitted.has(node.id)) return true;
        const arity = getVisualOperatorArity(node);
        if (!arity) return true;
        const inputIds = (node.inputs || []).slice(0, arity);
        if (inputIds.length < arity || inputIds.some(id => !id)) return false;
        for (const inputId of inputIds) {
            const input = _visNodes.find(n => n.id === inputId);
            if (!emitNode(input)) return false;
        }
        const expr = buildInlineExprForSourceNode(node, nameByNodeId);
        const name = nameByNodeId.get(node.id);
        if (!expr || !name) return false;
        const line = buildVisualAssignmentLine(node, name, expr);
        assignmentLines.push(line);
        assignmentLineByNodeId.set(node.id, line);
        emitted.add(node.id);
        return true;
    };

    if (!emitNode(returnInput)) return {assignmentLines: [], returnExpr: ''};
    _visNodes.forEach(node => {
        if (node.key === 'Return' || node.cat === 'leaf' || node.id === returnInput?.id) return;
        emitNode(node);
    });

    const returnExpr = returnInput ? buildReturnExprForSourceNode(returnInput, nameByNodeId) : '';
    return {
        assignmentLines,
        returnExpr,
        detachedBranches: collectVisualDetachedBranchRecords(_visNodes, assignmentLineByNodeId),
    };
}

function assignVisualVariableNames() {
    const used = new Set();
    _visNodes.filter(isVisualParamNode).forEach(node => used.add(getVisualParamVariableName(node)));
    getNamedVisualConstNodes().forEach(node => used.add(node.params.name.trim()));
    const nameByNodeId = new Map();
    _visNodes.forEach(node => {
        if (!node || node.key === 'Return' || node.cat === 'leaf') return;
        const preferred = getVisualUserIntermediateName(node) || node.label || '';
        const fallback = `expr_${node.id}`;
        const name = uniqueVisualPythonIdentifier(preferred, fallback, used);
        used.add(name);
        nameByNodeId.set(node.id, name);
    });
    return nameByNodeId;
}

function uniqueVisualPythonIdentifier(preferred, fallback, used) {
    const base = visualPythonIdentifier(preferred, fallback);
    let candidate = base;
    let suffix = 2;
    while (used.has(candidate)) {
        candidate = `${base}_${suffix++}`;
    }
    return candidate;
}

function visualPythonIdentifier(preferred, fallback) {
    const opKeys = new Set(Object.values(OP_PALETTE).flat().map(op => op.key));
    let text = String(preferred || '').trim();
    if (!text || opKeys.has(text) || text === 'Return') text = fallback;
    text = text.replace(/[^0-9A-Za-z_]/g, '_').replace(/_+/g, '_').replace(/^_+|_+$/g, '');
    if (!text || /^[0-9]/.test(text)) text = `expr_${text || fallback}`;
    return text;
}

function buildReturnExprForSourceNode(node, nameByNodeId) {
    if (!node) return '';
    if (node.cat !== 'leaf') return nameByNodeId.get(node.id) || '';
    if (isVisualParamNode(node)) return getVisualParamVariableName(node);
    if (node.key === 'Constant') {
        const name = (node.params?.name || '').trim();
        return `ConstExpr(${name || normalizeVisualConstValue(node.params?.value)})`;
    }
    return '';
}

function getVisualUserIntermediateName(node) {
    const name = String(node?.params?.intermediate_name || '').trim();
    if (isVisualGeneratedVariableName(name)
        && node?.params?.intermediate_from_factor_expr
        && !node?.params?.intermediate_canvas_defined) {
        return '';
    }
    return node?.params?.intermediate_user_defined && name ? name : '';
}

function isVisualGeneratedVariableName(name) {
    return /^expr_\d+$/.test(String(name || '').trim());
}

function buildVisualAssignmentLine(node, name, expr) {
    const intermediateName = getVisualUserIntermediateName(node);
    if (intermediateName) {
        return `${name} = (${expr}).as_intermediate(${JSON.stringify(intermediateName)})`;
    }
    return `${name} = ${expr}`;
}

function buildInlineExprForSourceNode(node, nameByNodeId) {
    if (!node) return '';
    if (isVisualParamNode(node)) return getVisualParamVariableName(node);
    if (node.key === 'Constant') {
        const name = (node.params?.name || '').trim();
        return name || normalizeVisualConstValue(node.params?.value);
    }
    const arity = getVisualOperatorArity(node);
    const inputIds = (node.inputs || []).slice(0, arity);
    if (arity && (inputIds.length < arity || inputIds.some(id => !id))) return '';
    const exprs = inputIds.map(id => {
        const child = _visNodes.find(n => n.id === id);
        return child?.cat !== 'leaf'
            ? nameByNodeId.get(child.id)
            : buildInlineExprForSourceNode(child, nameByNodeId);
    });
    return buildVisualOperatorExpr(node, exprs, arity);
}

function buildVisualOperatorExpr(node, exprs, arity) {
    if (exprs.some(expr => !expr)) return '';
    if (isVisualInfixOperator(node)) {
        return exprs.length >= arity ? `(${exprs[0]} ${node.key} ${exprs[1]})` : '';
    }
    if (node.key === '~') {
        return exprs.length >= 1 ? `(~${exprs[0]})` : '';
    }
    if (node.key === 'expr_max' || node.key === 'expr_min') {
        return exprs.length >= arity ? `${node.key}(${exprs.join(', ')})` : '';
    }
    if (node.key === 'max' || node.key === 'min') {
        return exprs.length >= 2 ? `${exprs[0]}.${node.key}(${exprs[1]})` : '';
    }
    if (node.key === 'rolling_corr') {
        return exprs.length >= 3 ? `${exprs[0]}.rolling_corr(${exprs[1]}, ${exprs[2]})` : '';
    }
    if (!exprs.length) return '';
    return `${exprs[0]}.${node.key}(${exprs.slice(1).join(', ')})`;
}

function rememberVisualGraphSnapshot(source, detachedBranches = null) {
    if (!source) return;
    _visGraphSnapshotSource = source;
    _visGraphSnapshotNormalizedSource = normalizeVisualSourceForSnapshot(source);
    _visGraphSnapshot = {
        nodes: cloneVisualGraphValue(_visNodes),
        nextId: _visNextId,
        selectedNodeId: _visSelectedNodeId,
        rootId: getVisualRootNode()?.id || null,
        namedConstants: collectVisualNamedConstRecords(_visNodes),
        detachedBranches: detachedBranches || collectVisualDetachedBranchRecords(_visNodes),
    };
}

function snapshotCurrentVisualGraphForModeSwitch() {
    const source = visualToSource({silent: true});
    if (source) rememberVisualGraphSnapshot(source);
}

function restoreVisualGraphSnapshotIfMatches(source) {
    if (!source || !_visGraphSnapshot) return false;
    const sourceMatches = source === _visGraphSnapshotSource
        || normalizeVisualSourceForSnapshot(source) === _visGraphSnapshotNormalizedSource;
    if (!sourceMatches) return false;
    _visNodes = cloneVisualGraphValue(_visGraphSnapshot.nodes || []);
    _visNextId = _visGraphSnapshot.nextId || inferNextVisualNodeId();
    _visSelectedNodeId = _visGraphSnapshot.selectedNodeId || null;
    _visGraphDirty = true;
    renderVisualEditor._lastSource = source;
    return true;
}

function cloneVisualGraphValue(value) {
    return JSON.parse(JSON.stringify(value || []));
}

function inferNextVisualNodeId() {
    return Math.max(0, ..._visNodes.map(n => Number(n.id) || 0)) + 1;
}

function normalizeVisualSourceForSnapshot(source) {
    return String(source || '')
        .replace(/\r\n/g, '\n')
        .split('\n')
        .map(line => line.trim())
        .filter(Boolean)
        .join('\n');
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

function collectVisualNamedConstRecords(nodes) {
    return nodes
        .filter(node => node.key === 'Constant' && node.params?.name?.trim())
        .map(node => {
            const name = node.params.name.trim();
            const value = normalizeVisualConstValue(node.params?.value);
            return {
                nodeId: node.id,
                name,
                value,
                line: `${name} = ${value}`,
            };
        });
}

function collectVisualDetachedBranchRecords(nodes, assignmentLineByNodeId = null) {
    const reachable = collectVisualReachableFromReturn(nodes);
    const detached = nodes.filter(node => node.cat !== 'leaf' && node.key !== 'Return' && !reachable.has(node.id));
    if (!detached.length) return [];
    const detachedIds = new Set(detached.map(node => node.id));
    const referencedByDetached = new Set();
    detached.forEach(node => (node.inputs || []).forEach(inputId => {
        if (detachedIds.has(inputId)) referencedByDetached.add(inputId);
    }));
    return detached
        .filter(node => !referencedByDetached.has(node.id))
        .map(root => buildVisualDetachedBranchRecord(nodes, root.id, assignmentLineByNodeId))
        .filter(Boolean);
}

function collectVisualReachableFromReturn(nodes) {
    const reachable = new Set();
    const returnNode = nodes.find(node => node.key === 'Return');
    const stack = [...(returnNode?.inputs || []).filter(Boolean)];
    while (stack.length) {
        const id = stack.pop();
        if (reachable.has(id)) continue;
        reachable.add(id);
        const node = nodes.find(n => n.id === id);
        (node?.inputs || []).filter(Boolean).forEach(inputId => stack.push(inputId));
    }
    return reachable;
}

function buildVisualDetachedBranchRecord(nodes, rootId, assignmentLineByNodeId = null) {
    const subtreeIds = collectVisualSubtreeIds(nodes, rootId);
    const subtreeNodes = nodes.filter(node => subtreeIds.has(node.id));
    const nameByNodeId = assignSnapshotIntermediateNames(subtreeNodes);
    const emitted = new Set();
    const lines = [];
    const emitNode = (node) => {
        if (!node || node.key === 'Return' || node.cat === 'leaf' || emitted.has(node.id)) return true;
        const arity = getVisualOperatorArity(node);
        const inputIds = (node.inputs || []).slice(0, arity);
        if (arity && (inputIds.length < arity || inputIds.some(id => !id))) return false;
        for (const inputId of inputIds) {
            const input = nodes.find(n => n.id === inputId);
            if (!emitNode(input)) return false;
        }
        const existingLine = assignmentLineByNodeId?.get(node.id);
        if (existingLine) {
            lines.push(existingLine);
        } else {
            const expr = buildInlineExprForSnapshotNode(nodes, node, nameByNodeId);
            const name = nameByNodeId.get(node.id);
            if (!expr || !name) return false;
            lines.push(buildVisualAssignmentLine(node, name, expr));
        }
        emitted.add(node.id);
        return true;
    };
    const root = nodes.find(node => node.id === rootId);
    if (!emitNode(root) || !lines.length) return null;
    return {rootId, nodeIds: [...subtreeIds], lines};
}

function collectVisualSubtreeIds(nodes, rootId) {
    const result = new Set();
    const stack = [rootId];
    while (stack.length) {
        const id = stack.pop();
        if (!id || result.has(id)) continue;
        result.add(id);
        const node = nodes.find(n => n.id === id);
        (node?.inputs || []).filter(Boolean).forEach(inputId => stack.push(inputId));
    }
    return result;
}

function assignSnapshotIntermediateNames(nodes) {
    const used = new Set();
    nodes.filter(isVisualParamNode).forEach(node => used.add(getVisualParamVariableName(node)));
    nodes.filter(node => node.key === 'Constant').forEach(node => {
        const name = node.params?.name?.trim();
        if (name) used.add(name);
    });
    const nameByNodeId = new Map();
    nodes.forEach(node => {
        if (!node || node.key === 'Return' || node.cat === 'leaf') return;
        const preferred = getVisualUserIntermediateName(node) || node.label || '';
        const fallback = `expr_${node.id}`;
        const name = uniqueVisualPythonIdentifier(preferred, fallback, used);
        used.add(name);
        nameByNodeId.set(node.id, name);
    });
    return nameByNodeId;
}

function buildInlineExprForSnapshotNode(nodes, node, nameByNodeId) {
    if (!node) return '';
    if (isVisualParamNode(node)) return getVisualParamVariableName(node);
    if (node.key === 'Constant') {
        const name = (node.params?.name || '').trim();
        return name || normalizeVisualConstValue(node.params?.value);
    }
    const arity = getVisualOperatorArity(node);
    const inputIds = (node.inputs || []).slice(0, arity);
    if (arity && (inputIds.length < arity || inputIds.some(id => !id))) return '';
    const exprs = inputIds.map(id => {
        const child = nodes.find(n => n.id === id);
        return child?.cat !== 'leaf'
            ? nameByNodeId.get(child.id)
            : buildInlineExprForSnapshotNode(nodes, child, nameByNodeId);
    });
    return buildVisualOperatorExpr(node, exprs, arity);
}

function restoreSnapshotDetachedBranchesIfStillInSource(source) {
    const branches = _visGraphSnapshot?.detachedBranches || [];
    if (!branches.length) return;
    const sourceLines = new Set(normalizeVisualSourceForSnapshot(source).split('\n'));
    const snapshotNodes = cloneVisualGraphValue(_visGraphSnapshot.nodes || []);
    const currentNames = new Set(_visNodes.map(node => getVisualUserIntermediateName(node) || node.label).filter(Boolean));
    let nextId = inferNextVisualNodeId();

    branches.forEach(branch => {
        if (!branch.lines?.every(line => sourceLines.has(String(line || '').trim()))) return;
        const branchNodes = snapshotNodes.filter(node => (branch.nodeIds || []).includes(node.id));
        const branchNames = branchNodes.map(node => getVisualUserIntermediateName(node) || node.label).filter(Boolean);
        if (branchNames.some(name => currentNames.has(name))) return;

        const oldIds = new Set(branchNodes.map(node => node.id));
        const idMap = new Map();
        branchNodes.forEach(node => idMap.set(node.id, nextId++));
        const cloned = branchNodes.map(node => ({
            ...node,
            id: idMap.get(node.id),
            inputs: (node.inputs || []).map(inputId => oldIds.has(inputId) ? idMap.get(inputId) : null),
            params: {...(node.params || {})},
        }));
        cloned.forEach(node => {
            const name = getVisualUserIntermediateName(node) || node.label;
            if (name) currentNames.add(name);
        });
        _visNodes.push(...cloned);
    });
    _visNextId = Math.max(_visNextId, nextId);
}

function restoreSnapshotNamedConstantsIfStillInSource(source) {
    const records = _visGraphSnapshot?.namedConstants || [];
    if (!records.length) return;
    const sourceLines = new Set(normalizeVisualSourceForSnapshot(source).split('\n'));
    const usedNames = new Set(_visNodes
        .filter(node => node.key === 'Constant')
        .map(node => node.params?.name?.trim())
        .filter(Boolean));
    let nextId = inferNextVisualNodeId();

    records.forEach(record => {
        const name = String(record.name || '').trim();
        const value = normalizeVisualConstValue(record.value);
        if (!name || usedNames.has(name)) return;
        if (!sourceLines.has(String(record.line || '').trim())) return;

        const existing = _visNodes.find(node =>
            node.key === 'Constant'
            && !node.params?.name?.trim()
            && normalizeVisualConstValue(node.params?.value) === value
        );
        if (existing) {
            existing.params = existing.params || {};
            existing.params.name = name;
            existing.label = name;
        } else {
            _visNodes.push({
                id: nextId++,
                key: 'Constant',
                cat: 'leaf',
                label: name,
                x: 0,
                y: 0,
                inputs: [],
                params: {name, value},
            });
        }
        usedNames.add(name);
    });
    _visNextId = Math.max(_visNextId, nextId);
}

function loadVisualNodesFromSource(source) {
    _visNodes = [];
    _visNextId = 1;
    _visSelectedNodeId = null;
    const params = parseParamNodesFromSource(source);
    addUnusedVisualParamsFromSource(params.length ? params : [
        { alias: 'P', variable_name: 'P', type: 'DataColumnParam', default_value: 'CA' },
    ]);
    restoreSnapshotNamedConstantsIfStillInSource(source);
    restoreSnapshotDetachedBranchesIfStillInSource(source);
    ensureReturnNode();
}

function loadVisualNodesFromGraph(graph, source = '') {
    if (!graph || !Array.isArray(graph.nodes) || !graph.nodes.length) return false;
    _visNodes = graph.nodes.map(node => ({
        id: Number(node.id),
        key: node.key,
        cat: node.cat,
        label: node.label || node.key,
        x: Number(node.x) || 0,
        y: Number(node.y) || 0,
        inputs: Array.isArray(node.inputs) ? node.inputs.map(id => Number(id)).filter(Boolean) : [],
        params: {...(node.params || {})},
    })).filter(node => node.id && node.key);
    _visNextId = Number(graph.next_id) || inferNextVisualNodeId();
    _visSelectedNodeId = null;
    ensureReturnNode();
    addUnusedVisualParamsFromSource(parseParamNodesFromSource(source));
    restoreSnapshotNamedConstantsIfStillInSource(source);
    restoreSnapshotDetachedBranchesIfStillInSource(source);
    return true;
}

function addUnusedVisualParamsFromSource(params) {
    const existingAliases = new Set(_visNodes
        .filter(isVisualParamNode)
        .map(node => getVisualParamAlias(node)));
    params.forEach(param => {
        if (existingAliases.has(param.alias)) return;
        existingAliases.add(param.alias);
        addVisualParamNodeFromParsed(param);
    });
}

function parseParamNodesFromSource(source) {
    const body = extractFactorExprBody(source);
    const params = [];
    const regex = /^\s*(\w+)\s*=\s*(\w+Param)\(\s*['"]([^'"]+)['"]\s*,\s*default_value\s*=\s*([^)\n]+)\)/gm;
    let match;
    while ((match = regex.exec(body)) !== null) {
        params.push({
            alias: match[3] || match[1],
            variable_name: match[1] || '',
            type: match[2],
            default_value: String(match[4] || '').trim().replace(/^['"]|['"]$/g, ''),
        });
    }
    return params;
}

function extractFactorExprBody(source) {
    const lines = String(source || '').replace(/\r\n/g, '\n').split('\n');
    const defIndex = lines.findIndex(line => /^\s*def\s+factor_expr\s*\(/.test(line));
    if (defIndex < 0) return String(source || '');
    const defIndent = lines[defIndex].match(/^\s*/)?.[0].length || 0;
    const body = [];
    for (let i = defIndex + 1; i < lines.length; i++) {
        const line = lines[i];
        if (line.trim() && (line.match(/^\s*/)?.[0].length || 0) <= defIndent) break;
        body.push(line);
    }
    return body.join('\n');
}

function addVisualParamNodeFromParsed(param, x = 0, y = 0) {
    const key = param.type === 'FactorFreqParam' || param.alias === '$F'
        ? 'FactorFreqParam'
        : 'DataColumnParam';
    return addVisualNodeFromParsed(key, 'leaf', param.alias, x, y, [], {
        ...param,
        alias: param.alias,
        locked: key === 'FactorFreqParam',
    });
}

function addVisualNodeFromParsed(key, cat, label, x = 0, y = 0, inputs = [], params = {}) {
    const node = {
        id: _visNextId++,
        key,
        cat,
        label,
        x: Math.max(0, x),
        y: Math.max(0, y),
        inputs,
        params,
    };
    _visNodes.push(node);
    return node.id;
}
