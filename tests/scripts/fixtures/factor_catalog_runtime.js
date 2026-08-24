const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.window = {};
window.FTFactorModel = {
  mergeFactorSets(serverItems, localItems) {
    return [...(serverItems || []), ...(localItems || [])];
  },
};
global.FTFactorModel = window.FTFactorModel;

vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-catalog-runtime.js", "utf8"),
  {filename: "factor-catalog-runtime.js"},
);

function deferred() {
  let resolve;
  const promise = new Promise(value => { resolve = value; });
  return {promise, resolve};
}

async function main() {
  const calls = [];
  const pending = new Map();
  const context = {
    api(path) {
      calls.push(path);
      const request = pending.get(path);
      if (request) return request.promise;
      return Promise.resolve({
        "/api/catalog/factor-sets": {items: [{target_ref: "set:one"}]},
        "/api/catalog/product-groups": {groups: [{group_ref: "group:one"}]},
        "/api/catalog/factors": {
          factors: [{factor_ref: "factor:one"}],
          families: [{family_ref: "family:one"}],
          family_scopes: {}, principal: "alice", visitor: false,
        },
      }[path]);
    },
    isRouteCurrent() { return true; },
  };

  let data = await window.FTFactorCatalog.load(context, {sets: true});
  assert.deepStrictEqual(calls, ["/api/catalog/factor-sets"]);
  assert.strictEqual(data.sets[0].target_ref, "set:one");
  assert.strictEqual(data.libraryLoaded, false);

  data = await window.FTFactorCatalog.load(context, {groups: true});
  assert.deepStrictEqual(calls, [
    "/api/catalog/factor-sets", "/api/catalog/product-groups",
  ]);
  assert.strictEqual(data.groups[0].group_ref, "group:one");

  data = await window.FTFactorCatalog.load(context, {library: true});
  assert.deepStrictEqual(calls, [
    "/api/catalog/factor-sets", "/api/catalog/product-groups",
    "/api/catalog/factors",
  ]);
  assert.strictEqual(data.factors[0].factor_ref, "factor:one");

  calls.length = 0;
  await Promise.all([
    window.FTFactorCatalog.load(context, {sets: true}),
    window.FTFactorCatalog.load(context, {library: true}),
  ]);
  assert.deepStrictEqual(calls, []);

  // A library and set request issued together must retain both results.  This
  // guards the shared-cache mutation contract used during route transitions.
  await window.FTFactorCatalog.load(context, {refresh: true});
  calls.length = 0;
  const factors = deferred();
  const sets = deferred();
  pending.set("/api/catalog/factors", factors);
  pending.set("/api/catalog/factor-sets", sets);
  const libraryLoad = window.FTFactorCatalog.load(context, {library: true});
  const setLoad = window.FTFactorCatalog.load(context, {sets: true});
  factors.resolve({
    factors: [{factor_ref: "factor:two"}], families: [],
    family_scopes: {}, principal: "alice", visitor: false,
  });
  sets.resolve({items: [{target_ref: "set:two"}]});
  const [libraryData, setData] = await Promise.all([libraryLoad, setLoad]);
  assert.strictEqual(libraryData.factors[0].factor_ref, "factor:two");
  assert.strictEqual(setData.sets[0].target_ref, "set:two");
  assert.strictEqual(setData.libraryLoaded, true);
  assert.deepStrictEqual(calls.sort(), [
    "/api/catalog/factor-sets", "/api/catalog/factors",
  ].sort());

  console.log("ok");
}

main().catch(error => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
