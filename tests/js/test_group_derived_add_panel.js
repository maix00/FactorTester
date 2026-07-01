const { assert, MockElement, resetGroupTest, load } = require('./group_test_harness');

const GT = resetGroupTest();

function domElement(id) {
  const element = new MockElement(id);
  element.childNodes = [];
  element.children = element.childNodes;
  return element;
}

document.registerElement('gt-tab-btns', domElement('gt-tab-btns'));
document.registerElement('gt-tab-actions', domElement('gt-tab-actions'));
document.registerElement('gt-panel-container', domElement('gt-panel-container'));
document.registerElement('gt-section-status', domElement('gt-section-status'));
document.registerElement('add-derived', domElement('add-derived'));

load('panels/list/selection-state.js');
load('registry/modes.js');
load('core/group-settings.js');
load('core/add-group-batch.js');
load('panels/actions.js');
load('panels/add/derived.js');
load('registry/tabs.js');
GT.tabs.init();

GT.groupSettings.groups.add({
  id: 'base-derived',
  name: '基础组',
  product_path_selection: {
    product_path_selection_id: 'pps-derived',
    label: '路径',
    products: [
      { name: 'IF', desc: '沪深300' },
      { name: 'IH', desc: '上证50' },
    ],
  },
  factorAlias: 'FactorA',
  splitCount: 5,
  groupIndex: 1,
  shortAlias: 'A1',
});

GT.modes.enterAdd('derived');
GT.modes.setAddDraft({
  addFlow: 'derived',
  preselectedParentId: 'base-derived',
  preselectedParentLabel: 'A1',
});
GT.tabs.mountTab('add-derived');

const panelContainer = document.getElementById('gt-panel-container');
const panel = document.getElementById('add-derived');
assert.match(panelContainer.innerHTML, /add-derived/);
assert.match(panel.innerHTML, /品种筛选/);
assert.match(panel.innerHTML, /IF/);
assert.match(panel.innerHTML, /沪深300/);
assert.match(panel.innerHTML, /IH/);
assert.match(panel.innerHTML, /上证50/);

console.log('PASS: derived add panel renders product selector');
