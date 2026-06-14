const { assert, resetGroupTest, load } = require('./group_test_harness');
const path = require('path');

const GT = resetGroupTest();
require(path.resolve(__dirname, '../../static/js/modules/shared/money_display.js'));
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
        { name: '总资产', desc: 'Total Equity' },
        { name: '现金', desc: 'Cash' },
        { name: 'IF', desc: '沪深300', fee: { open_ratio: 0.001, close_ratio: 0.002 } },
        { name: 'IC', desc: '中证500', fee: { open_ratio: 0.001, close_ratio: 0.002 } },
      ],
      cells: [
        [
          { status: 'increasing', product: { name: '总资产', desc: 'Total Equity' }, quantity: null, amount: 1300, pre_rebalance_amount: 1250, post_rebalance_amount: 1240, end_amount: 1300, buy_fee_amount: 7, sell_fee_amount: 3, delta_quantity: null, delta_amount: 60, change_direction: 'increase' },
          { status: 'decreasing', product: { name: '总资产', desc: 'Total Equity' }, quantity: null, amount: 1100, pre_rebalance_amount: 1150, post_rebalance_amount: 1140, end_amount: 1100, buy_fee_amount: 6, sell_fee_amount: 4, delta_quantity: null, delta_amount: -40, change_direction: 'decrease' },
        ],
        [
          { status: 'decreasing', product: { name: '现金', desc: 'Cash' }, quantity: null, amount: 900, pre_rebalance_amount: 950, post_rebalance_amount: 920, end_amount: 900, buy_fee_amount: 7, sell_fee_amount: 3, delta_quantity: null, delta_amount: -20, change_direction: 'decrease' },
          { status: 'increasing', product: { name: '现金', desc: 'Cash' }, quantity: null, amount: 1200, pre_rebalance_amount: 1000, post_rebalance_amount: 980, end_amount: 1200, buy_fee_amount: 12, sell_fee_amount: 8, delta_quantity: null, delta_amount: 220, change_direction: 'increase' },
        ],
        [
          { status: 'selected', selected: true, currency: 'CNY', open_reason: '剩余现金约 CNY 1,000.00，小于一手总成本约 CNY 10,000.00', planned_qty: 0, planned_amount: 0, one_lot_margin: 8000, one_lot_required_cash: 10000, target_budget_amount: 1000, product: { name: 'IF', desc: '沪深300', fee: { open_ratio: 0.001, close_ratio: 0.002 } }, quantity: 0, amount: 0, delta_quantity: 0, delta_amount: 0, change_direction: 'flat' },
          { status: 'entering', selected: false, currency: 'CNY', product: { name: 'IF', desc: '沪深300', fee: { open_ratio: 0.001, close_ratio: 0.002 } }, quantity: 1, amount: 5000, delta_quantity: 1, delta_amount: 5000, change_direction: 'increase' },
        ],
        [
          { status: 'absent' },
          { status: 'pending_exit', currency: 'CNY', product: { name: 'IC', desc: '中证500', fee: { open_ratio: 0.001, close_ratio: 0.002 } }, quantity: 3, amount: 7500, delta_quantity: -2, delta_amount: -2500, change_direction: 'decrease' },
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
  all_timestamps_ms: [1710000000000, 1710000060000],
  display_timezone: 'Asia/Shanghai',
  capital_warning: '首期有 1 个组未能开出任何仓位。按等权分配后，每个活跃品种可分到的预算约 CNY 1,000.00，但第一组里最便宜的品种 TEST 的一手资金需求约 CNY 10,000.00，因此目标仓位在最小手数上被压成 0。当前初始金额为 CNY 1,000.00。',
  summary: { avg_turnover: 12.3, total_changed: 4, total_prod_count: 2 },
}, 1710000000000);

const body = document.getElementById('snapshot_body').innerHTML;
const stats = document.getElementById('snapshot_flow_stats').innerHTML;
const title = document.getElementById('snapshot_title').innerHTML;
assert.match(title, /至/);
assert.match(body, /仓位矩阵/);
assert.match(body, /Group A/);
assert.match(body, /Group B/);
assert.match(body, /持仓品种数\(1\)/);
assert.match(body, /IF/);
assert.match(body, /IC/);
assert.match(body, /总资产/);
assert.match(body, /现金/);
const toggle = document.getElementById('snapshot_matrix_toggle').innerHTML;
assert.match(toggle, /全产品/);
assert.match(toggle, /期限折叠/);
assert.match(body, /已选中/);
assert.match(body, /一手估算 CNY\s*10,000\.00（保证金 CNY\s*8,000\.00 \+ 手续费 CNY\s*0\.00）/);
assert.match(body, /计划开 0 手/);
assert.match(body, /目标预算 CNY\s*1,000\.00/);
assert.match(body, /剩余现金约 CNY 1,000\.00，小于一手总成本约 CNY 10,000\.00/);
assert.match(body, /变化 \+1/);
assert.match(body, /变化 -2/);
assert.match(body, /金额 \+60\.00/);
assert.match(body, /金额 -20\.00/);
assert.match(body, /调仓前 1,250\.00/);
assert.match(body, /调仓后 1,240\.00/);
assert.match(body, /期末 1,300\.00/);
assert.match(body, /买入费 7\.00/);
assert.match(body, /卖出费 3\.00/);
assert.match(body, /买入费 7\.00<\/div><div class="snapshot-summary-fees">卖出费 3\.00/);
assert.match(body, /总资产<\/span>/);
assert.doesNotMatch(body, /总资产<\/span><span class="snapshot-product-desc">/);
assert.match(body, /新增/);
assert.match(body, /增加/);
assert.match(body, /减少/);
assert.match(body, /待卖/);
assert.match(body, /已选中/);
assert.match(body, /持仓品种数\(1\)/);
assert.match(stats, /一手资金需求/);
assert.match(stats, /总体流动统计/);

console.log('PASS: group snapshot renders matrix toggle and matrix table');
