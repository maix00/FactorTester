const assert = require('assert');
const path = require('path');

const ROOT = path.resolve(__dirname, '../..');
const GROUP_TEST_ROOT = path.join(ROOT, 'static/js/modules/single_factor_test/group_test');

class MockElement {
  constructor(id) {
    this.id = id || '';
    this.value = '';
    this.innerHTML = '';
    this.textContent = '';
    this.style = {};
    this.className = '';
    this.listeners = {};
    this.classList = {
      _values: {},
      add: (name) => { this.classList._values[name] = true; },
      remove: (name) => { delete this.classList._values[name]; },
      toggle: (name) => {
        if (this.classList._values[name]) {
          delete this.classList._values[name];
          return false;
        }
        this.classList._values[name] = true;
        return true;
      },
    };
  }
  addEventListener(type, fn) {
    this.listeners[type] = this.listeners[type] || [];
    this.listeners[type].push(fn);
  }
  removeEventListener(type, fn) {
    this.listeners[type] = (this.listeners[type] || []).filter((item) => item !== fn);
  }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  closest() { return null; }
  appendChild() {}
  remove() { this.removed = true; }
  scrollIntoView() {}
  removeAttribute() {}
  getAttribute(name) { return this[name] || null; }
  setAttribute(name, value) { this[name] = value; }
  insertAdjacentHTML(_, html) { this.innerHTML += html; }
}

function createDocument() {
  const elements = {};
  return {
    body: new MockElement('body'),
    createElement: (tag) => new MockElement(tag),
    getElementById: (id) => elements[id] || null,
    querySelectorAll: () => [],
    addEventListener: () => {},
    registerElement: (id, el) => {
      elements[id] = el || new MockElement(id);
      return elements[id];
    },
  };
}

function clearModuleCache() {
  Object.keys(require.cache).forEach((key) => {
    if (key.indexOf(GROUP_TEST_ROOT) >= 0) delete require.cache[key];
  });
}

function load(relativePath) {
  return require(path.join(GROUP_TEST_ROOT, relativePath));
}

function resetGroupTest() {
  clearModuleCache();
  global.window = global;
  global.document = createDocument();
  global.alert = (message) => { throw new Error(String(message)); };
  global.confirm = () => true;
  global.DateUtils = {
    pad: (n) => String(n).padStart(2, '0'),
    getMaxDay: (year, month) => new Date(Number(year), Number(month), 0).getDate(),
  };
  global.submissions = [];
  delete global.GroupTest;
  delete global.GT_CONFIG_REGISTRY;
  load('bootstrap.js');
  return global.GroupTest;
}

function registerConfigFields(GT) {
  [
    { key: 'feeMode', type: 'string', default: 'none' },
    { key: 'feeRate', type: 'number', default: null },
    { key: 'feeMap', type: 'object', default: null },
    { key: 'feeSensitivity', type: 'number', default: 1 },
    { key: 'useCloseToday', type: 'boolean', default: false },
    { key: 'rebalanceMode', type: 'string', default: 'buy_and_hold' },
    { key: 'liquidityMode', type: 'string', default: 'infinite' },
    { key: 'liquidityPercent', type: 'number', default: 100 },
    { key: 'productMask', type: 'object', default: null },
    { key: 'products', type: 'object', default: null },
    { key: 'productNames', type: 'object', default: null },
  ].forEach((spec) => GT.groupSettings.registerField(spec));
}

if (require.main === module) {
  resetGroupTest();
  console.log('PASS: group_test_harness');
}

module.exports = {
  assert,
  MockElement,
  resetGroupTest,
  registerConfigFields,
  load,
};
