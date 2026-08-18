const assert = require("node:assert/strict");
const fs = require("node:fs");

global.window = globalThis;
for (const modulePath of process.argv.slice(2, -1)) {
  eval(fs.readFileSync(modulePath, "utf8"));
}

const expected = JSON.parse(fs.readFileSync(process.argv.at(-1), "utf8"));
for (const adapter of expected) {
  assert.equal(
    FTTestContentAdapters.supports({content_adapter: adapter}),
    true,
    `backend adapter is not registered in the Web renderer: ${adapter}`,
  );
}
assert.equal(
  FTTestContentAdapters.supports({content_adapter: "unregistered-adapter"}),
  false,
);
console.log("ok");
