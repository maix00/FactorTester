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
      productMask: {
        value: null,
        tab_key: 'market_universe',
        scope_policy: 'overridable',
        chip_template: null,
        options: [],
      },
    },
    chip_fields: [],
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
    id: 'tester-layout',
    label: '测试器',
    products: [{ name: 'IF', desc: '沪深300' }],
  }];

  GT.groupSettings.groups.add({
    id: 'root-layout-a',
    name: 'Root A',
    testerId: 'tester-layout',
    factorAlias: 'FactorLayout',
    splitCount: 2,
    groupIndex: 1,
    shortAlias: 'A',
  });
  GT.groupSettings.groups.add({
    id: 'child-layout-a1',
    name: 'Root A:1',
    parentId: 'root-layout-a',
    productMask: { IF: true },
  });
  GT.groupSettings.groups.add({
    id: 'root-layout-b',
    name: 'Root B',
    testerId: 'tester-layout',
    factorAlias: 'FactorLayout',
    splitCount: 2,
    groupIndex: 2,
    shortAlias: 'B',
  });

  const container = document.registerElement('unified-group-list', new MockElement('unified-group-list'));
  GT.panels.list.index.mount(container);

  let columns = GT.panels.list.index.getSnapshotMatrixColumns();
  assert.deepStrictEqual(columns.map((col) => col.label), ['A', 'B']);

  GT.groupSettings.groups.toggleExpanded('root-layout-a');
  columns = GT.panels.list.index.getSnapshotMatrixColumns();
  assert.deepStrictEqual(columns.map((col) => col.label), ['A', 'A:1', 'B']);

  GT.panels.list.index.unmount();
  console.log('PASS: list panel snapshot columns follow expand state');
});
