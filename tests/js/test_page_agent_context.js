const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/profile/page-agent-context.js", "utf8"),
  {filename: "page-agent-context.js"},
);

(async () => {
  let document = {source: "old"};
  let delivered = false;
  const calls = [];
  const context = {
    tabID: "factor-new",
    assistance: {
      snapshot: () => ({schema_version: 1, revision: 0, document}),
      apply: value => { document = value.document; },
    },
    api: async (url, options = {}) => {
      calls.push({url, options});
      if (options.method === "POST") return {success: true};
      if (delivered) return {actions: []};
      delivered = true;
      return {applications: [{
        sequence: 1, kind: "replace_document", expected_revision: 0,
        document: {source: "new"},
      }]};
    },
  };
  const bridge = window.FTPageAgentContext.create(
    context, "self-profile", context.assistance,
  );
  await bridge.syncOnce();
  bridge.dispose();

  assert.equal(document.source, "new");
  assert.equal(calls.filter(call => call.options.method === "POST").length, 3);
  assert(calls.some(call => call.url.endsWith("/acknowledge")));
  console.log("PASS: CLI atomically replaces the registered page document");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
