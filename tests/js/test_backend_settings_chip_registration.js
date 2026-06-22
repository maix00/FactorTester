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
    'local-settings': [
      { key: 'target_allocation', label: '分配方式', mount_points: ['local-settings'], layout_template: 'settings-grid', order: 30 },
    ],
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
    allocation_policy: {
      value: 'inverse_volatility',
      tab_key: 'target_allocation',
      scope_policy: 'group_override',
      chip_template: '分配: {value}',
      options: [
        { value: 'inverse_volatility', label: '等风险' },
        { value: 'equal_notional', label: '等市值' },
      ],
    },
    volatility_lookback: {
      value: 20,
      tab_key: 'target_allocation',
      scope_policy: 'group_override',
      chip_template: '波动率窗口: {value}',
      options: [],
      visible_when: { allocation_policy: ['inverse_volatility'] },
    },
    position_policy: {
      value: 'rebalance_to_target',
      tab_key: 'position_policy',
      scope_policy: 'group_override',
      chip_template: '持仓: {value}',
      options: [
        { value: 'rebalance_to_target', label: '按目标调仓' },
        { value: 'buy_and_hold', label: '买入持有' },
      ],
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

global.fetch = (url) => Promise.resolve({
  ok: true,
  json: () => {
    if (String(url).indexOf('/tabs/target_allocation') >= 0) {
      return Promise.resolve({
        tab: indexManifest.tab_lists['local-settings'][0],
        settings: [
          Object.assign({ key: 'allocation_policy', label: '分配方式', control_template: 'select' }, indexManifest.defaults.allocation_policy),
          Object.assign({ key: 'volatility_lookback', label: '波动率回看期数', control_template: 'number' }, indexManifest.defaults.volatility_lookback),
        ],
      });
    }
    return Promise.resolve(indexManifest);
  },
});

load('core/backend-settings.js');

return GT.backendSettings.init().then(async () => {
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
  assert.ok(mountedConfigChips.some((chip) => chipPlainText(chip) === '流动性成交量参与率'));

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

  GT.backendSettings.applyFlatSnapshot({
    local_settings: {
      allocation_policy: 'equal_notional',
    },
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  const sparseRunPayload = GT.backendSettings.runPayload();
  assert.equal(sparseRunPayload.allocation_policy, 'equal_notional');
  assert.equal(sparseRunPayload.initial_capital, undefined);
  assert.equal(sparseRunPayload.base_currency, undefined);
  assert.equal(sparseRunPayload.currency_conversion_fee_rate, undefined);
  assert.equal(sparseRunPayload.start_date, undefined);
  assert.ok(sparseRunPayload._runtime_window);
  assert.deepEqual(GT.backendSettings._state.mountedTabs['group-settings'], []);
  const localChipText = document.getElementById('gt-local-settings-chip-row').childNodes
    .map((chip) => chip.innerHTML.replace(/<[^>]+>/g, ''));
  assert.ok(localChipText.some((text) => text === '分配等市值'));
  assert.ok(localChipText.every((text) => text.indexOf('波动率窗口') < 0));
  const hiddenVolatilityId = GT.groupSettings.groups.add({
    id: 'hidden-volatility-group',
    name: 'Hidden Volatility',
    testerId: 'tester-chip-order',
    factorAlias: 'FactorChipOrder',
    splitCount: 5,
    groupIndex: 3,
    allocation_policy: 'equal_notional',
    volatility_lookback: 5,
  });
  const hiddenVolatilityPayload = GT.backendSettings.groupPayloadForRun(GT.groupSettings.groups.get(hiddenVolatilityId));
  assert.equal(hiddenVolatilityPayload.allocation_policy, undefined);
  assert.equal(hiddenVolatilityPayload.volatility_lookback, undefined);
  assert.equal(GT.backendSettings.configChipForGroupKey(GT.groupSettings.groups.get(hiddenVolatilityId), 'volatility_lookback'), null);

  const defaultPositionId = GT.groupSettings.groups.add({
    id: 'position-default-group',
    name: 'Position Default',
    testerId: 'tester-chip-order',
    factorAlias: 'PositionFactor',
    splitCount: 2,
    groupIndex: 1,
  });
  const buyHoldPositionId = GT.groupSettings.groups.add({
    id: 'position-buy-hold-group',
    name: 'Position Buy Hold',
    testerId: 'tester-chip-order',
    factorAlias: 'PositionFactor',
    splitCount: 2,
    groupIndex: 2,
    position_policy: 'buy_and_hold',
  });
  const defaultPositionChip = GT.backendSettings.configChipForGroupKey(GT.groupSettings.groups.get(defaultPositionId), 'position_policy');
  const buyHoldPositionChip = GT.backendSettings.configChipForGroupKey(GT.groupSettings.groups.get(buyHoldPositionId), 'position_policy');
  assert.equal(chipPlainText(defaultPositionChip), '持仓按目标调仓');
  assert.equal(chipPlainText(buyHoldPositionChip), '持仓买入持有');

  console.log('PASS: backend settings owns field and chip registration');
});
