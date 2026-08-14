const assert = require("node:assert/strict");
const fs = require("node:fs");

global.window = globalThis;
for (const modulePath of process.argv.slice(2, -1)) {
  eval(fs.readFileSync(modulePath, "utf8"));
}

const expected = JSON.parse(fs.readFileSync(process.argv.at(-1), "utf8"));
assert.deepEqual(
  [...FTTestSettings.supportedControlTemplates].sort(),
  expected.sort(),
);
for (const control of expected) assert.equal(FTTestSettings.supportsControl(control), true);
assert.equal(FTTestSettings.supportsControl("unregistered-control"), false);
console.log("ok");
