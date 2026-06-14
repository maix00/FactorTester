const { assert, resetGroupTest, load } = require('./group_test_harness');

const GT = resetGroupTest();
load('results/snapshot.js');

document.registerElement('snapshot_title');
document.registerElement('snapshot_body');
document.registerElement('snapshot_flow_stats');
document.registerElement('snapshot_matrix_toggle');

GT.results.snapshot.renderGroupSnapshot({
  default_matrix_key: 'raw',
  matrices: [
    {
      key: 'raw',
      label: '全产品',
      columns: [
        { name: 'Group A', label: 'Group A', count: 1 },
        { name: 'Group B', label: 'Group B', count: 2 },
      ],
      rows: [
        { name: 'IF', desc: '沪深300', fee: { open_ratio: 0.001, close_ratio: 0.002 } },
        { name: 'IC', desc: '中证500', fee: { open_ratio: 0.001, close_ratio: 0.002 } },
        { name: '总资产', desc: 'Total Equity' },
        { name: '现金', desc: 'Cash' },
      ],
      cells: [
        [
          { status: 'increasing', product: { name: 'IF', desc: '沪深300', fee: { open_ratio: 0.001, close_ratio: 0.002 } }, quantity: 2, amount: 10000, delta_quantity: 1, delta_amount: 5000, change_direction: 'increase' },
          { status: 'entering', product: { name: 'IF', desc: '沪深300', fee: { open_ratio: 0.001, close_ratio: 0.002 } }, quantity: 1, amount: 5000, delta_quantity: 1, delta_amount: 5000, change_direction: 'increase' },
        ],
        [
          { status: 'absent' },
          { status: 'pending_exit', product: { name: 'IC', desc: '中证500', fee: { open_ratio: 0.001, close_ratio: 0.002 } }, quantity: 3, amount: 7500, delta_quantity: -2, delta_amount: -2500, change_direction: 'decrease' },
        ],
        [
          { status: 'increasing', product: { name: '总资产', desc: 'Total Equity' }, quantity: null, amount: 1300, delta_quantity: null, delta_amount: 100, change_direction: 'increase' },
          { status: 'decreasing', product: { name: '总资产', desc: 'Total Equity' }, quantity: null, amount: 1100, delta_quantity: null, delta_amount: -50, change_direction: 'decrease' },
        ],
        [
          { status: 'decreasing', product: { name: '现金', desc: 'Cash' }, quantity: null, amount: 900, delta_quantity: null, delta_amount: -100, change_direction: 'decrease' },
          { status: 'increasing', product: { name: '现金', desc: 'Cash' }, quantity: null, amount: 1200, delta_quantity: null, delta_amount: 200, change_direction: 'increase' },
        ],
      ],
    },
    {
      key: 'collapsed',
      label: '期限折叠',
      columns: [
        { name: 'Group A', label: 'Group A', count: 1 },
      ],
      rows: [
        { name: 'IF.CFE', desc: '沪深300期货', fee: { open_ratio: 0.001, close_ratio: 0.002 } },
      ],
      cells: [
        [
          { status: 'holding', product: { name: 'IF.CFE', desc: '沪深300期货', fee: { open_ratio: 0.001, close_ratio: 0.002 } }, quantity: 2, amount: 10000 },
        ],
      ],
    },
  ],
  has_prev: false,
  has_next: false,
  summary: { avg_turnover: 12.3, total_changed: 4, total_prod_count: 2 },
}, Date.now());

const body = document.getElementById('snapshot_body').innerHTML;
assert.match(body, /仓位矩阵/);
assert.match(body, /Group A/);
assert.match(body, /Group B/);
assert.match(body, /IF/);
assert.match(body, /IC/);
assert.match(body, /总资产/);
assert.match(body, /现金/);
const toggle = document.getElementById('snapshot_matrix_toggle').innerHTML;
assert.match(toggle, /全产品/);
assert.match(toggle, /期限折叠/);
assert.match(body, /持仓 2\.000000/);
assert.match(body, /金额 10000\.00/);
assert.match(body, /变化 \+1\.000000/);
assert.match(body, /变化 -2\.000000/);
assert.match(body, /金额 \+100\.00/);
assert.match(body, /金额 -100\.00/);

console.log('PASS: group snapshot renders matrix toggle and matrix table');
