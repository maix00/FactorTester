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
      start_date: { key: 'start_date', value: '2026-01-01', tab_key: 'time', scope_policy: 'local_only' },
      end_date: { key: 'end_date', value: '2026-01-31', tab_key: 'time', scope_policy: 'local_only' },
      start_time: { key: 'start_time', value: '09:00', tab_key: 'time', scope_policy: 'local_only' },
      end_time: { key: 'end_time', value: '15:00', tab_key: 'time', scope_policy: 'local_only' },
      timezone: { key: 'timezone', value: 'Asia/Shanghai', tab_key: 'time', scope_policy: 'local_only' },
      time_precision: { key: 'time_precision', value: 'exact', tab_key: 'time', scope_policy: 'local_only' },
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
  assert.equal(runPayload.initial_capital, 123456);
  assert.equal(runPayload.allocation_policy, 'equal_notional');
  assert.equal(runPayload.rebalance_trigger, 'membership_change');
  assert.equal(runPayload.volatility_lookback, undefined);

  const groupPayload = GT.backendSettings.groupPayloadForRun(group);
  assert.equal(groupPayload.initial_capital, 123456);
  assert.equal(groupPayload.allocation_policy, 'inverse_volatility');
  assert.equal(groupPayload.volatility_lookback, 7);
  assert.equal(groupPayload.rebalance_trigger, 'membership_change');
  assert.equal(groupPayload.product_path_selection.product_path_selection_id, 'pps-run');

  console.log('PASS: backend settings run payload uses effective local and group values');
});
