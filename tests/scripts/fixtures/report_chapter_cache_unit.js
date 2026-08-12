const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/report/chapter-cache.js", "utf8",
), {filename: "chapter-cache.js"});

const cache = window.FTReportChapterCache.create(2);
cache.set("a", 1);
cache.set("b", 2);
assert.strictEqual(cache.get("a"), 1);
cache.set("c", 3);
assert.strictEqual(cache.get("b"), undefined);
assert.strictEqual(cache.get("a"), 1);
assert.strictEqual(cache.get("c"), 3);
assert.strictEqual(cache.size, 2);
cache.clear();
assert.strictEqual(cache.size, 0);
console.log("ok");
