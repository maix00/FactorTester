const { assert, MockElement, resetGroupTest, load } = require('./group_test_harness');

const GT = resetGroupTest();

function domElement(id) {
  const element = new MockElement(id);
  element.childNodes = [];
  element.children = element.childNodes;
  element.appendChild = (child) => {
    element.childNodes.push(child);
    return child;
  };
  return element;
}

document.registerElement('gt-backtest-local-host', domElement('gt-backtest-local-host'));
document.registerElement('gt-local-settings-tab-bar', domElement('gt-local-settings-tab-bar'));
document.registerElement('gt-local-settings-chip-row', domElement('gt-local-settings-chip-row'));

global.fetch = () => Promise.resolve({
  ok: true,
  json: () => Promise.resolve({
    schema_version: 1,
    application: 'group_test',
    tab_lists: { 'local-settings': [], 'group-settings': [] },
    default_mounted_tabs: { 'local-settings': [], 'group-settings': [] },
    defaults: {
      rebalance_trigger: {
        value: 'on_factor_signal',
        tab_key: 'rebalance_trigger',
        scope_policy: 'group_override',
        chip_template: '触发: {value}',
        options: [
          { value: 'on_factor_signal', label: '因子信号事件' },
          { value: 'membership_change', label: '成员变化事件' },
        ],
      },
      productMask: {
        value: null,
        tab_key: 'market_universe',
        scope_policy: 'group_override',
        chip_template: null,
        options: [],
      },
    },
    chip_fields: [
      {
        key: 'factor_alias',
        label: '因子',
        category: 'identity',
        chip_template: '因子: {factorAlias}',
        source_keys: ['factorAlias'],
        order: 10,
        inherit_from_root: true,
        value_resolvers: {},
        clickable: false,
      },
      {
        key: 'tester',
        label: '测试器',
        category: 'identity',
        chip_template: '测试器: {testerLabel}',
        source_keys: ['testerId'],
        order: 20,
        inherit_from_root: true,
        value_resolvers: { testerLabel: 'tester_label' },
        clickable: true,
      },
      {
        key: 'group_index',
        label: '分组序号',
        category: 'identity',
        chip_template: '分组: {groupIndex}/{splitCount}',
        source_keys: ['groupIndex', 'splitCount'],
        order: 30,
        inherit_from_root: true,
        value_resolvers: {},
        clickable: false,
      },
      {
        key: 'product_mask',
        label: '品种范围',
        category: 'derived',
        chip_template: '品种范围: {productCount}品种 {expandSymbol}',
        source_keys: ['productMask'],
        order: 40,
        inherit_from_root: false,
        value_resolvers: {
          productCount: 'product_mask_count',
          expandSymbol: 'product_mask_expand_symbol',
        },
        clickable: true,
      },
    ],
    tab_url_template: '/api/backtest/settings/group_test/tabs/{tab_key}',
  }),
});

load('core/backend-settings.js');

return GT.backendSettings.init().then(() => {
  load('panels/list/selection-state.js');
  load('core/group-settings.js');
  load('core/add-group-batch.js');
  GT.backendSettings.attachGroupTabs();
  load('panels/list/helpers.js');
  load('panels/list/render.js');
  load('panels/list/events.js');
  load('panels/list/index.js');

  window.submissions = [{
    id: 'tester-list',
    label: '测试器',
    products: [
      { name: 'IF', desc: '沪深300' },
      { name: 'IH', desc: '上证50' },
    ],
  }];

  GT.groupSettings.groups.add({
    id: 'base-list',
    name: 'List',
    testerId: 'tester-list',
    product_path_selection: {
      product_path_selection_id: 'pg-list',
      product_group_template_id: 'pg-list',
      product_group: '测试路径',
      label: '测试路径',
      products: [
        { name: 'IF', desc: '沪深300' },
        { name: 'IH', desc: '上证50' },
      ],
    },
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
  assert.match(container.innerHTML, /产品组/);
  assert.doesNotMatch(container.innerHTML, /rebalanceMode/);
  assert.match(container.innerHTML, /显示设置/);
  assert.doesNotMatch(container.innerHTML, /成员变化事件/);
  assert.match(container.innerHTML, /1\/5/);
  assert.match(container.innerHTML, /List:1|A:1/);

  GT.panels.list.index.setShowFullChips(true);
  assert.match(container.innerHTML, /收起设置/);
  assert.match(container.innerHTML, /成员变化事件/);
  assert.match(container.innerHTML, /1品种/);

  GT.panels.list.index.unmount();
  console.log('PASS: new list panel renders from backend-registered fields and chips');
});
