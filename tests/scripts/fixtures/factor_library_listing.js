const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.window = {};
global.document = {createElement() { return {}; }};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-model.js", "utf8"),
  {filename: "factor-model.js"},
);
window.FTUI = {
  table(headers, rows) {
    return {shell: {headers, rows}, body: {rows: []}};
  },
  empty(title, description) { return {title, description}; },
};
global.FTUI = window.FTUI;
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-list.js", "utf8"),
  {filename: "factor-list.js"},
);

const context = {t: value => value};
const data = {
  groups: [],
  sets: [],
  families: [{
    family_ref: "family:one",
    factor_family_name: "MmRateOfChg",
    factor_family_alias: "ROC",
    chinese_name: "动量变动率",
    description: "使用端点收益率衡量动量的长篇说明",
    categories: ["momentum"],
    owner_alias: "MaxA",
    factor_count: 2,
  }],
  factors: [{
    factor_ref: "factor:one",
    factor_alias: "MmRateOfChg|P:[CA]|N:20d|$F:1d",
    factor_family_name: "MmRateOfChg",
    factor_family_alias: "ROC",
    chinese_name: "20 日动量变动率",
    description: "使用二十日端点收益率构造的具体因子长篇说明",
    factor_kind: "custom",
    owner_alias: "MaxA",
  }],
};
const mount = {replaceChildren(value) { this.value = value; }};

window.FTFactorList.render(context, data, mount, {
  page: "families", query: "", groupRef: "*",
});
assert.deepStrictEqual(mount.value.headers, [
  "原类名", "说明", "分类", "来源", "所有者", "因子数",
]);
assert.strictEqual(mount.value.rows[0][0], "MmRateOfChg");
assert.strictEqual(mount.value.rows[0][1], "动量变动率");

window.FTFactorList.render(context, data, mount, {
  page: "factors", query: "", groupRef: "*",
});
assert.deepStrictEqual(mount.value.headers, [
  "因子", "原类名", "说明", "来源", "所有者", "产品组",
]);
assert.strictEqual(mount.value.rows[0][1], "MmRateOfChg");
assert.strictEqual(mount.value.rows[0][2], "20 日动量变动率");
console.log("ok");
