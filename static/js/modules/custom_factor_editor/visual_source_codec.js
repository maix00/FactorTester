// 可视化表达式与 Python 源码互转

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
    params.forEach(param => {
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
