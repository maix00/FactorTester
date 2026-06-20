const { assert, resetGroupTest, registerConfigFields, load } = require('./group_test_harness');

const GT = resetGroupTest();
load('panels/list/selection-state.js');
load('core/group-settings.js');
registerConfigFields(GT);
load('registry/group-settings.js');
load('registry/chips.js');

window.submissions = [{
  id: 'tester-1',
  products: [
    { name: 'IF', desc: '股指' },
    { name: 'RB', desc: '螺纹钢' },
    { name: 'CU', desc: '铜' },
  ],
}];

const baseId = GT.groupSettings.groups.add({
  id: 'base-a',
  name: 'A',
  testerId: 'tester-1',
  factorAlias: 'FactorA',
  splitCount: 5,
});
const parentId = GT.groupSettings.groups.add({
  id: 'derived-parent',
  name: 'Parent',
  parentId: baseId,
  productMask: { IF: true, RB: true },
});
const childId = GT.groupSettings.groups.add({
  id: 'derived-child',
  name: 'Child',
  parentId: parentId,
  productMask: { RB: true },
});

const parentChips = window.GT_CONFIG_REGISTRY.getAllChips(GT.groupSettings.groups.get(parentId), 'derived');
const childChips = window.GT_CONFIG_REGISTRY.getAllChips(GT.groupSettings.groups.get(childId), 'derived');

assert.strictEqual(parentChips[0].html.includes('2品种'), true);
assert.strictEqual(childChips[0].html.includes('1品种'), true);

console.log('PASS: derived product chips resolve products through parent derived masks');
