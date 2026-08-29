const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

let imported = null;
let attached = null;
let current = {name: "old"};
let ready = false;
let profileReads = 0;
let afterApply = 0;
let bridgeStarts = 0;
let bridgeDisposals = 0;
let bridgeOptions = null;
let lifecycleRegistration = null;
let rebuilding = false;
global.window = {
  FTPageAgentProfiles: {self: async () => {
    profileReads += 1;
    return {profile_id: "self"};
  }},
  FTPageAgentDrawer: {attach: (_context, options) => { attached = options; }},
  FTPageAgentContext: {create: (_context, profileID, assistance) => {
    bridgeOptions = {profileID, assistance};
    return {
      start: async () => { bridgeStarts += 1; },
      dispose: () => { bridgeDisposals += 1; },
    };
  }},
};
global.structuredClone = value => JSON.parse(JSON.stringify(value));
vm.runInThisContext(
  fs.readFileSync("server/manager/web/profile/page-assistance.js", "utf8"),
  {filename: "page-assistance.js"},
);

(async () => {
  const context = {
    tabID: "tab-1", tabSession: {durable: {}}, t: value => value,
    isRouteCurrent: () => true,
    pageState: {register: (_id, adapter) => { lifecycleRegistration = adapter; }},
  };
  const controller = window.FTPageAssistance.register(context, {
    prepare: async () => { ready = true; },
    navigation: () => ({
      schema_version: 1, root_id: "page",
      nodes: {page: {id: "page", kind: "page", label: "Factor", children: []}},
    }),
    schema: () => ({type: "object"}),
    exportDocument: () => {
      assert.equal(ready, true, "the document is not exported before preparation");
      if (rebuilding) {
        throw new Error("document cannot be exported from transient imported state");
      }
      return current;
    },
    validate: document => {
      if (!document.name) throw new Error("name is required");
    },
    importDocument: document => {
      imported = document;
      current = document;
      rebuilding = true;
    },
    afterApply: () => {
      rebuilding = false;
      afterApply += 1;
    },
  }, {pageKind: "factor-create"});
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(profileReads, 1,
    "an active assisted page resolves its Profile without waiting for the drawer");
  assert.equal(bridgeStarts, 1,
    "the document receiver starts before the Agent drawer is opened");
  assert.equal(bridgeOptions.profileID, "self");
  assert.equal(bridgeOptions.assistance, controller);
  assert.equal(typeof attached.resolveProfile, "function");
  assert.equal((await attached.resolveProfile()).profile_id, "self");
  assert.equal(profileReads, 1, "the resolved Profile is shared with the drawer");
  await controller.prepare();
  assert.equal(controller.snapshot().revision, 0);
  assert.equal(controller.snapshot().navigation.root_id, "page");
  current = {name: "person edit"};
  assert.equal(controller.snapshot().revision, 1, "person edits advance the revision");
  await controller.apply({expected_revision: 1, document: {name: "new"}});
  assert.deepEqual(imported, {name: "new"});
  assert.equal(afterApply, 0, "page rebuilding is held until acknowledgement");
  await controller.afterAcknowledge({result: {success: true}});
  assert.equal(afterApply, 1);
  assert.equal(controller.snapshot().revision, 2);
  await controller.afterAcknowledge({result: {success: false}});
  assert.equal(afterApply, 1, "a rejected replacement never redraws page content");
  await assert.rejects(
    controller.apply({expected_revision: 1, document: {name: "stale"}}),
    /revision conflict/,
  );
  lifecycleRegistration.dispose();
  assert.equal(bridgeDisposals, 1,
    "the receiver stops only when the assisted page is reclaimed");
  console.log("PASS: structured assistance is atomic and auto-mounts its drawer");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
