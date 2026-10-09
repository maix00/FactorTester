// Route loading uses one dependency-ordered bundle for groups missing from
// this page, loads only their styles, and retains legacy fallbacks.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const requests = [];
let failGroupSets = false;
let failBundles = false;
let failHighlightAttempts = 0;

class Element {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.classList = {add() {}, remove() {}};
  }
  append(...kids) { this.children.push(...kids); }
  setAttribute(key, value) { this.attributes[key] = value; }
  remove() { this.removed = true; }
  addEventListener() {}
}

const head = new Element('head');
const documentShim = {
  head,
  createElement: tag => new Element(tag),
  querySelector: selector => (
    selector.includes('ft-client-assets-revision') ? {content: 'rev-1'} : null
  ),
  addEventListener() {},
};

global.window = global;
global.document = documentShim;
global.setTimeout = fn => { fn(); return 0; };

const manifest = {
  group_bundles: true,
  group_set_bundles: true,
  groups: {
    alpha: ['app/one.js', 'app/two.js'],
    beta: ['app/three.js'],
    gamma: ['app/four.js'],
    delta: ['app/five.js'],
    epsilon: ['app/six.js'],
  },
  group_dependencies: {beta: ['alpha'], gamma: ['alpha']},
  group_external_scripts: {beta: ['vendor/highlight/highlight.min.js']},
  group_styles: {
    alpha: ['styles/alpha.css'],
    beta: ['styles/beta.css'],
    gamma: ['styles/gamma.css'],
    delta: ['styles/delta.css'],
  },
  route_groups: {
    alpha: ['alpha'], beta: ['beta'], gamma: ['gamma'], delta: ['delta'],
    epsilon: ['epsilon'],
  },
};

global.fetch = async url => ({
  ok: true,
  json: async () => manifest,
  status: 200,
  url,
});

// Intercept dynamic tags. `async=false` scripts execute in insertion order;
// this shim records that order and simulates their load/error events.
const originalAppend = head.append.bind(head);
head.append = element => {
  const url = element.src || element.href;
  requests.push({tag: element.tag, url});
  originalAppend(element);
  const isGroupSet = url?.includes('__groups__/');
  const isBundle = url?.includes('__group__/');
  if (url?.includes('epsilon.min.js') && failHighlightAttempts > 0) {
    failHighlightAttempts -= 1;
    element.onerror?.();
  } else if ((isGroupSet && failGroupSets) || (isBundle && failBundles)) {
    element.onerror?.();
  } else {
    element.onload?.();
  }
};

vm.runInThisContext(
  fs.readFileSync('server/manager/web/core/module-loader.js', 'utf8'),
);

(async () => {
  await window.FTStaticLoader.ensureRoute('alpha');
  assert.deepEqual(requests.map(item => item.url), [
    '/research-static/styles/alpha.css?v=rev-1',
    '/research-static/__groups__/alpha?v=rev-1',
  ], 'initial route loads only its style and one bundle');

  requests.length = 0;
  await window.FTStaticLoader.ensureRoute('beta');
  assert.deepEqual(requests.map(item => item.url), [
    '/research-static/styles/beta.css?v=rev-1',
    '/research-static/vendor/highlight/highlight.min.js?v=rev-1',
    '/research-static/__groups__/beta?v=rev-1',
  ], 'loaded dependencies are omitted and external scripts precede group code');

  requests.length = 0;
  await window.FTStaticLoader.ensureRoute('beta');
  assert.deepEqual(requests, [], 'loaded groups, styles, and external scripts are reused');

  // If the combined code loads while its vendor script fails, the next route
  // entry retries the vendor instead of treating the group as fully ready.
  requests.length = 0;
  manifest.group_external_scripts.epsilon = ['vendor/epsilon.min.js'];
  failHighlightAttempts = 5;
  await assert.rejects(window.FTStaticLoader.ensureRoute('epsilon'));
  assert.ok(requests.some(item => item.url.includes('__groups__/epsilon')));
  requests.length = 0;
  await window.FTStaticLoader.ensureRoute('epsilon');
  assert.deepEqual(requests.map(item => item.url), [
    '/research-static/vendor/epsilon.min.js?v=rev-1',
  ], 'a retry loads the vendor even when its first-party bundle is already loaded');

  // A server with only per-group bundles: fail the combined request, then
  // retain the ordered legacy group bundle path.
  requests.length = 0;
  failGroupSets = true;
  await window.FTStaticLoader.ensureRoute('gamma');
  assert.ok(requests.some(item => item.url.includes('__groups__/gamma')));
  assert.ok(requests.some(item => item.url.includes('__group__/gamma')));
  assert.ok(!requests.some(item => item.url.endsWith('/app/four.js?v=rev-1')));

  // A still older container without either bundle endpoint falls back to its
  // declared per-file scripts after the per-group bundle fails.
  requests.length = 0;
  failBundles = true;
  await window.FTStaticLoader.ensureRoute('delta');
  assert.ok(!requests.some(item => item.url.includes('__groups__/delta')));
  assert.ok(requests.some(item => item.url.includes('__group__/delta')));
  assert.equal(requests.at(-1).url, '/research-static/app/five.js?v=rev-1');
  assert.equal(
    requests.filter(item => item.url.includes('/app/five.js')).length, 1,
    'each declared fallback file loads exactly once',
  );

  console.log('MODULE BUNDLE LOADER: route bundle, scoped styles, and legacy fallbacks PASSED');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
