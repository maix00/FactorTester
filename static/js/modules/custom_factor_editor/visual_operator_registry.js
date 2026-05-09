// 可视化算子注册表与算子面板

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
const VIS_SYSTEM_OPERATORS = [
    { key: 'Return', label: 'return', desc: '最终返回值', arity: 1, slots: ['返回表达式'], cat: 'output' },
];

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
