const { assert, resetGroupTest, load } = require('./group_test_harness');

const GT = resetGroupTest();
load('results/strategy_panel.js');

document.registerElement('gt-layer-strategy');
document.registerElement('gt-strategy-status');
document.registerElement('gt-strategy-notice');
document.registerElement('gt-strategy-head');
document.registerElement('gt-strategy-body');

GT.results.strategyPanel.update(false, [], {
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
const body = document.getElementById('gt-strategy-body').innerHTML;

assert.equal(layer.style.display, '');
assert.match(body, /未开仓组数/);
assert.match(body, /第一组/);
assert.match(body, /TEST/);

GT.results.strategyPanel.update(false, [], {
  setting_fallback_warning: '当前执行引擎替换了 1 个不适用设置，已使用该引擎默认值继续回测。',
  setting_fallbacks: [{
    module: 'accounting',
    setting_key: 'money_unit_policy',
    requested_value: 'minor_units',
    applied_value: 'engine_native',
  }],
});

const fallbackBody = document.getElementById('gt-strategy-body').innerHTML;
assert.match(fallbackBody, /引擎设置/);
assert.match(fallbackBody, /accounting/);
assert.match(fallbackBody, /minor_units/);
assert.match(fallbackBody, /engine_native/);

console.log('PASS: group strategy panel shows capital warning');
