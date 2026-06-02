const { assert, resetGroupTest, registerConfigFields, load } = require('./group_test_harness');

const GT = resetGroupTest();
load('panels/list/selection-state.js');
load('core/group-settings.js');
registerConfigFields(GT);

let emitted = 0;
GT.events.on('groupsChanged', () => { emitted += 1; });

const baseId = GT.groupSettings.groups.add({
  id: 'base-a',
  name: 'A',
  testerId: 'tester-1',
  factorAlias: 'FactorA',
  groupCount: 5,
  groupIndex: 1,
  feeMode: 'uniform',
  feeRate: 0.0003,
  rebalanceMode: 'each_period',
  liquidityMode: 'percent',
  liquidityPercent: 10,
});
const childId = GT.groupSettings.groups.add({
  id: 'base-a-1',
  name: 'A:1',
  isDerived: true,
  baseGroupId: baseId,
  parentId: null,
  productMask: { IF: true },
  feeMode: 'none',
  rebalanceMode: 'buy_and_hold',
});

assert.strictEqual(GT.groupSettings.groups.get(baseId).feeMode, 'uniform');
assert.strictEqual(GT.groupSettings.groups.get(childId).feeMode, 'none');
assert.deepStrictEqual(GT.groupSettings.groups.getTree()[0].id, childId);
assert.strictEqual(GT.groupSettings.groups.displayKey(GT.groupSettings.groups.get(childId)), 'A:1');
assert.ok(emitted >= 2);

GT.groupSettings.groups.update(childId, { feeMode: 'per_product', feeMap: { IF: { open_ratio: 0.1 } } });
assert.strictEqual(GT.groupSettings.groups.get(childId).feeMode, 'per_product');
assert.deepStrictEqual(GT.groupSettings.groups.getDescendants(baseId), [baseId]);

GT.groupSettings.cache.setLastGrossData([{ key: 'G1' }]);
GT.groupSettings.cache.setCurrentGroupDetailIndex(2);
assert.deepStrictEqual(GT.groupSettings.cache.getLastGrossData(), [{ key: 'G1' }]);
assert.strictEqual(GT.groupSettings.cache.getCurrentGroupDetailIndex(), 2);

console.log('PASS: groupSettings core stores group fields directly');
