const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "factor-family-picker.js",
});

const picker = window.FTFactorFamilyPicker;
const entries = picker.entries({
  publicFamilies: [{
    family_ref: "factor-family:public:roc",
    factor_family_alias: "MmRateOfChg",
    chinese_name: "变动率",
    owner_alias: "公共因子库",
    factor_refs: ["factor:roc-1m"],
  }],
  localFamilies: [{family: "MmRateOfChg", title_zh: "本地变动率"}],
  ownerRef: "profile:maxa",
  gitCommit: "0123456789abcdef",
});

assert.equal(entries.length, 2);
assert.deepEqual(entries.map(item => item.sourceKind), ["public", "local"]);
assert.notEqual(entries[0].key, entries[1].key);
assert.deepEqual(
  picker.filter(entries, "变动率").map(item => item.sourceKind),
  ["public", "local"],
);
assert.deepEqual(
  picker.filter(entries, "profile:maxa").map(item => item.sourceKind),
  ["local"],
);
assert.equal(picker.filter(entries, "不存在").length, 0);
assert.deepEqual(picker.familyFactors(entries[0], [
  {factor_ref: "factor:roc-1m", factor_alias: "ROC 1m"},
  {factor_ref: "factor:other", factor_alias: "Other"},
]).map(item => item.factor_alias), ["ROC 1m"]);
console.log("ok");
