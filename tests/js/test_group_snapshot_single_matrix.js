const { assert, resetGroupTest, load } = require('./group_test_harness');

const GT = resetGroupTest();
load('results/snapshot.js');

document.registerElement('snapshot_title');
document.registerElement('snapshot_body');
document.registerElement('snapshot_flow_stats');

GT.results.snapshot.renderGroupSnapshot({
  flat_count: 2,
  groups: [
    {
      name: 'Group A',
      count: 2,
      products: [
        { name: 'IF', desc: '沪深300', fee: { open_ratio: 0.001, close_ratio: 0.002 } },
      ],
      products_in: [],
      products_out: [],
    },
    {
      name: 'Group B',
      count: 2,
      products: [
        { name: 'IF', desc: '沪深300', fee: { open_ratio: 0.001, close_ratio: 0.002 } },
        { name: 'IC', desc: '中证500', fee: { open_ratio: 0.001, close_ratio: 0.002 } },
      ],
      products_in: [],
      products_out: [],
    },
  ],
  has_prev: false,
}, Date.now());

const body = document.getElementById('snapshot_body').innerHTML;
assert.match(body, /仓位矩阵/);
assert.match(body, /Group A/);
assert.match(body, /Group B/);
assert.match(body, /IF/);
assert.match(body, /IC/);
assert.ok(!body.includes('snapshot-tab-ls'));
assert.ok(!body.includes('暂无 LS'));

console.log('PASS: group snapshot renders a single matrix only');
