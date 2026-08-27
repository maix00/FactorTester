const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

let imported = null;
let attached = null;
let current = {name: "old"};
let ready = false;
let profileReads = 0;
global.window = {
  FTPageAgentProfiles: {self: async () => {
    profileReads += 1;
    return {profile_id: "self"};
  }},
  FTPageAgentDrawer: {attach: (_context, options) => { attached = options; }},
};
global.structuredClone = value => JSON.parse(JSON.stringify(value));
vm.runInThisContext(
  fs.readFileSync("server/manager/web/profile/page-assistance.js", "utf8"),
  {filename: "page-assistance.js"},
);

(async () => {
  const context = {
    tabID: "tab-1", tabSession: {durable: {}}, t: value => value,
    // Nested Job result tabs can briefly report the outer route token as
    // inactive while their owned editor is already rendering.
    isRouteCurrent: () => false,
  };
  const controller = window.FTPageAssistance.register(context, {
    prepare: async () => { ready = true; },
    schema: () => ({type: "object"}),
    exportDocument: () => {
      assert.equal(ready, true, "the document is not exported before preparation");
      return current;
    },
    validate: document => {
      if (!document.name) throw new Error("name is required");
    },
    importDocument: document => { imported = document; current = document; },
  }, {pageKind: "factor-create"});
  assert.equal(profileReads, 0, "registration does not resolve a Profile eagerly");
  assert.ok(attached, "nested page registration must not lose its Agent trigger");
  assert.equal(typeof attached.resolveProfile, "function");
  assert.equal((await attached.resolveProfile()).profile_id, "self");
  assert.equal(profileReads, 1);
  await controller.prepare();
  assert.equal(controller.snapshot().revision, 0);
  current = {name: "person edit"};
  assert.equal(controller.snapshot().revision, 1, "person edits advance the revision");
  await controller.apply({expected_revision: 1, document: {name: "new"}});
  assert.deepEqual(imported, {name: "new"});
  assert.equal(controller.snapshot().revision, 2);
  await assert.rejects(
    controller.apply({expected_revision: 1, document: {name: "stale"}}),
    /revision conflict/,
  );
  console.log("PASS: structured assistance is atomic and auto-mounts its drawer");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
