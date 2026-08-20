const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const values = new Map();
global.localStorage = {
  getItem: key => values.get(key) || null,
  setItem: (key, value) => values.set(key, value),
  removeItem: key => values.delete(key),
};
global.window = {};

vm.runInThisContext(
  fs.readFileSync("server/manager/web/app/tab-workspace.js", "utf8"),
  {filename: "tab-workspace.js"},
);

const alice = window.FTTabWorkspace.create({
  storage: localStorage,
  managerKey: "https://manager.example:7998",
  principalKey: "account:GTHT@Alice@1",
});
alice.save({
  tabs: [
    {id: "home", path: "/", title: "主页", icon: "house", closable: false},
    {id: "factor:1", path: "/factors/factor/1", title: "Factor A", icon: "fx", closable: true},
  ],
  activeTabID: "factor:1",
});

assert.deepStrictEqual(alice.restore(), {
  tabs: [
    {id: "home", path: "/", title: "主页", icon: "house", closable: false},
    {id: "factor:1", path: "/factors/factor/1", title: "Factor A", icon: "fx", closable: true},
  ],
  activeTabID: "factor:1",
});
alice.saveSession("factor:1", {scrollY: 41, durable: {draft: {name: "A"}}});
assert.deepStrictEqual(
  alice.restoreSession("factor:1"),
  {scrollY: 41, durable: {draft: {name: "A"}}},
);

const bob = window.FTTabWorkspace.create({
  storage: localStorage,
  managerKey: "https://manager.example:7998",
  principalKey: "account:GTHT@Bob@2",
});
assert.strictEqual(bob.restore(), null);

values.set(alice.storageKey(), JSON.stringify({schemaVersion: 999, tabs: []}));
assert.strictEqual(alice.restore(), null);
assert.strictEqual(values.has(alice.storageKey()), false);

console.log("ok");
