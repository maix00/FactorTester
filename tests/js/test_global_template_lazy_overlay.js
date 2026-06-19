const assert = require('assert');
const path = require('path');

let domReady = null;
let observerCallback = null;
let fetchCount = 0;

const drawer = {
  classList: {
    open: false,
    contains(name) { return name === 'open' && this.open; },
  },
};
const list = {
  innerHTML: '',
  querySelectorAll() { return []; },
};

global.window = global;
global.factorFamilyAlias = 'MmRet';
global.document = {
  readyState: 'loading',
  addEventListener(name, callback) {
    if (name === 'DOMContentLoaded') domReady = callback;
  },
  getElementById(id) {
    if (id === 'global-tpl-drawer') return drawer;
    if (id === 'global-tpl-list') return list;
    return null;
  },
  createElement() {
    return { textContent: '', innerHTML: '' };
  },
  querySelectorAll() { return []; },
};
global.MutationObserver = class {
  constructor(callback) { observerCallback = callback; }
  observe() {}
};
global.fetch = () => {
  fetchCount += 1;
  return new Promise(() => {});
};

require(path.resolve(__dirname, '../../static/js/modules/single_factor_test/global_template_module.js'));

assert.strictEqual(fetchCount, 0, 'module evaluation must not preload the template list');
assert.ok(domReady, 'DOMContentLoaded handler should be registered');
domReady();
assert.strictEqual(fetchCount, 0, 'DOMContentLoaded must not preload the template list');

drawer.classList.open = true;
observerCallback();
observerCallback();
assert.strictEqual(fetchCount, 1, 'concurrent drawer-open callbacks must share one list request');

console.log('PASS: global template overlay lazily loads one list request');
