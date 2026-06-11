const { assert, MockElement, resetGroupTest, registerConfigFields, load } = require('./group_test_harness');

const GT = resetGroupTest();
load('panels/list/selection-state.js');
load('core/group-settings.js');
registerConfigFields(GT);
load('registry/group-settings.js');
load('registry/chips.js');
load('panels/list/helpers.js');
load('panels/list/render.js');
load('panels/list/events.js');
load('panels/list/index.js');

window.submissions = [{
  id: 'tester-list',
  label: '测试器',
  products: [{ name: 'IF', desc: '沪深300' }],
}];

window.GT_CONFIG_REGISTRY.register({
  name: 'rebalance',
  fields: ['rebalanceMode'],
  panel: {
    getChips(group) {
      return [{ label: 'rebalance', html: group.rebalanceMode || 'each_period' }];
    },
  },
});

GT.groupSettings.groups.add({
  id: 'base-list',
  name: 'List',
  testerId: 'tester-list',
  factorAlias: 'FactorList',
  groupCount: 5,
  groupIndex: 1,
  shortAlias: 'A',
  rebalanceMode: 'each_period',
});
GT.groupSettings.groups.add({
  id: 'derived-list',
  name: 'List:1',
  parentId: 'base-list',
  productMask: { IF: true },
  rebalanceMode: 'each_period',
});

const container = document.registerElement('unified-group-list', new MockElement('unified-group-list'));
GT.panels.list.index.mount(container);

assert.match(container.innerHTML, /FactorList/);
assert.match(container.innerHTML, /each_period/);
assert.match(container.innerHTML, /List:1|A:1/);

GT.panels.list.index.unmount();
console.log('PASS: new list panel renders from groupSettings and registry chips');
