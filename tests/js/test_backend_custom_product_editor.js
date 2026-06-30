const { assert, MockElement, resetGroupTest, load } = require('./group_test_harness');

const GT = resetGroupTest();
require('../../static/js/modules/shared/backend_settings_panel.js');

function domElement(id) {
  return new MockElement(id);
}

function findByText(node, text) {
  if (!node) return null;
  if (node.textContent === text) return node;
  const children = node.childNodes || [];
  for (let i = 0; i < children.length; i += 1) {
    const found = findByText(children[i], text);
    if (found) return found;
  }
  return null;
}

function findById(node, id) {
  if (!node) return null;
  if (node.id === id) return node;
  const children = node.childNodes || [];
  for (let i = 0; i < children.length; i += 1) {
    const found = findById(children[i], id);
    if (found) return found;
  }
  return null;
}

document.registerElement('gt-backtest-local-host', domElement('gt-backtest-local-host'));
document.registerElement('gt-local-settings-tab-bar', domElement('gt-local-settings-tab-bar'));
document.registerElement('gt-local-settings-chip-row', domElement('gt-local-settings-chip-row'));

global.fetch = (url) => Promise.resolve({
  ok: true,
  json: () => Promise.resolve(String(url).includes('/tabs/cost') ? {
    tab: { key: 'cost', label: '费用', layout_template: 'settings-grid' },
    settings: [{
      key: 'fee_custom_product_fields',
      label: '自定义费用字段',
      value: [],
      tab_key: 'cost',
      scope_policy: 'overridable',
      control_template: 'custom_product_overrides',
      visible_when: { engine_mode: ['custom'], fee_mode: ['custom'] },
      editable_when: { engine_mode: ['custom'], fee_mode: ['custom'] },
      serialization: {
        kind: 'custom_product_overrides',
        storage_key: 'custom_product_fields',
        module_filter: 'fee',
        fields: [{ value: 'OpenRatioByMoney', label: '开仓费率', unit: 'ratio', module: 'fee' }],
      },
    }],
  } : {
    schema_version: 1,
    application: 'group_test',
    tab_lists: {
      'local-settings': [{ key: 'cost', label: '费用', mount_points: ['local-settings'], layout_template: 'settings-grid', order: 100 }],
      'group-settings': [],
    },
    default_mounted_tabs: { 'local-settings': [], 'group-settings': [] },
    defaults: {
      engine_mode: {
        key: 'engine_mode',
        value: 'auto',
        tab_key: 'engine',
        scope_policy: 'overridable',
      },
      fee_mode: {
        key: 'fee_mode',
        value: 'auto',
        tab_key: 'cost',
        scope_policy: 'overridable',
        editable_when: { engine_mode: ['custom'] },
        default_when: { engine_mode: { auto: 'auto' } },
      },
      custom_product_fields: {
        key: 'custom_product_fields',
        value: [],
        tab_key: 'engine',
        scope_policy: 'overridable',
        control_template: 'custom_product_overrides',
        visible_when: { engine_mode: ['custom'] },
        editable_when: { engine_mode: ['custom'] },
        serialization: {
          kind: 'custom_product_overrides',
          storage_key: 'custom_product_fields',
          fields: [{ value: 'OpenRatioByMoney', label: '开仓费率', unit: 'ratio', module: 'fee' }],
        },
      },
      fee_custom_product_fields: {
        key: 'fee_custom_product_fields',
        label: '自定义费用字段',
        value: [],
        tab_key: 'cost',
        scope_policy: 'overridable',
        control_template: 'custom_product_overrides',
        visible_when: { engine_mode: ['custom'], fee_mode: ['custom'] },
        editable_when: { engine_mode: ['custom'], fee_mode: ['custom'] },
        serialization: {
          kind: 'custom_product_overrides',
          storage_key: 'custom_product_fields',
          module_filter: 'fee',
          fields: [{ value: 'OpenRatioByMoney', label: '开仓费率', unit: 'ratio', module: 'fee' }],
        },
      },
    },
    chip_fields: [],
    tab_url_template: '/api/backtest/settings/group_test/tabs/{tab_key}',
  }),
});

load('core/group-settings.js');
load('core/backend-settings.js');

GT.backendSettings.init().then(() => {
  GT.backendSettings._state.localValues.engine_mode = 'custom';
  GT.backendSettings._state.localValues.fee_mode = 'custom';
  assert.equal(GT.backendSettings.openLocalTab('cost'), true);
  return new Promise((resolve) => setTimeout(resolve, 0));
}).then(() => {
  const host = document.getElementById('gt-backtest-local-host');
  const addButton = findByText(host, '+ 字段');
  assert.ok(addButton, 'expected + 字段 button to be rendered');
  assert.equal(
    window.BackendSettingsPanel.customProductFieldLabel(
      GT.backendSettings._state.index.defaults.fee_custom_product_fields,
      'OpenRatioByMoney',
    ),
    '开仓费率',
  );
  assert.equal((GT.backendSettings._state.localValues.custom_product_fields || []).length, 0);
  addButton.listeners.click[0]({});
  const fieldSelect = findById(host, 'select');
  assert.ok(fieldSelect, 'expected field select to be rendered after adding a draft row');
  assert.equal(fieldSelect.childNodes[0].textContent, '开仓费率');
  assert.equal(fieldSelect.childNodes[0].title, 'ratio');
  assert.deepEqual(GT.backendSettings._state.localValues.custom_product_fields, [{
    product: '',
    field: 'OpenRatioByMoney',
    value: '',
  }]);
  console.log('PASS: backend custom product editor keeps added draft rows');
});
