const { assert, MockElement, resetGroupTest, registerConfigFields, load } = require('./group_test_harness');

const GT = resetGroupTest();
load('panels/list/selection-state.js');
load('core/group-settings.js');
load('core/add-group-batch.js');
registerConfigFields(GT);
load('registry/group-settings.js');
load('registry/chips.js');
load('panels/list/helpers.js');
load('panels/list/render.js');
load('panels/list/events.js');
load('panels/list/index.js');

window.submissions = [{
  id: 'tester-layout',
  label: '测试器',
  products: [{ name: 'IF', desc: '沪深300' }],
}];

GT.groupSettings.groups.add({
  id: 'root-layout-a',
  name: 'Root A',
  testerId: 'tester-layout',
  factorAlias: 'FactorLayout',
  splitCount: 2,
  groupIndex: 1,
  shortAlias: 'A',
});
GT.groupSettings.groups.add({
  id: 'child-layout-a1',
  name: 'Root A:1',
  parentId: 'root-layout-a',
  productMask: { IF: true },
});
GT.groupSettings.groups.add({
  id: 'root-layout-b',
  name: 'Root B',
  testerId: 'tester-layout',
  factorAlias: 'FactorLayout',
  splitCount: 2,
  groupIndex: 2,
  shortAlias: 'B',
});

const container = document.registerElement('unified-group-list', new MockElement('unified-group-list'));
GT.panels.list.index.mount(container);

let columns = GT.panels.list.index.getSnapshotMatrixColumns();
assert.deepStrictEqual(columns.map((col) => col.label), ['A', 'B']);

GT.groupSettings.groups.toggleExpanded('root-layout-a');
columns = GT.panels.list.index.getSnapshotMatrixColumns();
assert.deepStrictEqual(columns.map((col) => col.label), ['A', 'A:1', 'B']);

GT.panels.list.index.unmount();
console.log('PASS: list panel snapshot columns follow expand state');
