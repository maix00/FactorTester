const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/app/route-presentation.js", "utf8",
), {filename: "route-presentation.js"});

let current = true;
const calls = [];
const presentation = window.FTRoutePresentation.create({
  isCurrent: () => current,
  activeNav: value => calls.push(["nav", value]),
  setHeading: (...value) => calls.push(["heading", ...value]),
  updateActiveTab: value => calls.push(["tab", value.title]),
});
presentation.activeNav("products");
presentation.setHeading("数据源一", "数据源族");
presentation.updateActiveTab({title: "数据源一"});
current = false;
presentation.setHeading("过期因子", "因子详情");
presentation.updateActiveTab({title: "过期因子"});
assert.deepEqual(calls, [
  ["nav", "products"],
  ["heading", "数据源一", "数据源族"],
  ["tab", "数据源一"],
]);
console.log("ok");
