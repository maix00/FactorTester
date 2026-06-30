const { assert, MockElement, resetGroupTest, load } = require('./group_test_harness');

const GT = resetGroupTest();
require('../../static/js/modules/shared/chip_renderer.js');
require('../../static/js/modules/shared/backend_settings_panel.js');

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
      { key: 'time', label: '时间范围', mount_points: ['local-settings'], layout_template: 'settings-grid', order: 20 },
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
    start_date: {
      value: '2026-01-01',
      tab_key: 'time',
      scope_policy: 'local_only',
      chip_template: '开始: {value}',
      options: [],
    },
    end_date: {
      value: '2026-01-31',
      tab_key: 'time',
      scope_policy: 'local_only',
      chip_template: '结束: {value}',
      options: [],
    },
    start_time: {
      value: '09:00',
      tab_key: 'time',
      scope_policy: 'local_only',
      chip_template: '开始时刻: {value}',
      options: [],
      visible_when: { time_precision: ['exact'] },
    },
    end_time: {
      value: '15:00',
      tab_key: 'time',
      scope_policy: 'local_only',
      chip_template: '结束时刻: {value}',
      options: [],
      visible_when: { time_precision: ['exact'] },
    },
    time_precision: {
      value: 'exact',
      tab_key: 'time',
      scope_policy: 'local_only',
      chip_template: '精度: {value}',
      options: [
        { value: 'exact', label: '精确时间' },
        { value: 'trading_day', label: '交易日' },
      ],
    },
    timezone: {
      value: 'Asia/Shanghai',
      tab_key: 'time',
      scope_policy: 'local_only',
      chip_template: '时区: {value}',
      options: [
        { value: 'Asia/Shanghai', label: 'Asia/Shanghai (UTC+8)' },
        { value: 'UTC', label: 'UTC' },
      ],
      visible_when: { time_precision: ['exact'] },
    },
    liquidity_mode: {
      value: 'infinite',
      tab_key: 'liquidity',
      scope_policy: 'overridable',
      chip_template: '流动性: {value}',
      options: [
        { value: 'infinite', label: '无限流动性' },
        { value: 'volume_participation', label: '成交量参与率' },
      ],
    },
    participation_rate: {
      value: 0.1,
      tab_key: 'liquidity',
      scope_policy: 'overridable',
      chip_template: '参与率: {value}',
      options: [],
      visible_when: { liquidity_mode: ['volume_participation'] },
    },
    initial_capital: {
      value: 100000000,
      tab_key: 'capital',
      scope_policy: 'overridable',
      chip_template: '资金: {value}',
      options: [],
    },
    allocation_policy: {
      value: 'inverse_volatility',
      tab_key: 'target_allocation',
      scope_policy: 'overridable',
      chip_template: '分配: {value}',
      options: [
        { value: 'inverse_volatility', label: '等风险' },
        { value: 'equal_notional', label: '等市值' },
      ],
    },
    volatility_lookback: {
      value: 20,
      tab_key: 'target_allocation',
      scope_policy: 'overridable',
      chip_template: '波动率窗口: {value}',
      options: [],
      visible_when: { allocation_policy: ['inverse_volatility'] },
    },
    position_policy: {
      value: 'rebalance_to_target',
      tab_key: 'position_policy',
      scope_policy: 'overridable',
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
      chip_template: '因子: {factorAlias}',
      source_keys: ['factorAlias'],
      order: 10,
      inherit_from_root: true,
      value_resolvers: {},
      clickable: false,
    },
    {
      key: 'product_path_selection',
      label: '产品路径',
      category: 'identity',
      chip_template: '产品路径: {productPathSelectionLabel}',
      source_keys: ['product_path_selection'],
      order: 20,
      inherit_from_root: true,
      value_resolvers: {
        productPathSelectionLabel: 'product_path_selection_label',
      },
      clickable: true,
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
  ],
  tab_url_template: '/api/backtest/settings/group_test/tabs/{tab_key}',
};

let productGroupListCalls = 0;
let productGroupResolveCalls = 0;

global.fetch = (url) => Promise.resolve({
  ok: true,
  json: () => {
    if (String(url).indexOf('/api/product-groups/resolve') >= 0) {
      productGroupResolveCalls += 1;
      return Promise.resolve({
        groups: [{
          id: 'pg-day',
          name: '中国期货日盘',
          paths: ['Product/Futures/CNFutures/日夜盘/日盘'],
          products: [{ name: 'AP.CZC', desc: '苹果' }],
        }],
      });
    }
    if (String(url).indexOf('/api/product-groups') >= 0) {
      productGroupListCalls += 1;
      return Promise.resolve({
        groups: [{
          id: 'pg-day',
          name: '中国期货日盘',
          paths: ['Product/Futures/CNFutures/日夜盘/日盘'],
          products: [{ name: 'AP.CZC', desc: '苹果' }],
        }],
      });
    }
    if (String(url).indexOf('/tabs/time') >= 0) {
      return Promise.resolve({
        tab: indexManifest.tab_lists['local-settings'][0],
        settings: [
          Object.assign({ key: 'start_date', label: '开始日期', control_template: 'date' }, indexManifest.defaults.start_date),
          Object.assign({ key: 'end_date', label: '结束日期', control_template: 'date' }, indexManifest.defaults.end_date),
          Object.assign({ key: 'start_time', label: '开始时间', control_template: 'time' }, indexManifest.defaults.start_time),
          Object.assign({ key: 'end_time', label: '结束时间', control_template: 'time' }, indexManifest.defaults.end_time),
          Object.assign({ key: 'time_precision', label: '时间精度', control_template: 'select' }, indexManifest.defaults.time_precision),
          Object.assign({ key: 'timezone', label: '时区', control_template: 'select' }, indexManifest.defaults.timezone),
        ],
      });
    }
    if (String(url).indexOf('/tabs/target_allocation') >= 0) {
      return Promise.resolve({
        tab: indexManifest.tab_lists['local-settings'][1],
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
document.dispatchEvent = () => {};
global.CustomEvent = function CustomEvent(type, init) {
  return { type, detail: init && init.detail };
};
global.getSharedRuntimeTimeRange = () => ({
  start_date: '2025-05-06',
  end_date: '2025-05-30',
  start_time: '09:01',
  end_time: '14:59',
  timezone: 'Asia/Shanghai',
  is_trading_day: false,
});
window.BacktestTimeWindowSettings = {
  pageRuntimeTimeRangeValues: () => global.getSharedRuntimeTimeRange(),
};
window.SingleFactorGlobalSettings = {
  getDefaultValues: (keys) => {
    const values = global.getSharedRuntimeTimeRange();
    const out = {};
    keys.forEach((key) => {
      if (Object.prototype.hasOwnProperty.call(values, key)) out[key] = values[key];
    });
    return out;
  },
  sharedDefaultKeys: () => ['start_date', 'end_date', 'start_time', 'end_time', 'timezone', 'time_precision'],
};

return GT.backendSettings.init().then(async () => {
  load('panels/list/selection-state.js');
  load('core/group-settings.js');

  GT.tabs = {
    registerPanel() {},
    refreshTabBar() {},
  };
  GT.backendSettings.attachGroupTabs();

  assert.equal(GT.backendSettings._state.index.defaults.start_date.value, '2025-05-06');
  assert.equal(GT.backendSettings._state.index.defaults.end_date.value, '2025-05-30');
  assert.equal(GT.backendSettings._state.index.defaults.start_time.value, '09:01');
  assert.equal(GT.backendSettings._state.index.defaults.end_time.value, '14:59');
  assert.equal(GT.backendSettings.collectLocalSettings().start_date, undefined);
  assert.equal(GT.backendSettings.runPayload().local_settings.start_date, '2025-05-06');

  await GT.backendSettings.applyFlatSnapshot({
    local_settings: {
      start_date: '2024-01-02',
      end_date: '2024-01-31',
      start_time: '10:00',
      end_time: '14:30',
      time_precision: 'exact',
      timezone: 'Asia/Shanghai',
    },
  });
  assert.equal(GT.backendSettings.runPayload().local_settings.start_date, '2024-01-02');
  global.getSharedRuntimeTimeRange = () => ({
    start_date: '2025-09-01',
    end_date: '2025-09-30',
    start_time: '09:00',
    end_time: '15:00',
    timezone: 'UTC',
    is_trading_day: true,
  });
  assert.equal(
    GT.backendSettings.copyLocalDefaultsFromProvider('page_time_range', {
      blockOnUserKeys: ['start_date', 'end_date', 'start_time', 'end_time', 'timezone', 'time_precision'],
    }),
    false,
  );
  assert.equal(GT.backendSettings.runPayload().local_settings.start_date, '2024-01-02');
  assert.equal(GT.backendSettings.runPayload().local_settings.timezone, 'Asia/Shanghai');

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
    product_path_selection: {
      product_path_selection_id: 'tester-chip-order',
      products: [
        { name: 'IF', desc: '股指' },
        { name: 'RB', desc: '螺纹钢' },
      ],
    },
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
  const maskOnlyChildId = GT.groupSettings.groups.add({
    id: 'chip-order-mask-child',
    name: 'Mask Child',
    parentId: baseId,
    productMask: { IF: true },
  });
  const selectedSkipChildId = GT.groupSettings.groups.add({
    id: 'chip-order-selected-child',
    name: 'Selected Child',
    parentId: baseId,
    productMask: { IF: true },
  });

  const configChips = GT.backendSettings.getAllChips(GT.groupSettings.groups.get(baseId), 'config');
  assert.ok(configChips.some((chip) => chipPlainText(chip) === '流动性成交量参与率'));
  assert.ok(configChips.some((chip) => chipPlainText(chip) === '参与率0.02'));
  assert.ok(configChips.every((chip) => chip.html.indexOf('gt-backend-chip-value') >= 0));
  GT.groupSettings.groups.update(childId, {
    product_path_selection: {
      product_path_selection_id: 'tester-child-path',
      label: '子路径',
      products: [{ name: 'IC', desc: '中证' }],
    },
    factorAlias: 'FactorChild',
    splitCount: 7,
    groupIndex: 2,
  });
  let overrideTexts = GT.backendSettings.getOverrideChips(GT.groupSettings.groups.get(childId)).map(chipPlainText);
  assert.ok(overrideTexts.includes('因子FactorChild'));
  assert.ok(overrideTexts.includes('产品路径子路径'));
  assert.ok(overrideTexts.includes('分组2/7'));
  GT.groupSettings.groups.update(baseId, { factorAlias: 'FactorParentChanged' });
  overrideTexts = GT.backendSettings.getOverrideChips(GT.groupSettings.groups.get(childId)).map(chipPlainText);
  assert.ok(overrideTexts.includes('因子FactorChild'));
  GT.groupSettings.groups.update(baseId, {
    product_path_selection: {
      product_path_selection_id: 'tester-rb-only',
      label: '父路径变更',
      products: [{ name: 'RB', desc: '螺纹钢' }],
    },
  });
  GT.backendSettings.materializeChildDefaultsForChangedKeys(baseId, ['liquidity_mode'], { skipIds: [selectedSkipChildId] });
  assert.equal(GT.groupSettings.groups.get(maskOnlyChildId).liquidity_mode, 'infinite');
  assert.equal(GT.groupSettings.groups.get(selectedSkipChildId).liquidity_mode, null);
  assert.equal(
    GT.backendSettings.groupPayloadForRun(GT.groupSettings.groups.get(maskOnlyChildId)).liquidity_mode,
    'infinite',
  );
  overrideTexts = GT.backendSettings.getOverrideChips(GT.groupSettings.groups.get(maskOnlyChildId)).map(chipPlainText);
  assert.ok(overrideTexts.includes('品种范围0品种 ▸'));
  assert.ok(overrideTexts.includes('流动性无限流动性'));

  await GT.backendSettings.applyFlatSnapshot({
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
  assert.ok(identityChips.some((chip) => chipPlainText(chip) === '因子FactorParentChanged'));

  const compactSnapshot = {
    group_settings: {
      groups: [{
        id: 'compact-product-group',
        name: 'Compact Product Group',
        product_path_selection: { product_path_selection_id: 'pg-day' },
        factorAlias: 'FactorChipOrder',
        splitCount: 5,
        groupIndex: 1,
      }],
    },
  };
  await GT.backendSettings.resolveSnapshotProductPathReferences(compactSnapshot);
  assert.equal(productGroupResolveCalls, 1);
  assert.equal(productGroupListCalls, 0);
  assert.equal(compactSnapshot.group_settings.groups[0].product_path_selection.product_group, '中国期货日盘');
  GT.groupSettings.groups.add(compactSnapshot.group_settings.groups[0]);
  const compactIdentityChips = GT.backendSettings.getAllChips(GT.groupSettings.groups.get('compact-product-group'), 'identity');
  assert.ok(compactIdentityChips.some((chip) => chipPlainText(chip) === '产品路径中国期货日盘 · 产品组'));
  await GT.backendSettings.resolveSnapshotProductPathReferences({
    group_settings: { groups: [{ product_path_selection: { product_path_selection_id: 'pg-day' } }] },
  });
  assert.equal(productGroupResolveCalls, 1);

  const derivedChips = GT.backendSettings.getAllChips(GT.groupSettings.groups.get(childId), 'derived');
  assert.ok(derivedChips.some((chip) => chipPlainText(chip).indexOf('0品种') >= 0 && chip.clickable));

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
    product_path_selection: { product_path_selection_id: 'tester-chip-order' },
    factorAlias: 'FactorChipOrder',
    splitCount: 5,
    groupIndex: 2,
    liquidity_mode: 'infinite',
    participation_rate: 0.02,
  });
  const hiddenPayload = GT.backendSettings.groupPayloadForRun(GT.groupSettings.groups.get(hiddenDependentId));
  assert.equal(hiddenPayload.liquidity_mode, undefined);
  assert.equal(hiddenPayload.participation_rate, undefined);

  await GT.backendSettings.applyFlatSnapshot({
    local_settings: {
      allocation_policy: 'equal_notional',
    },
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  const sparseRunPayload = GT.backendSettings.runPayload();
  assert.equal(sparseRunPayload.local_settings.allocation_policy, 'equal_notional');
  assert.equal(sparseRunPayload.initial_capital, undefined);
  assert.equal(sparseRunPayload.base_currency, undefined);
  assert.equal(sparseRunPayload.currency_conversion_fee_rate, undefined);
  assert.equal(sparseRunPayload.start_date, undefined);
  assert.ok(sparseRunPayload.local_settings);
  assert.deepEqual(GT.backendSettings._state.mountedTabs['group-settings'], []);
  await GT.backendSettings.applyFlatSnapshot({
    local_settings: {
      start_date: '2025-04-01',
      end_date: '2025-04-30',
      time_precision: 'trading_day',
    },
  });
  const tradingDayPayload = GT.backendSettings.runPayload();
  assert.equal(tradingDayPayload.local_settings.start_date, '2025-04-01');
  assert.equal(tradingDayPayload.local_settings.end_date, '2025-04-30');
  assert.equal(tradingDayPayload.local_settings.time_precision, 'trading_day');
  assert.equal(tradingDayPayload.local_settings.start_time, undefined);
  assert.equal(tradingDayPayload.local_settings.end_time, undefined);
  assert.equal(tradingDayPayload.local_settings.timezone, undefined);
  assert.deepEqual(GT.backendSettings._state.mountedTabs['local-settings'], ['time']);

  await GT.backendSettings.applyFlatSnapshot({
    local_settings: {
      allocation_policy: 'equal_notional',
    },
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  const hiddenVolatilityId = GT.groupSettings.groups.add({
    id: 'hidden-volatility-group',
    name: 'Hidden Volatility',
    product_path_selection: { product_path_selection_id: 'tester-chip-order' },
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
    product_path_selection: { product_path_selection_id: 'tester-chip-order' },
    factorAlias: 'PositionFactor',
    splitCount: 2,
    groupIndex: 1,
  });
  const buyHoldPositionId = GT.groupSettings.groups.add({
    id: 'position-buy-hold-group',
    name: 'Position Buy Hold',
    product_path_selection: { product_path_selection_id: 'tester-chip-order' },
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
