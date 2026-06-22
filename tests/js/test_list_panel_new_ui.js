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
  id: 'tester-list',
  label: '测试器',
  products: [{ name: 'IF', desc: '沪深300' }],
}];

window.GT_CONFIG_REGISTRY.register({
  name: 'rebalance_trigger',
  fields: ['rebalance_trigger'],
  panel: {
    getChips(group) {
      return [{ label: 'rebalance', html: group.rebalance_trigger || 'on_factor_signal' }];
    },
  },
});
window.GT_CONFIG_REGISTRY.registerChipProvider({
  category: window.GT_CONFIG_REGISTRY.CHIP_CATEGORY.CONFIG,
  name: 'test-rebalance-trigger',
  getChips(group) {
    return [{ label: 'rebalance', html: group.rebalance_trigger || 'on_factor_signal' }];
  },
});

GT.groupSettings.groups.add({
  id: 'base-list',
  name: 'List',
  testerId: 'tester-list',
  factorAlias: 'FactorList',
  splitCount: 5,
  groupIndex: 1,
  shortAlias: 'A',
  rebalance_trigger: 'membership_change',
});
GT.groupSettings.groups.add({
  id: 'derived-list',
  name: 'List:1',
  parentId: 'base-list',
  productMask: { IF: true },
  rebalance_trigger: 'membership_change',
});

const container = document.registerElement('unified-group-list', new MockElement('unified-group-list'));
GT.panels.list.index.mount(container);

assert.match(container.innerHTML, /FactorList/);
assert.doesNotMatch(container.innerHTML, /rebalanceMode/);
assert.match(container.innerHTML, /显示设置/);
assert.doesNotMatch(container.innerHTML, /membership_change/);
assert.match(container.innerHTML, /List:1|A:1/);

GT.panels.list.index.setShowFullChips(true);
assert.match(container.innerHTML, /收起设置/);
assert.match(container.innerHTML, /membership_change/);

GT.panels.list.index.unmount();
console.log('PASS: new list panel renders from groupSettings and registry chips');
