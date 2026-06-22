const { assert, MockElement, resetGroupTest, load } = require('./group_test_harness');

const GT = resetGroupTest();

function chipPlainText(chip) {
  return String(chip.html || '').replace(/<[^>]+>/g, '');
}

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
    engine: {
      value: 'native',
      tab_key: 'engine',
      scope_policy: 'local_only',
      chip_template: '引擎: {value}',
      options: [
        { value: 'native', label: 'Native' },
        { value: 'qlib', label: 'Qlib' },
      ],
    },
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
      visible_when: { liquidity_mode: ['volume_participation'] },
    },
    initial_capital: {
      value: 100000000,
      tab_key: 'capital',
      scope_policy: 'group_override',
      chip_template: '资金: {value}',
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
    engine: 'qlib',
    initial_capital: '',
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
  assert.ok(configChips.some((chip) => chipPlainText(chip) === '流动性成交量参与率'));
  assert.ok(configChips.some((chip) => chipPlainText(chip) === '参与率0.02'));
  assert.ok(configChips.every((chip) => chip.html.indexOf('gt-backend-chip-value') >= 0));

  GT.backendSettings.applyFlatSnapshot({
    group_settings: {
      groups: [{
        id: baseId,
        liquidity_mode: 'volume_participation',
        participation_rate: 0.02,
      }],
    },
  });
  const mountedConfigChips = GT.backendSettings.getAllChips(GT.groupSettings.groups.get(baseId), 'config');
  assert.equal(mountedConfigChips.length, 0);

  const identityChips = GT.backendSettings.getAllChips(GT.groupSettings.groups.get(baseId), 'identity');
  assert.ok(identityChips.some((chip) => chipPlainText(chip) === 'FactorChipOrder'));

  const derivedChips = GT.backendSettings.getAllChips(GT.groupSettings.groups.get(childId), 'derived');
  assert.ok(derivedChips.some((chip) => chipPlainText(chip).indexOf('1品种') >= 0 && chip.clickable));

  const flat = GT.backendSettings.flattenGroupForSnapshot(GT.groupSettings.groups.get(baseId));
  assert.equal(flat.engine, undefined);
  assert.equal(flat.initial_capital, undefined);
  assert.equal(flat.liquidity_mode, 'volume_participation');

  const runPayload = GT.backendSettings.groupPayloadForRun(GT.groupSettings.groups.get(baseId));
  assert.equal(runPayload.engine, undefined);
  assert.equal(runPayload.initial_capital, undefined);
  assert.equal(runPayload.liquidity_mode, 'volume_participation');

  const hiddenDependentId = GT.groupSettings.groups.add({
    id: 'hidden-dependent-group',
    name: 'Hidden Dependent',
    testerId: 'tester-chip-order',
    factorAlias: 'FactorChipOrder',
    splitCount: 5,
    groupIndex: 2,
    liquidity_mode: 'infinite',
    participation_rate: 0.02,
  });
  const hiddenPayload = GT.backendSettings.groupPayloadForRun(GT.groupSettings.groups.get(hiddenDependentId));
  assert.equal(hiddenPayload.liquidity_mode, undefined);
  assert.equal(hiddenPayload.participation_rate, undefined);

  console.log('PASS: backend settings owns field and chip registration');
});
