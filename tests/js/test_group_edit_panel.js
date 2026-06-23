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

document.registerElement('gt-tab-btns', domElement('gt-tab-btns'));
document.registerElement('gt-tab-actions', domElement('gt-tab-actions'));
document.registerElement('gt-panel-container', domElement('gt-panel-container'));
document.registerElement('gt-section-status', domElement('gt-section-status'));
document.registerElement('edit-group', domElement('edit-group'));

load('panels/list/selection-state.js');
load('registry/modes.js');
load('core/group-settings.js');
load('core/add-group-batch.js');

window.factorList = [{ alias: 'FactorA' }, { alias: 'FactorB' }];
window.ProductPathSelectionUtils = {
  selectionId: (selection) => selection ? String(selection.product_path_selection_id || selection.id || '') : '',
  selectionLabel: (selection) => selection ? String(selection.label || selection.name || selection.product_path_selection_id || '') : '',
  dedupe: (items) => {
    const seen = new Set();
    return items.filter((item) => {
      const id = window.ProductPathSelectionUtils.selectionId(item);
      if (!id || seen.has(id)) return false;
      seen.add(id);
      return true;
    });
  },
};

const ppsA = { product_path_selection_id: 'pps-a', label: '路径A', products: [{ name: 'IF' }] };
const ppsB = { product_path_selection_id: 'pps-b', label: '路径B', products: [{ name: 'IH' }] };

GT.backendSettings = {
  getProductPathSelections: () => [ppsA, ppsB],
  openLocalTab: () => true,
};

load('panels/add/group.js');
load('registry/tabs.js');
GT.tabs.init();

GT.groupSettings.groups.add({
  id: 'base-a1',
  name: '路径A_FactorA_5组_第1组',
  product_path_selection: ppsA,
  factorAlias: 'FactorA',
  splitCount: 5,
  groupIndex: 1,
  shortAlias: 'A1',
});
GT.groupSettings.groups.add({
  id: 'base-a2',
  name: '路径A_FactorA_5组_第2组',
  product_path_selection: ppsA,
  factorAlias: 'FactorA',
  splitCount: 5,
  groupIndex: 2,
  shortAlias: 'A2',
});
GT.groupSettings.groups.add({
  id: 'base-c1',
  name: '路径A_FactorB_4组_第1组',
  product_path_selection: ppsA,
  factorAlias: 'FactorB',
  splitCount: 4,
  groupIndex: 1,
  shortAlias: 'C1',
});
GT.groupSettings.groups.add({
  id: 'derived-a1',
  name: '派生',
  parentId: 'base-a1',
  productMask: { IF: true },
});
GT.groupSettings.addGroupBatch.rebuildFromGroups();

GT.tabs.enterEditMode(['base-a1']);
GT.tabs.mountTab('edit-group');

let base = GT.groupSettings.groups.get('base-a1');
assert.equal(base.shortAlias, 'A1');
assert.match(document.getElementById('edit-group').innerHTML, /产品路径/);
assert.match(document.getElementById('edit-group').innerHTML, /分组序号/);

function patchBase(patch) {
  const group = GT.groupSettings.groups.get('base-a1');
  const selection = patch.product_path_selection !== undefined ? patch.product_path_selection : group.product_path_selection;
  const factor = patch.factorAlias !== undefined ? patch.factorAlias : group.factorAlias;
  let splitCount = patch.splitCount !== undefined ? patch.splitCount : group.splitCount;
  let groupIndex = patch.groupIndex !== undefined ? patch.groupIndex : group.groupIndex;
  if (groupIndex > splitCount) splitCount = groupIndex;
  const letter = (() => {
    const groups = GT.groupSettings.groups.getAll().filter((item) => item.id !== group.id && !item.parentId);
    const same = groups.find((item) => (
      window.ProductPathSelectionUtils.selectionId(item.product_path_selection) === window.ProductPathSelectionUtils.selectionId(selection)
      && item.factorAlias === factor
      && item.splitCount === splitCount
    ));
    if (same && same.shortAlias) return same.shortAlias.match(/^([A-Z]+)/)[1];
    const used = new Set(groups.map((item) => (item.shortAlias || '').match(/^([A-Z]+)/)?.[1]).filter(Boolean));
    let code = 65;
    while (used.has(String.fromCharCode(code))) code += 1;
    return String.fromCharCode(code);
  })();
  const name = `${window.ProductPathSelectionUtils.selectionLabel(selection)}_${factor}_${splitCount}组_第${groupIndex}组`;
  GT.groupSettings.groups.update(group.id, {
    product_path_selection: selection,
    factorAlias: factor,
    splitCount,
    groupIndex,
    name,
    shortAlias: `${letter}${groupIndex}`,
    needsRegenerate: true,
  });
  GT.groupSettings.addGroupBatch.rebuildFromGroups();
  return GT.groupSettings.groups.get(group.id);
}

base = patchBase({ product_path_selection: ppsB });
assert.equal(base.shortAlias, 'B1');
assert.match(base.name, /路径B_FactorA_5组_第1组/);
assert.equal(GT.groupSettings.addGroupBatch.forGroup(base).name, 'B');

base = patchBase({ factorAlias: 'FactorB' });
assert.equal(base.shortAlias, 'B1');
assert.match(base.name, /路径B_FactorB_5组_第1组/);

base = patchBase({ splitCount: 6 });
assert.equal(base.shortAlias, 'B1');
assert.match(base.name, /路径B_FactorB_6组_第1组/);

base = patchBase({ groupIndex: 3 });
assert.equal(base.shortAlias, 'B3');
assert.match(base.name, /路径B_FactorB_6组_第3组/);

GT.groupSettings.groups.update('derived-a1', { shortAlias: 'A:1', name: '旧派生名' });
const descendants = GT.groupSettings.groups.getDescendants('base-a1');
descendants.filter((id) => id !== 'base-a1').forEach((id) => {
  GT.groupSettings.groups.update(id, {
    product_path_selection: base.product_path_selection,
    factorAlias: base.factorAlias,
    splitCount: base.splitCount,
    groupIndex: base.groupIndex,
    shortAlias: '',
    name: '',
    needsRegenerate: true,
  });
});
const derivedAfterCascade = GT.groupSettings.groups.get('derived-a1');
assert.equal(derivedAfterCascade.shortAlias, '');
assert.equal(derivedAfterCascade.name, '');
assert.equal(derivedAfterCascade.groupIndex, 3);

GT.tabs.enterEditMode(['base-a1', 'derived-a1']);
GT.tabs.mountTab('edit-group');
assert.match(document.getElementById('edit-group').innerHTML, /将修改 1 个基础组/);
assert.match(document.getElementById('edit-group').innerHTML, /edit-group-index/);

GT.tabs.enterEditMode(['base-a1', 'base-c1', 'derived-a1']);
GT.tabs.mountTab('edit-group');
assert.match(document.getElementById('edit-group').innerHTML, /将修改 2 个基础组/);
assert.doesNotMatch(document.getElementById('edit-group').innerHTML, /edit-group-index/);

GT.tabs.enterEditMode(['derived-a1']);
assert.doesNotMatch(
  document.getElementById('gt-tab-btns').innerHTML,
  /修改分组/,
);

console.log('PASS: group edit panel supports single-base structural edits and mixed selections');
