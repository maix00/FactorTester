// Switching tabs clears the live header toolbar before the target view is
// restored, so a save must not erase the actions a tab parked earlier -
// otherwise the report's header group disappears for good.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function element(tag = 'div') {
  const node = {
    tagName: String(tag).toUpperCase(),
    children: [],
    dataset: {},
    classList: {add() {}, remove() {}, toggle() {}},
    style: {},
    hidden: false,
    parent: null,
    append(...kids) {
      kids.forEach(kid => {
        if (!kid) return;
        const previous = kid.parent;
        if (previous && previous !== this) {
          const index = previous.children.indexOf(kid);
          if (index >= 0) previous.children.splice(index, 1);
        }
        kid.parent = this;
        this.children.push(kid);
      });
    },
    replaceChildren(...kids) {
      this.children.forEach(kid => { if (kid) kid.parent = null; });
      this.children = [];
      this.append(...kids);
    },
    querySelectorAll: () => [],
    querySelector: () => null,
    remove() {},
    setAttribute() {},
    addEventListener() {},
    get firstChild() { return this.children[0] || null; },
    get childNodes() { return this.children; },
  };
  return node;
}

global.window = global;
global.document = {
  body: element('body'),
  createElement: tag => element(tag),
  createDocumentFragment: () => element('#fragment'),
  querySelectorAll: () => [],
  querySelector: () => null,
  addEventListener() {},
};
global.location = {pathname: '/research/report-1', search: '', origin: 'https://x.invalid'};
global.MutationObserver = undefined;

vm.runInThisContext(
  fs.readFileSync('server/manager/web/app/tab-view-cache.js', 'utf8'),
);

function build(path) {
  const state = {
    tabs: [{id: 'tab-1', path, title: '报告'}],
    activeTabID: 'tab-1',
    modules: [],
    tabSessions: new Map(),
  };
  const toolbar = element('header');
  const content = element('main');
  const cache = window.FTTabViewCache.create({
    state,
    content,
    title: element('h1'),
    eyebrow: element('small'),
    toolbar,
    notice: element('p'),
    persistSession() {},
    restoreSession() {},
    removeSession() {},
    liveViewLimit: 2,
  });
  return {state, toolbar, content, cache};
}

// 1) The report page parks its header group.
const report = build('/jobs?section=types');
report.content.append(element('div'));
['刷新', '研究报告设置', '导出报告'].forEach(label => {
  const button = element('button');
  button.label = label;
  report.toolbar.append(button);
});
report.cache.saveActiveTabSession();
assert.equal(report.tabSession, undefined);
const parked = report.state.tabSessions.get('tab-1').view.toolbar;
assert.equal(parked.childNodes.length, 3);

// 2) A tab switch clears the live toolbar; saving again must keep the parked
//    actions instead of overwriting them with the empty shell.
report.toolbar.replaceChildren();
report.cache.saveActiveTabSession();
assert.equal(
  report.state.tabSessions.get('tab-1').view.toolbar.childNodes.length, 3,
  'an empty capture must not erase the parked header actions',
);

// 3) Restoring the tab brings the group back.
const restored = report.cache.restoreView('tab-1');
assert.equal(restored, 'live');
assert.equal(report.toolbar.childNodes.length, 3);
assert.deepEqual(
  report.toolbar.childNodes.map(node => node.label),
  ['刷新', '研究报告设置', '导出报告'],
);

// 4) A page that never had header actions stays without them.
const plain = build('/factors');
plain.content.append(element('div'));
plain.cache.saveActiveTabSession();
assert.equal(plain.toolbar.childNodes.length, 0);
assert.equal(plain.state.tabSessions.get('tab-1').view.toolbar.childNodes.length, 0);

console.log('TAB TOOLBAR PARKING: header group survives tab switches PASSED');
