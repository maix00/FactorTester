const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

function element(tagName) {
  return {
    tagName: tagName.toUpperCase(),
    children: [],
    attributes: {},
    listeners: {},
    append(...children) { this.children.push(...children); },
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(name, handler) { this.listeners[name] = handler; },
  };
}

global.document = {createElement: element};
global.window = {};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-list.js", "utf8"),
  {filename: "factor-list.js"},
);

const navigated = [];
const context = {t: value => value, navigate: path => navigated.push(path)};
const tabs = window.FTFactorList.headerTabs(context, "factors");

assert.strictEqual(tabs.tagName, "NAV");
assert.match(tabs.className, /research-section-tabs/);
assert.strictEqual(tabs.attributes["aria-label"], "因子库页面");
assert.deepStrictEqual(tabs.children.map(item => item.textContent), [
  "因子家族", "因子", "因子集合",
]);
assert.match(tabs.children[1].className, /active/);
tabs.children[2].listeners.click();
assert.deepStrictEqual(navigated, ["/factors/sets"]);

const familyTabs = window.FTFactorList.familyScopeTabs(context, "mine", false);
assert.deepStrictEqual(familyTabs.children.map(item => item.textContent), [
  "公共因子家族", "我的因子家族", "下级用户因子家族",
]);
assert.match(familyTabs.children[1].className, /active/);
familyTabs.children[2].listeners.click();
assert.deepStrictEqual(navigated, [
  "/factors/sets", "/factors/families?scope=subordinates",
]);
const visitorTabs = window.FTFactorList.familyScopeTabs(context, "public", true);
assert.deepStrictEqual(visitorTabs.children.map(item => item.textContent), [
  "公共因子家族",
]);
assert.equal(window.FTFactorList.searchPlaceholder(context, "families", "public"), "搜索因子家族");
assert.equal(
  window.FTFactorList.searchPlaceholder(context, "families", "subordinates"),
  "搜索下级用户或因子家族",
);
console.log("ok");
