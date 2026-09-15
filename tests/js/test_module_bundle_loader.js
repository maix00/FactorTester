// A route loads one bundle per group; a container without bundles still works
// by falling back to the declared files, and the decision sticks for the page.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const requests = [];
let failBundles = false;

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
  groups: {alpha: ['app/one.js', 'app/two.js'], beta: ['app/three.js']},
  group_dependencies: {},
  group_external_scripts: {},
  route_groups: {alpha: ['alpha']},
};

global.fetch = async url => ({
  ok: true,
  json: async () => manifest,
  status: 200,
  url,
});

// Intercept script insertion: onload normally, onerror for bundles when the
// simulated container predates them.
const originalAppend = head.append.bind(head);
head.append = script => {
  requests.push(script.src);
  const isBundle = script.src.includes('__group__');
  originalAppend(script);
  if (isBundle && failBundles) script.onerror?.();
  else script.onload?.();
};

vm.runInThisContext(
  fs.readFileSync('server/manager/web/core/module-loader.js', 'utf8'),
);

(async () => {
  await window.FTStaticLoader.loadGroups(['alpha']);
  assert.deepEqual(requests, [
    '/research-static/__group__/alpha?v=rev-1',
  ], 'a group is one request');

  // Loading the same group again reuses the resolved promise.
  await window.FTStaticLoader.loadGroups(['alpha']);
  assert.equal(requests.length, 1);

  // A container without bundles: the declared files load instead, and the
  // decision is remembered for the rest of the page.
  requests.length = 0;
  failBundles = true;
  await window.FTStaticLoader.loadGroups(['beta']);
  // The bundle is retried while the container responds, then the loader gives
  // up on bundles and loads the declared files.
  assert.ok(requests[0].includes('__group__/beta'), 'bundle is attempted first');
  assert.equal(requests.at(-1), '/research-static/app/three.js?v=rev-1');
  assert.equal(
    requests.filter(url => !url.includes('__group__')).length, 1,
    'each declared file loads exactly once',
  );

  requests.length = 0;
  await window.FTStaticLoader.loadGroups(['beta']);
  assert.deepEqual(requests, [], 'already loaded groups are not refetched');

  console.log('MODULE BUNDLE LOADER: bundle first, file fallback PASSED');
})();
