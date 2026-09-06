"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = globalThis;
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-editor.js", "utf8"),
  {filename: "factor-editor.js"},
);

(async () => {
  const factor = {factor_ref: "factor:v2:stored", factor_alias: "Probe|N:5d"};
  let loads = 0;
  window.FTFactorCatalog = {
    async load(_context, options) {
      loads += 1;
      assert.deepEqual(options, {refresh: true, library: true});
      return {factors: [factor]};
    },
  };
  const context = {t: value => value};
  const persisted = await window.FTFactorEditor.refreshPersistedObject(
    context, {familyMode: false}, {factor_alias: factor.factor_alias},
  );
  assert.equal(persisted.factor_ref, factor.factor_ref);
  assert.equal(loads, 1, "persistent saves must refresh the factor catalog");

  const temporary = {factor_alias: "Inline|N:5d", temporary: true};
  assert.equal(await window.FTFactorEditor.refreshPersistedObject(
    {...context, testObjectTemporary: true}, {familyMode: false}, temporary,
  ), temporary);
  assert.equal(loads, 1, "inline factors must not touch the persistent catalog");

  window.FTFactorCatalog.load = async () => ({factors: []});
  await assert.rejects(
    window.FTFactorEditor.refreshPersistedObject(
      context, {familyMode: false}, {factor_alias: "Missing|N:5d"},
    ),
    /因子保存后未在因子库中登记/,
  );

  const transitions = [];
  const inPlaceContext = {
    tabID: "factor-detail:factor:old",
    navigate(path) { transitions.push(["navigate", path]); },
    navigateInPlace(path) { transitions.push(["navigateInPlace", path]); },
    closeTab(tabID) { transitions.push(["close", tabID]); },
  };
  window.FTFactorEditor.replacePersistedObjectTab(
    inPlaceContext, {familyMode: false, mode: "create"}, {
      factor_ref: "factor:v2:new",
      factor_alias: "Probe|N:10d",
    },
  );
  // Same-tab authoring: saves adopt the result view inside the SAME tab —
  // factor aliases/refs change after an edit, so the destination URL differs
  // from the editing URL; navigateInPlace keeps one tab (no close, no second
  // tab).  When the host lacks navigateInPlace, plain navigate is the
  // fallback.
  assert.deepEqual(transitions, [
    ["navigateInPlace", "/factors/factor/Probe%7CN%3A10d"],
  ]);
  const fallback = [];
  window.FTFactorEditor.replacePersistedObjectTab({
    tabID: "factor-detail:factor:stored",
    navigate(path) { fallback.push(["navigate", path]); },
    closeTab() { fallback.push(["close"]); },
  }, {familyMode: false, mode: "edit"}, {
    factor_ref: "factor:v2:stored",
    factor_alias: "Probe|N:5d",
  });
  assert.deepEqual(fallback, [
    ["navigate", "/factors/factor/Probe%7CN%3A5d"],
  ]);

  // A registered factor edits its frozen source, even when current source
  // is unavailable or belongs to a newer revision. Stop at the real API seam.
  vm.runInThisContext(fs.readFileSync(
    "server/manager/web/catalog/factor-detail-shared.js", "utf8"));
  const stop = new Error("source request captured");
  for (const row of [
    {factor_ref: "factor:v2:edited", factor_alias: "Probe|N:5d"},
    {ref: "factor:v2:edited", alias: "Probe|N:5d"},
  ]) {
    let requested;
    await assert.rejects(window.FTFactorEditor.render({
      session: {username: "parent"}, t: x => x,
      api: async path => { requested = path; throw stop; },
    }, {factors: [{...row, factor_family_alias: "Probe", owner_ref: "child",
      identity: {family_formula_fingerprint: "a".repeat(64)}}]},
    "factor:v2:edited", "edit"), error => error === stop);
    assert.equal(requested,
      "/api/factor-library/family-sources/custom/Probe/versions/"
      + "a".repeat(64) + "?owner_username=child");
  }

  const requests = [];
  const field = value => ({querySelector() { return {value}; }});
  const edited = await window.FTFactorEditor.saveSourceFactor({
    async api(path, options) {
      requests.push([path, options.method]);
      if (path.includes("/families/custom/")) {
        return {factor: {id: "SgChgDur", name: "SgChgDur"}};
      }
      return {factors: [{
        factor_ref: "factor:v2:changed",
        factor_alias: "SgChgDur|Th:[0.01]",
      }]};
    },
  }, {
    mode: "edit",
    familyMode: false,
    publicMode: false,
    factorID: "SgChgDur|Th:[0.001]",
    loaded: {factor_family_alias: "SgChgDur"},
    inspection: {factor_name: "SgChgDur"},
    sourceCode: "class SgChgDur(FactorFamily): pass",
    parameterValues: {Th: 0.01},
  }, {
    chineseName: field("差持续期"),
    description: field("说明"),
    category: field("自编"),
  });
  assert.deepEqual(requests, [
    ["/api/factor-library/families/custom/SgChgDur", "PUT"],
    ["/api/factor-library/configurations/SgChgDur/factors", "POST"],
  ]);
  assert.equal(edited.factor_ref, "factor:v2:changed");
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
