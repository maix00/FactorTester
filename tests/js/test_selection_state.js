const { assert, resetGroupTest, load } = require('./group_test_harness');

const GT = resetGroupTest();
load('panels/list/selection-state.js');
load('core/group-settings.js');

GT.groupSettings.groups.add({
  id: 'base-select',
  name: 'Select',
  testerId: 'tester-select',
  product_path_selection: {
    product_path_selection_id: 'pps-select',
    label: '选择测试路径',
    products: [{ name: 'IF' }],
  },
  factorAlias: 'FactorSelect',
  splitCount: 2,
  groupIndex: 1,
});
GT.groupSettings.groups.add({
  id: 'derived-select',
  name: 'Select:1',
  parentId: 'base-select',
});

let eventCount = 0;
GT.events.on('selectionChanged', () => { eventCount += 1; });

GT.panels.list.selection.add('derived-select');
assert.strictEqual(GT.panels.list.selection.getFirst(), 'derived-select');
assert.strictEqual(GT.panels.list.selection.getFirstBaseGroup().id, 'base-select');
assert.strictEqual(GT.panels.list.selection.getFirstProductPathSelectionId(), 'pps-select');
assert.strictEqual(GT.panels.list.selection.getFirstFactorAlias(), 'FactorSelect');
assert.strictEqual(eventCount, 1);

GT.panels.list.selection.clear();
assert.strictEqual(GT.panels.list.selection.count(), 0);

console.log('PASS: selection state derives active tester/factor from selected group');
