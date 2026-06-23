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
      engine: { key: 'engine', value: 'native', tab_key: 'engine', scope_policy: 'local_only' },
      start_date: { key: 'start_date', value: '2026-01-01', tab_key: 'time', scope_policy: 'group_override' },
      end_date: { key: 'end_date', value: '2026-01-31', tab_key: 'time', scope_policy: 'group_override' },
      start_time: { key: 'start_time', value: '09:00', tab_key: 'time', scope_policy: 'group_override' },
      end_time: { key: 'end_time', value: '15:00', tab_key: 'time', scope_policy: 'group_override' },
      timezone: { key: 'timezone', value: 'Asia/Shanghai', tab_key: 'time', scope_policy: 'group_override' },
      time_precision: { key: 'time_precision', value: 'exact', tab_key: 'time', scope_policy: 'group_override' },
      calendar_frequency: { key: 'calendar_frequency', value: 'auto', tab_key: 'calendar', scope_policy: 'local_only' },
      initial_capital: { key: 'initial_capital', value: 100000000, tab_key: 'capital', scope_policy: 'group_override' },
      allocation_policy: { key: 'allocation_policy', value: 'inverse_volatility', tab_key: 'target_allocation', scope_policy: 'group_override' },
      volatility_lookback: {
        key: 'volatility_lookback',
        value: 20,
        tab_key: 'target_allocation',
        scope_policy: 'group_override',
        visible_when: { allocation_policy: ['inverse_volatility'] },
      },
      rebalance_trigger: { key: 'rebalance_trigger', value: 'on_factor_signal', tab_key: 'rebalance_trigger', scope_policy: 'group_override' },
      product_path_selection: { key: 'product_path_selection', value: null, tab_key: 'product_path_selection', scope_policy: 'group_override' },
    },
    chip_fields: [],
    tab_url_template: '/api/backtest/settings/group_test/tabs/{tab_key}',
  }),
});

load('core/group-settings.js');
load('core/backend-settings.js');

return GT.backendSettings.init().then(() => {
  GT.backendSettings._state.localValues.initial_capital = 123456;
  GT.backendSettings._state.localValues.allocation_policy = 'equal_notional';
  GT.backendSettings._state.localValues.volatility_lookback = 99;
  GT.backendSettings._state.localValues.rebalance_trigger = 'membership_change';

  const group = {
    id: 'g-run',
    name: 'G',
    product_path_selection: { product_path_selection_id: 'pps-run', label: '路径' },
    factorAlias: 'FactorRun',
    splitCount: 5,
    groupIndex: 1,
    allocation_policy: 'inverse_volatility',
    volatility_lookback: 7,
  };

  const runPayload = GT.backendSettings.runPayload();
  assert.deepEqual(runPayload.local_settings.initial_capital, 123456);
  assert.deepEqual(runPayload.local_settings.allocation_policy, 'equal_notional');
  assert.equal(runPayload.local_settings.start_date, undefined);
  assert.equal(runPayload.local_settings.end_date, undefined);
  assert.equal(runPayload.local_settings.time_precision, undefined);
  assert.equal(runPayload.initial_capital, undefined);
  assert.equal(runPayload.allocation_policy, undefined);
  assert.equal(runPayload.rebalance_trigger, undefined);
  assert.equal(runPayload.volatility_lookback, undefined);
  assert.equal(runPayload._runtime_window.start_date, '2026-01-01');
  assert.equal(runPayload._runtime_window.end_date, '2026-01-31');

  const groupPayload = GT.backendSettings.groupPayloadForRun(group);
  assert.equal(groupPayload.allocation_policy, 'inverse_volatility');
  assert.equal(groupPayload.volatility_lookback, 7);
  assert.equal(groupPayload.initial_capital, undefined);
  assert.equal(groupPayload.rebalance_trigger, undefined);
  assert.equal(groupPayload.product_path_selection.product_path_selection_id, 'pps-run');

  const inheritedGroup = {
    id: 'g-inherit',
    name: 'Inherit',
    product_path_selection: { product_path_selection_id: 'pps-run-2', label: '路径2' },
    factorAlias: 'FactorRun',
    splitCount: 5,
    groupIndex: 2,
    allocation_policy: 'equal_notional',
    volatility_lookback: 99,
  };
  const inheritedPayload = GT.backendSettings.groupPayloadForRun(inheritedGroup);
  assert.equal(inheritedPayload.allocation_policy, undefined);
  assert.equal(inheritedPayload.volatility_lookback, undefined);

  const explicitSignalWindow = {
    id: 'g-time-explicit',
    name: 'TimeExplicit',
    product_path_selection: { product_path_selection_id: 'pps-time', label: '路径时间' },
    factorAlias: 'FactorRun',
    splitCount: 5,
    groupIndex: 3,
    start_time: '00:00',
    end_time: '23:59',
    time_precision: 'exact',
    timezone: 'Asia/Shanghai',
    start_date: '2026-01-10',
    end_date: '2026-01-20',
  };
  const explicitSignalPayload = GT.backendSettings.groupPayloadForRun(explicitSignalWindow);
  assert.equal(explicitSignalPayload.start_date, '2026-01-10');
  assert.equal(explicitSignalPayload.end_date, '2026-01-20');
  assert.equal(explicitSignalPayload.start_time, '00:00');
  assert.equal(explicitSignalPayload.end_time, '23:59');
  assert.equal(explicitSignalPayload.time_precision, undefined);

  global.getSharedRuntimeTimeRange = () => ({
    start_date: '2025-02-01',
    end_date: '2025-02-28',
    start_time: '09:00',
    end_time: '15:00',
    timezone: 'Asia/Shanghai',
    is_trading_day: false,
  });
  window.BacktestTimeWindowSettings = {
    pageRuntimeTimeRangeValues: () => global.getSharedRuntimeTimeRange(),
  };
  GT.backendSettings.registerLocalDefaultProvider('page_time_range', () => global.getSharedRuntimeTimeRange());
  GT.groupSettings.groups.add(explicitSignalWindow);
  const groupedSignalWindowPayload = GT.backendSettings.runPayload();
  assert.equal(groupedSignalWindowPayload.local_settings.start_date, '2025-02-01');
  assert.equal(groupedSignalWindowPayload.local_settings.end_date, '2025-02-28');

  assert.deepEqual(
    GT.backendSettings.compactProductPathSelection({
      product_path_selection_id: 'runtime-pg',
      product_group_template_id: 'pg-template',
      label: '中国期货日盘',
      paths: ['Product/Futures/CNFutures/日夜盘/日盘'],
      products: [{ name: 'AP.CZC', desc: '苹果' }],
    }),
    { product_path_selection_id: 'pg-template' },
  );
  assert.deepEqual(
    GT.backendSettings.compactProductPathSelection({
      product_path_selection_id: 'manual-paths',
      label: '现场路径组',
      paths: ['A/Path', '-A/Path/_products/X.SHF'],
      products: [{ name: 'Y.SHF', desc: '测试' }],
    }),
    { product_path_selection_id: 'manual-paths', paths: ['A/Path', '-A/Path/_products/X.SHF'] },
  );

  console.log('PASS: backend settings run payload uses effective local and group values');
});
