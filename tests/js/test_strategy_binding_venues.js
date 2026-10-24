// The editor models Nautilus Venue accounts and many-to-many strategy routes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.attributes = {};
    this.handlers = {};
    this.classList = {add() {}, remove() {}, toggle() {}};
    this.value = '';
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, callback) { this.handlers[name] = callback; }
  dispatch(name) { this.handlers[name]?.({target: this}); }
  click() { this.handlers.click?.({target: this}); }
}

global.window = global;
global.document = {createElement: name => new Element(name)};
global.FTTestInputState = {initialize(state) { if (!state.strategyBindings) state.strategyBindings = []; }};
global.FTUI = {empty: () => new Element('div')};
global.FTTestObjectPicker = {create: (_context, options) => ({element: new Element('div'), options})};
global.venuePickers = [];
global.FTMultiSelectFilter = {create: (_context, options) => {
  venuePickers.push(options);
  return {element: new Element('div'), options};
}};
global.FTTestFieldRow = {
  create: (label, control) => {
    global.nativeFieldLabels ||= [];
    global.nativeFieldLabels.push(label);
    const row = new Element('div');
    row.append(control);
    return row;
  },
};

vm.runInThisContext(
  fs.readFileSync('server/manager/web/workbench/strategy-binding-panel.js', 'utf8'),
);

function walk(element, predicate, found = []) {
  if (predicate(element)) found.push(element);
  for (const child of element.children || []) walk(child, predicate, found);
  return found;
}

function button(root, label) {
  return walk(root, item => item.tagName === 'button' && item.textContent === label)[0];
}

const state = {
  kind: 'backtest',
  values: {base_currency: 'CNY'},
  analysis: {groups: [
    {id: 'strategy:a', name: 'A', product_path_selection_id: 'scope:a'},
    {id: 'strategy:b', name: 'B', product_path_selection_id: 'scope:b'},
  ]},
};
const context = {
  t: value => value,
  button: (label, callback) => {
    const result = new Element('button');
    result.textContent = label;
    result.addEventListener('click', callback);
    return result;
  },
};
let root = window.FTStrategyBindingPanel.render(context, state);
assert.equal(state.analysis.venues.length, 0);
assert.equal(state.analysis.strategy_venue_bindings.length, 2);

button(root, '添加 Venue').click();
assert.equal(state.analysis.venues[0].name, 'VENUE1');
root = window.FTStrategyBindingPanel.render(context, state);
const venueID = walk(root, item => item.attributes?.['aria-label'] === 'Venue ID 1')[0];
const balance = walk(root, item => item.attributes?.['aria-label'] === 'Venue 初始余额 1')[0];
assert.ok(venueID && balance, 'Venue card exposes its native ID and starting balance');
venueID.value = 'CFFEX';
venueID.dispatch('change');
balance.value = '1000000';
balance.dispatch('change');

root = window.FTStrategyBindingPanel.render(context, state);
assert.equal(state.analysis.venues[0].name, 'CFFEX');
assert.equal(state.analysis.venues[0].account_type, 'MARGIN');
assert.equal(state.analysis.venues[0].oms_type, 'NETTING');
assert.equal(state.analysis.venues[0].starting_balance, '1000000');
assert.deepEqual(state.analysis.strategy_venue_bindings[0].venue_ids, ['CFFEX']);
assert.deepEqual(state.analysis.strategy_venue_bindings[1].venue_ids, ['CFFEX']);
assert.equal(venuePickers.at(-1).selected[0], 'CFFEX');

venuePickers.at(-1).onChange(['CFFEX']);
assert.deepEqual(state.analysis.strategy_venue_bindings[1].venue_ids, ['CFFEX']);
assert.equal(state.analysis.account_hierarchy, undefined, 'no FactorTester account tree is created');

function capabilityState(label) {
  return {
    kind: 'backtest', executionBackend: 'nautilus_trader',
    values: {base_currency: 'CNY'},
    analysis: {
      groups: [{id: `strategy:${label}`, name: label}],
      venues: [{name: 'CFFEX', account_type: 'MARGIN', oms_type: 'NETTING', starting_balances: ['100 CNY']}],
      strategy_venue_bindings: [],
    },
    nautilusCapabilities: {simulated_venue_config: {
      available: true,
      venue_identity: {label: `Venue ID ${label}`},
      venue_fields: [{path: 'starting_balances', label: `Balance ${label}`, type: 'money_array', default: []}],
      defaults: {routing: false},
      sections: [{id: 'matching', label: `Matching ${label}`}],
      fields: [{path: 'routing', label: `Routing ${label}`, type: 'boolean', section: 'matching', default: false}],
      excluded: {},
    }},
  };
}

global.nativeFieldLabels = [];
const firstServiceRoot = window.FTStrategyBindingPanel.render(context, capabilityState('8000'));
const secondServiceRoot = window.FTStrategyBindingPanel.render(context, capabilityState('8001'));
assert.ok(walk(firstServiceRoot, item => item.attributes?.['aria-label'] === 'Venue ID 8000 1').length);
assert.ok(walk(secondServiceRoot, item => item.attributes?.['aria-label'] === 'Venue ID 8001 1').length);
assert.ok(global.nativeFieldLabels.includes('Balance 8000'));
assert.ok(global.nativeFieldLabels.includes('Balance 8001'));
console.log('STRATEGY VENUE BINDING: one account per Venue, routes, and initial balance passed');
