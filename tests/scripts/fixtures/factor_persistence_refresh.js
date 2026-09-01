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
  window.FTFactorEditor.replacePersistedObjectTab({
    tabID: "factor-detail:factor:old",
    navigate(path) { transitions.push(["navigate", path]); },
    closeTab(tabID) { transitions.push(["close", tabID]); },
  }, {familyMode: false}, {
    factor_ref: "factor:v2:new",
    factor_alias: "Probe|N:10d",
  });
  assert.equal(transitions[0][0], "navigate");
  assert.match(
    transitions[0][1],
    /^\/factors\/factor\/factor%3Av2%3Anew\?updated=\d+$/,
  );
  assert.deepEqual(transitions[1], ["close", "factor-detail:factor:old"]);
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
