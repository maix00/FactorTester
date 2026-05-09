// 可视化画布布局与连线渲染

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
    ensureReturnNode();
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
