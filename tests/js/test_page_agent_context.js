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
    {now: () => clock, heartbeatMs: 1000},
  );
  let clock = 0;
  await bridge.syncOnce();
  const initialPublishes = calls.filter(call => (
    call.url.endsWith("/publish")
  )).length;
  clock = 999;
  await bridge.syncOnce();
  assert.equal(calls.filter(call => call.url.endsWith("/publish")).length,
    initialPublishes, "unchanged context is not republished before the heartbeat");
  clock = 1000;
  await bridge.syncOnce();
  assert.equal(calls.filter(call => call.url.endsWith("/publish")).length,
    initialPublishes + 1, "unchanged active context renews its server TTL");
  bridge.dispose();

  assert.equal(document.source, "new");
  assert.equal(calls.filter(call => call.url.endsWith("/acknowledge")).length, 1);
  assert(calls.some(call => call.url.endsWith("/acknowledge")));
  assert(calls.some(call => call.url.includes("&wait=20")));
  console.log("PASS: CLI atomically replaces the registered page document");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
