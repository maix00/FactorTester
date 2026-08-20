const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
global.FTTestProducts = {
  groupID: value => value?.id || "",
  groupLabel: value => value?.name || value?.id || "",
  projection: value => ({id: value.id, name: value.name}),
};
vm.runInThisContext(fs.readFileSync(
  require("node:path").join(require("node:path").dirname(process.argv[2]), "backtest-group-batches.js"),
  "utf8",
), {filename: "backtest-group-batches.js"});
global.FTBacktestGroupBatches = window.FTBacktestGroupBatches;
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "backtest-group-model.js",
});

const state = {analysis: {}, selectedBacktestGroupIDs: []};
const created = window.FTBacktestGroupModel.addBaseBatch(state, {
  product_path_selection: {id: "metals", name: "金属"},
  factor_candidate_refs: ["factor:roc"],
  splitCount: 3,
  groupIndex: 1,
  allGroups: true,
});

assert.equal(created.length, 3);
assert.deepEqual(created.map(item => item.factor_candidate_refs), [
  ["factor:roc"], ["factor:roc"], ["factor:roc"],
]);
assert.deepEqual(created.map(item => item.name), created.map(item => (
  `${item.batchId}/${item.id}`
)));
const deprecatedDisplayKey = ["short", "Alias"].join("");
assert.ok(created.every(item => !Object.prototype.hasOwnProperty.call(item, deprecatedDisplayKey)));
assert.equal(new Set(created.map(item => item.id)).size, 3);
assert.equal(new Set(created.map(item => item.batchId)).size, 1);
assert.throws(() => window.FTBacktestGroupModel.addBaseBatch(state, {
  product_path_selection: {id: "metals", name: "金属"},
  factor_candidate_refs: ["factor:roc", "factor:sgccs"], splitCount: 1, groupIndex: 1,
}), /组合方式/);
const combined = window.FTBacktestGroupModel.addBaseBatch(state, {
  product_path_selection: {id: "metals", name: "金属"},
  factor_candidate_refs: ["factor:roc", "factor:sgccs"], factor_combination_mode: "future",
  splitCount: 1, groupIndex: 1,
});
assert.equal(combined.length, 1);
assert.deepEqual(combined[0].factor_candidate_refs, ["factor:roc", "factor:sgccs"]);
assert.equal(combined[0].factor_combination_mode, "future");
const repeated = window.FTBacktestGroupModel.addBaseBatch(state, {
  product_path_selection: {id: "metals", name: "金属"},
  factor_candidate_refs: ["factor:roc"], splitCount: 3, groupIndex: 1, allGroups: true,
});
assert.equal(new Set(repeated.map(item => item.batchId)).size, 1);
assert.notEqual(repeated[0].batchId, created[0].batchId);
assert.notEqual(repeated[0].name, created[0].name);
const derived = window.FTBacktestGroupModel.addDerived(state, created[0].id);
assert.notEqual(derived.batchId, created[0].batchId);
assert.equal(derived.name, `${derived.batchId}/${derived.id}`);
const longShort = window.FTBacktestGroupModel.addLongShort(
  state, created[0].id, created[1].id, "多空组合", {fee_mode: "custom"},
);
assert.equal(longShort.name, "多空组合");
const updatedLongShort = window.FTBacktestGroupModel.updateLongShort(state, longShort.id, {
  fee_mode: undefined, override_mounted_tabs: ["cost"],
});
assert.equal(Object.prototype.hasOwnProperty.call(updatedLongShort, "fee_mode"), false);
assert.deepEqual(updatedLongShort.override_mounted_tabs, ["cost"]);
const overrideManifest = {defaults: {fee_mode: {}, engine_mode: {}}};
assert.deepEqual(window.FTBacktestGroupModel.registeredOverrides(
  {...created[0], fee_mode: undefined, engine_mode: "custom"}, overrideManifest,
), {engine_mode: "custom"});
const batches = window.FTBacktestGroupModel.groupBatches(state);
assert.equal(batches.length, 3);
assert.equal(batches[0].items.find(item => item.group.id === derived.id).depth, 1);
assert.deepEqual(batches.map(item => item.order), [1, 2, 3]);
assert.throws(() => window.FTBacktestGroupModel.renameGroup(state, created[0].id, repeated[0].name), /策略名称已存在/);
window.FTBacktestGroupModel.renameGroup(state, created[0].id, "重命名策略");
assert.deepEqual(state.selectedBacktestGroupIDs, [derived.id]);
console.log("ok");
