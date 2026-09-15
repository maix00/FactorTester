const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

let attempts = 0;
const sources = [];
global.window = {};
global.document = {
  querySelector: () => ({content: "test-revision"}),
  createElement: () => ({dataset: {}, remove() {}}),
  head: {
    append(script) {
      attempts += 1;
      sources.push(script.src);
      if (attempts < 3) script.onerror();
      else script.onload();
    },
  },
};
// This fixture keeps the per-file path (a container without group bundles,
// also the loader's fallback) so the retry contract is unchanged there; the
// bundle-first path and its fallback are covered by tests/js/
// test_module_bundle_loader.js.
global.fetch = async () => ({
  ok: true,
  json: async () => ({
    group_bundles: false,
    group_dependencies: {},
    group_external_scripts: {},
    groups: {editor: ["catalog/factor-object-form.js"]},
  }),
});

vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: process.argv[2],
});

(async () => {
  await window.FTStaticLoader.loadGroups(["editor"]);
  assert.equal(attempts, 3, "one user action must survive two transient failures");
  assert.match(sources[0], /factor-object-form\.js\?v=test-revision$/);
  assert.match(sources[1], /factor-object-form\.js\?v=test-revision&retry=1$/);
  assert.match(sources[2], /factor-object-form\.js\?v=test-revision&retry=2$/);
  process.stdout.write("ok\n");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
