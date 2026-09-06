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
  const postSaveCalls = [];
  await window.FTFactorCatalog.load({
    session: {username: "saved-owner"},
    async api(path) {
      postSaveCalls.push(path);
      if (path === "/api/catalog/refresh") throw new Error("HTTP 503");
      return {factors: [{factor_ref: "factor:v2:committed"}], families: []};
    },
  }, {refresh: true, library: true, sync: false});
  assert.ok(!postSaveCalls.includes("/api/catalog/refresh"),
    "a committed save must not wait for unrelated account sync conflicts");
  assert.ok(postSaveCalls.includes("/api/factor-library/factors?refresh=1"));
  const calls = [];
  const pending = new Map();
  const context = {
    api(path) {
      calls.push(path);
      const request = pending.get(path);
      if (request) return request.promise;
      return Promise.resolve({
        "/api/factor-library/factor-sets": {items: [{target_ref: "set:one"}]},
        "/api/product-library/product-groups": {groups: [{group_ref: "group:one"}]},
        "/api/factor-library/families": {
          families: [{family_ref: "family:one"}],
          family_scopes: {
            public: {families: [{family_ref: "family:public"}]},
            mine: {families: [{family_ref: "family:mine"}]},
          },
          principal: "alice", visitor: false,
        },
        "/api/factor-library/factors": {
          factors: [{factor_ref: "factor:one"}],
          family_scopes: {
            public: {factors: [{factor_ref: "factor:public"}], families: []},
            mine: {factors: [{factor_ref: "factor:mine"}], families: []},
          },
          principal: "alice", visitor: false,
        },
      }[path]);
    },
    isRouteCurrent() { return true; },
  };

  let data = await window.FTFactorCatalog.load(context, {sets: true});
  assert.deepStrictEqual(calls, ["/api/factor-library/factor-sets"]);
  assert.strictEqual(data.sets[0].target_ref, "set:one");
  assert.strictEqual(data.libraryLoaded, false);

  data = await window.FTFactorCatalog.load(context, {groups: true});
  assert.deepStrictEqual(calls, [
    "/api/factor-library/factor-sets", "/api/product-library/product-groups",
  ]);
  assert.strictEqual(data.groups[0].group_ref, "group:one");

  data = await window.FTFactorCatalog.load(context, {library: true});
  assert.deepStrictEqual(calls, [
    "/api/factor-library/factor-sets", "/api/product-library/product-groups",
    "/api/factor-library/families", "/api/factor-library/factors",
  ]);
  assert.strictEqual(data.factors[0].factor_ref, "factor:one");
  assert.strictEqual(
    data.familyScopes.public.families[0].family_ref, "family:public",
  );
  assert.strictEqual(
    data.familyScopes.mine.families[0].family_ref, "family:mine",
  );
  assert.strictEqual(
    data.familyScopes.public.factors[0].factor_ref, "factor:public",
  );

  const savedFactor = {
    schema_version: 2,
    ref: "factor:v2:saved",
    alias: "SavedInline|N:5d",
    owner_ref: "alice",
    identity: {params: {N: "5d"}},
  };
  const upserted = window.FTFactorCatalog.upsertFactor(savedFactor);
  assert.ok(upserted.factors.some(item => item.ref === savedFactor.ref));

  calls.length = 0;
  await Promise.all([
    window.FTFactorCatalog.load(context, {sets: true}),
    window.FTFactorCatalog.load(context, {library: true}),
  ]);
  assert.deepStrictEqual(calls, []);

  await window.FTFactorCatalog.load(context, {refresh: true, library: true});
  assert.deepStrictEqual(calls.sort(), [
    "/api/factor-library/families?refresh=1",
    "/api/factor-library/factors?refresh=1",
  ].sort(), "manual refresh must bypass the populated catalog cache");

  // A library and set request issued together must retain both results.  This
  // guards the shared-cache mutation contract used during route transitions.
  await window.FTFactorCatalog.load(context, {refresh: true});
  calls.length = 0;
  const families = deferred();
  const factors = deferred();
  const sets = deferred();
  pending.set("/api/factor-library/families", families);
  pending.set("/api/factor-library/factors", factors);
  pending.set("/api/factor-library/factor-sets", sets);
  const libraryLoad = window.FTFactorCatalog.load(context, {library: true});
  const setLoad = window.FTFactorCatalog.load(context, {sets: true});
  families.resolve({
    families: [], family_scopes: {}, principal: "alice", visitor: false,
  });
  factors.resolve({
    factors: [{factor_ref: "factor:two"}],
    family_scopes: {}, principal: "alice", visitor: false,
  });
  sets.resolve({items: [{target_ref: "set:two"}]});
  const [libraryData, setData] = await Promise.all([libraryLoad, setLoad]);
  assert.strictEqual(libraryData.factors[0].factor_ref, "factor:two");
  assert.strictEqual(setData.sets[0].target_ref, "set:two");
  assert.strictEqual(setData.libraryLoaded, true);
  assert.deepStrictEqual(calls.sort(), [
    "/api/factor-library/factor-sets", "/api/factor-library/families",
    "/api/factor-library/factors",
  ].sort());

  // Old responses must not populate the cache of a refreshed session.
  const oldFamilies = deferred();
  const oldFactors = deferred();
  const staleContext = {...context, session: {username: "old"}, api(path) {
    return path.includes("families") ? oldFamilies.promise : oldFactors.promise;
  }};
  const stale = window.FTFactorCatalog.load(staleContext, {library: true});
  const rejection = assert.rejects(stale, /目录已刷新/);
  const freshContext = {...context, session: {username: "new"}, api: async () => ({principal: "new", factors: [{factor_ref: "new-factor"}], families: []})};
  const fresh = await window.FTFactorCatalog.load(freshContext, {library: true});
  oldFamilies.resolve({principal: "old", families: []});
  oldFactors.resolve({principal: "old", factors: [{factor_ref: "old-factor"}]});
  await rejection;
  assert.strictEqual((await window.FTFactorCatalog.load(freshContext, {library: true})), fresh);
  assert.strictEqual(fresh.factors[0].factor_ref, "new-factor");
  console.log("ok");
}

main().catch(error => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
