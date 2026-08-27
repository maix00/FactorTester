const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/profile/page-agent-context.js", "utf8"),
  {filename: "page-agent-context.js"},
);

(async () => {
  let source = "old";
  let delivered = false;
  const calls = [];
  const context = {
    tabID: "factor-new",
    pageState: {
      describe: () => ({
        schema_version: 1,
        sections: [{id: "editor", fields: [{key: "source", value: source}]}],
      }),
      apply: (section, action) => {
        assert.equal(section, "editor");
        source = action.value;
        return true;
      },
    },
    api: async (url, options = {}) => {
      calls.push({url, options});
      if (options.method === "POST") return {success: true};
      if (delivered) return {actions: []};
      delivered = true;
      return {actions: [{
        sequence: 1, section_id: "editor", action: {field: "source", value: "new"},
      }]};
    },
  };
  const bridge = window.FTPageAgentContext.create(context, "self-profile");
  await bridge.syncOnce();
  bridge.dispose();

  assert.equal(source, "new");
  assert.equal(calls.filter(call => call.options.method === "POST").length, 2);
  console.log("PASS: CLI page actions update registered browser fields");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
