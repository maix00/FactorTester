const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const attached = [];
global.setTimeout = callback => { callback(); return 0; };
global.window = {
  FTPageAgentDrawer: {
    attach: (context, options) => {
      attached.push(options.profile.profile_id);
      return {context, options};
    },
  },
};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/profile/page-agent-profiles.js", "utf8"),
  {filename: "page-agent-profiles.js"},
);

(async () => {
  const context = {
    api: async () => ({profiles: [
      {profile_id: "research-profile", profile_kind: "research"},
      {profile_id: "self-profile", profile_kind: "self"},
    ]}),
    isRouteCurrent: () => true,
    t: value => value,
    tabSession: {},
  };

  assert.equal((await window.FTPageAgentProfiles.self(context)).profile_id, "self-profile");
  assert.deepEqual(attached, []);
  assert.equal(
    (await window.FTPageAgentProfiles.bound(context, "profile:research-profile")).profile_id,
    "research-profile",
  );
  await assert.rejects(
    window.FTPageAgentProfiles.bound(context, "missing"),
    /研究报告绑定的 Profile 不可用/,
  );

  let transientCalls = 0;
  const transientContext = {
    ...context, tabSession: {},
    api: async () => {
      transientCalls += 1;
      if (transientCalls < 3) throw new TypeError("Failed to fetch");
      return {profiles: [{profile_id: "self-after-retry", profile_kind: "self"}]};
    },
  };
  assert.equal(
    (await window.FTPageAgentProfiles.self(transientContext)).profile_id,
    "self-after-retry",
  );
  assert.equal(transientCalls, 3, "transient Profile reads retry inside the shared boundary");

  let permissionCalls = 0;
  await assert.rejects(window.FTPageAgentProfiles.self({
    ...context, tabSession: {},
    api: async () => { permissionCalls += 1; throw new Error("HTTP 403"); },
  }), /HTTP 403/);
  assert.equal(permissionCalls, 1, "non-transient errors are not retried");

  console.log("PASS: non-report assistance uses self and reports keep bound profiles");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
