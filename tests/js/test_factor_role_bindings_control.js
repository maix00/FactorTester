const { assert, resetGroupTest, load } = require('./group_test_harness');

resetGroupTest();
load('core/factor-role-bindings-control.js');

const control = window.FactorRoleBindingsControl;
const setting = {
  serialization: {
    allowed_roles: ['ranking', 'screen', 'entry', 'exit', 'sizing'],
    roles_by_strategy_kind: {
      group: ['ranking', 'screen', 'sizing'],
      threshold: ['entry', 'exit'],
    },
  },
};

assert.deepEqual(
  control.normalizeBindings({ entry: 'EntryA', exit: { factorAlias: 'ExitB' }, sizing: '' }),
  { entry: 'EntryA', exit: 'ExitB' },
);
assert.deepEqual(control.visibleRoles(setting, 'group'), ['ranking', 'screen', 'sizing']);
assert.deepEqual(control.visibleRoles(setting, 'threshold'), ['entry', 'exit']);
assert.equal(
  control.displayValue({ entry: 'EntryA', exit: 'ExitB' }),
  '入场=EntryA · 退出=ExitB',
);
assert.equal(control.displayValue({}), '全部使用主因子');

console.log('factor role bindings control tests passed');
