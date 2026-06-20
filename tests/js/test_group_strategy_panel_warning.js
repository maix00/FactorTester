const { assert, resetGroupTest, load } = require('./group_test_harness');

const GT = resetGroupTest();
load('results/strategy_panel.js');

document.registerElement('gt-layer-strategy');
document.registerElement('gt-strategy-status');
document.registerElement('gt-strategy-notice');
document.registerElement('gt-strategy-head');
document.registerElement('gt-strategy-body');

GT.results.strategyPanel.update(false, 'each_period', [], {
  capital_warning: '首期有 1 个组未能开出任何仓位。',
  capital_diagnostics: {
    blocked_group_count: 1,
    blocked_groups: [
      {
        group_name: '第一组',
        cheapest_product_name: 'TEST',
        cheapest_required_capital: 10000,
        budget_per_product: 1000,
      },
    ],
  },
});

const layer = document.getElementById('gt-layer-strategy');
const notice = document.getElementById('gt-strategy-notice').innerHTML;

assert.equal(layer.style.display, '');
assert.match(notice, /未开仓组数/);
assert.match(notice, /第一组/);
assert.match(notice, /TEST/);

console.log('PASS: group strategy panel shows capital warning');
