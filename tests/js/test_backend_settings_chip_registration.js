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

const indexManifest = {
  schema_version: 1,
  application: 'group_test',
  tab_lists: {
    'local-settings': [],
    'group-settings': [
      { key: 'liquidity', label: '流动性', mount_points: ['group-settings'], layout_template: 'settings-grid', order: 50 },
    ],
  },
  default_mounted_tabs: {
    'local-settings': [],
    'group-settings': [],
  },
  defaults: {
    liquidity_mode: {
      value: 'infinite',
      tab_key: 'liquidity',
      scope_policy: 'group_override',
      chip_template: '流动性: {value}',
      options: [
        { value: 'infinite', label: '无限流动性' },
        { value: 'volume_participation', label: '成交量参与率' },
      ],
    },
    participation_rate: {
      value: 0.1,
      tab_key: 'liquidity',
      scope_policy: 'group_override',
      chip_template: '参与率: {value}',
      options: [],
    },
  },
  chip_fields: [
    {
      key: 'factor_alias',
      label: '因子',
      category: 'identity',
      chip_template: '{factorAlias}',
      source_keys: ['factorAlias'],
      order: 10,
      inherit_from_root: true,
      value_resolvers: {},
      clickable: false,
    },
    {
      key: 'product_mask',
      label: '品种范围',
      category: 'derived',
      chip_template: '📋 {productCount}品种 {expandSymbol}',
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
};

global.fetch = () => Promise.resolve({
  ok: true,
  json: () => Promise.resolve(indexManifest),
});

load('core/backend-settings.js');

return GT.backendSettings.init().then(() => {
  load('panels/list/selection-state.js');
  load('core/group-settings.js');

  GT.tabs = {
    registerPanel() {},
    refreshTabBar() {},
  };
  GT.backendSettings.attachGroupTabs();

  window.submissions = [{
    id: 'tester-chip-order',
    products: [
      { name: 'IF', desc: '股指' },
      { name: 'RB', desc: '螺纹钢' },
    ],
  }];

  const baseId = GT.groupSettings.groups.add({
    id: 'chip-order-group',
    name: 'Chip Order Group',
    testerId: 'tester-chip-order',
    factorAlias: 'FactorChipOrder',
    splitCount: 5,
    groupIndex: 1,
    liquidity_mode: 'volume_participation',
    participation_rate: 0.02,
  });
  const childId = GT.groupSettings.groups.add({
    id: 'chip-order-child',
    name: 'Child',
    parentId: baseId,
    productMask: { IF: true },
  });

  const configChips = GT.backendSettings.getAllChips(GT.groupSettings.groups.get(baseId), 'config');
  assert.ok(configChips.some((chip) => chip.html === '流动性: 成交量参与率'));
  assert.ok(configChips.some((chip) => chip.html === '参与率: 0.02'));

  const identityChips = GT.backendSettings.getAllChips(GT.groupSettings.groups.get(baseId), 'identity');
  assert.ok(identityChips.some((chip) => chip.html === 'FactorChipOrder'));

  const derivedChips = GT.backendSettings.getAllChips(GT.groupSettings.groups.get(childId), 'derived');
  assert.ok(derivedChips.some((chip) => chip.html.indexOf('1品种') >= 0 && chip.clickable));

  console.log('PASS: backend settings owns field and chip registration');
});
