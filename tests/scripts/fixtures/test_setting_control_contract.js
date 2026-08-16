const assert = require("node:assert/strict");
const fs = require("node:fs");

global.window = globalThis;
for (const modulePath of process.argv.slice(2, -1)) {
  eval(fs.readFileSync(modulePath, "utf8"));
}

const expected = JSON.parse(fs.readFileSync(process.argv.at(-1), "utf8"));
for (const editor of expected) {
  assert.equal(FTTestSettings.supportsEditor(editor), true);
}
for (const editor of expected) assert.equal(FTTestSettings.supportsEditor(editor), true);
assert.equal(FTTestSettings.supportsEditor("unregistered-editor"), false);
console.log("ok");
