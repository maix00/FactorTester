const { assert, resetGroupTest, registerConfigFields, load } = require('./group_test_harness');

const GT = resetGroupTest();
load('panels/list/selection-state.js');
load('core/group-settings.js');
registerConfigFields(GT);
load('registry/group-settings.js');

const id = GT.groupSettings.groups.add({
  id: 'base-b',
  name: 'B',
  testerId: 'tester-2',
  factorAlias: 'FactorB',
  splitCount: 3,
  feeMode: 'none',
  rebalance_trigger: 'membership_change',
  position_policy: 'rebalance_to_target',
});
GT.panels.list.selection.add(id);

window.GT_CONFIG_REGISTRY.register({
  name: 'fee',
  label: '费率',
  fields: ['feeMode', 'feeRate'],
  panel: {
    getChips(group) {
      return [{ label: 'fee', html: group.feeMode || 'none' }];
    },
  },
});

assert.strictEqual(window.GT_CONFIG_REGISTRY.getReferenceGroup().id, id);
assert.deepStrictEqual(window.GT_CONFIG_REGISTRY.getChips(GT.groupSettings.groups.get(id))[0].html, 'none');

window.GT_CONFIG_REGISTRY.setDirty('feeMode', 'uniform');
window.GT_CONFIG_REGISTRY.setDirty('feeRate', 0.0005);
assert.strictEqual(window.GT_CONFIG_REGISTRY.hasDirty(), true);
assert.strictEqual(window.GT_CONFIG_REGISTRY.commitDirty(), true);
assert.strictEqual(GT.groupSettings.groups.get(id).feeMode, 'uniform');
assert.strictEqual(GT.groupSettings.groups.get(id).feeRate, 0.0005);

console.log('PASS: config registry commits panel fields onto selected groups');
