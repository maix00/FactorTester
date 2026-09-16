// Entering the task list must show current tasks.  The list keeps a per-scope
// page cache so that scope tabs and pagination stay instant, but the entry
// call has to revalidate the active scope: tasks submitted from the CLI (or
// another session) otherwise stay invisible until the refresh button is used.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.listeners = {};
    this.dataset = {};
    this.style = {};
    this.hidden = false;
    this._text = '';
    const classes = new Set();
    this.classList = {add: n => classes.add(n), remove: n => classes.delete(n), contains: n => classes.has(n), toggle: n => classes.has(n)};
  }
  append(...kids) { kids.forEach(k => k && this.children.push(k)); }
  replaceChildren(...kids) { this.children = kids.filter(Boolean); }
  remove() {}
  setAttribute(k, v) { this[k] = v; }
  removeAttribute(k) { delete this[k]; }
  addEventListener(k, f) { this.listeners[k] = f; }
  removeEventListener(k, f) { if (this.listeners[k] === f) delete this.listeners[k]; }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  get textContent() { return this._text + this.children.map(c => c.textContent || '').join(''); }
  set textContent(v) { this._text = String(v); this.children = []; }
  click() { this.listeners.click?.({stopPropagation() {}}); }
}

global.window = global;
global.document = {body: new Element('body'), createElement: t => new Element(t)};
global.location = {search: ''};

const identity = () => new Element('span');
global.FTJobListFormat = {
  artifactCell: identity, date: identity, displayProfile: identity, formatBytes: identity,
  jobPort: identity, kindTitle: identity, scalar: identity, serverLabel: identity,
  statusCell: identity, statusPill: identity, table: () => ({shell: new Element('table')}),
  taskCell: identity, taskHash: identity, taskTitle: identity, text: v => String(v ?? ''),
};
global.FTTestPageTabs = {render: () => new Element('div')};
global.FTJobProgress = {stopProgress() {}};
global.FTUI = {
  loading: identity, empty: identity, refreshButton: identity,
  table: () => ({shell: new Element('table')}),
};

vm.runInThisContext(fs.readFileSync('server/manager/web/jobs/jobs.js', 'utf8'));

function context() {
  const api = [];
  return {
    calls: api,
    t: v => v,
    content: new Element('main'),
    toolbar: new Element('div'),
    tabSession: {},
    pageState: {register() {}},
    session: null,
    api: async path => { api.push(path); return {success: true, jobs: [], total: 0, page: 1, total_pages: 1}; },
    button: (label, handler, title) => new Element('button'),
    navigate() {}, activeNav() {}, setHeading() {},
    isRouteCurrent: () => true,
    loginRequiredView: () => new Element('div'),
  };
}

(async () => {
  // 1. Entering the page reads the active scope once.
  const first = context();
  await FTJobs.list(first);
  assert.equal(first.calls.length, 1, 'entry must read the task list');
  assert.match(first.calls[0], /scope=server/, 'default scope is the server feed');

  // 2. Staying on the page (scope tabs / pagination) reuses the cached page.
  await FTJobs.list(first);
  assert.equal(first.calls.length, 1, 'a repeat render inside one visit must reuse the cache');

  // 3. Entering the page again revalidates instead of trusting the cache.
  await FTJobs.list(first, null, null, {revalidate: true});
  assert.equal(first.calls.length, 2, 'entry must revalidate the active scope');
  assert.match(first.calls[1], /scope=server/, 'revalidation keeps the active scope');

  // 4. The scope the visitor selected survives the revalidation.
  const scoped = context();
  global.location.search = '?scope=mine';
  await FTJobs.list(scoped, null, null, {revalidate: true});
  assert.match(scoped.calls[0], /scope=mine/, 'the URL scope is honoured on entry');
  global.location.search = '';

  // 5. The coordinator is the entry point and must ask for that revalidation.
  const coordinatorSource = fs.readFileSync('server/manager/web/app/coordinator.js', 'utf8');
  assert.match(
    coordinatorSource,
    /FTJobs\.list\(pageContext,[^)]*\{revalidate: true\}/,
    'the page handler must enter the list with revalidate: true',
  );

  console.log('test_jobs_entry_refresh: ok');
})().catch(error => { console.error(error); process.exit(1); });
