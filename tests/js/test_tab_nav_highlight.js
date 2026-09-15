// A tab's stored feature-entry highlight must belong to that tab's route.
// Reading the DOM froze whatever entry was highlighted while the tab was still
// rendering, so 测试台 replayed 研究台 on every later switch.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function element(tag = 'div') {
  return {
    tagName: String(tag).toUpperCase(),
    children: [],
    dataset: {},
    classList: {add() {}, remove() {}, toggle() {}},
    style: {},
    append(...kids) { this.children.push(...kids); },
    replaceChildren(...kids) { this.children = kids; },
    querySelectorAll: () => [],
    querySelector: () => null,
    remove() {},
    setAttribute() {},
    addEventListener() {},
    get firstChild() { return this.children[0] || null; },
    get childNodes() { return this.children; },
  };
}

// The sidebar currently highlights 研究台, exactly like the reported case.
const navButtons = [
  Object.assign(element('button'), {dataset: {route: 'home'}}),
  Object.assign(element('button'), {dataset: {route: 'research'}, classList: {_active: true, add() {}, remove() {}, toggle() {}}}),
  Object.assign(element('button'), {dataset: {route: 'jobs'}}),
  Object.assign(element('button'), {dataset: {route: 'factors'}}),
];

global.window = global;
global.document = {
  body: element('body'),
  createElement: tag => element(tag),
  createDocumentFragment: () => element('#fragment'),
  querySelectorAll: selector => (
    selector === '.nav-button' ? navButtons : []
  ),
  querySelector: selector => {
    if (selector === '.nav-button.active') return navButtons[1];
    return null;
  },
  addEventListener() {},
};
global.location = {pathname: '/jobs', search: '?section=types', origin: 'https://x.invalid'};
global.MutationObserver = undefined;

vm.runInThisContext(fs.readFileSync('server/manager/web/app/navigation.js', 'utf8'));
vm.runInThisContext(fs.readFileSync('server/manager/web/app/tab-view-cache.js', 'utf8'));

const modules = [
  {id: 'home', title: '主页', path: '/', sidebarVisible: true},
  {id: 'research', title: '研究台', path: '/researches', sidebarVisible: true},
  {id: 'jobs', title: '测试台', path: '/jobs?section=types', sidebarVisible: true},
  {id: 'factors', title: '因子库', path: '/factors', sidebarVisible: true},
  {id: 'docs', title: '技术文档', path: '/docs', sidebarVisible: true},
  {id: 'ic-test', title: 'IC 测试', path: '/ic-test', sidebarVisible: false},
  {id: 'backtest', title: '回测', path: '/backtest', sidebarVisible: false},
  {id: 'factor-series', title: '查看因子序列', path: '/factor-series', sidebarVisible: false},
];

function cacheFor(path, {recorded, domRoute} = {}) {
  navButtons.forEach(button => { button.dataset.route = domRoute === undefined ? 'research' : domRoute; });
  const state = {
    tabs: [{id: 'tab-1', path}],
    activeTabID: 'tab-1',
    modules,
    tabSessions: new Map(),
  };
  const cache = window.FTTabViewCache.create({
    state,
    content: element('main'),
    title: element('h1'),
    eyebrow: element('small'),
    toolbar: element('header'),
    notice: element('p'),
    persistSession() {},
    restoreSession() {},
    removeSession() {},
    liveViewLimit: 2,
  });
  if (recorded !== undefined) cache.tabSession('tab-1').navRoute = recorded;
  cache.saveActiveTabSession();
  return state.tabSessions.get('tab-1').view.navRoute;
}

// Reported bug: the page chose 测试台 for this tab while the DOM still shows
// 研究台, so the saved view must keep 测试台.
assert.equal(cacheFor('/jobs?section=types', {recorded: 'jobs'}), 'jobs');
assert.equal(cacheFor('/jobs?section=types', {recorded: 'jobs', domRoute: 'factors'}), 'jobs');
// The other feature entries keep working.
assert.equal(cacheFor('/factors/families?scope=mine', {recorded: 'factors'}), 'factors');
// A page that deliberately clears the highlight keeps it clear, even though
// another entry is still highlighted in the DOM.
assert.equal(cacheFor('/docs', {recorded: '', domRoute: 'research'}), '');
assert.equal(cacheFor('/ic-test', {recorded: '', domRoute: 'research'}), '');
// A tab whose page never chose an entry falls back to the DOM value.
assert.equal(cacheFor('/factors', {}), 'research');

console.log('TAB NAV HIGHLIGHT: recorded per tab, DOM only as fallback PASSED');
