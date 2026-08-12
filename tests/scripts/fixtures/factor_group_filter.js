const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

function element(tagName) {
  return {
    tagName: tagName.toUpperCase(),
    children: [],
    listeners: {},
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    addEventListener(name, handler) { this.listeners[name] = handler; },
    setAttribute() {},
  };
}

global.document = {createElement: element};
global.window = {
  FTFactorModel: {
    groupRef(group) { return group.group_ref || `product-group:${group.id}`; },
  },
};
vm.runInThisContext(
  fs.readFileSync("scripts/worktree_manager_web/catalog/factor-group-filter.js", "utf8"),
  {filename: "factor-group-filter.js"},
);

const changes = [];
const view = window.FTFactorGroupFilter.create(
  {t: value => value},
  [
    {group_ref: "product-group:day", name: "日盘期货"},
    {group_ref: "product-group:night", name: "夜盘期货"},
  ],
  "*",
  value => changes.push(value),
);

assert.strictEqual(view.element.tagName, "SECTION");
assert.strictEqual(view.search.type, "search");
assert.strictEqual(view.search.placeholder, "搜索产品组");
assert.strictEqual(view.value, "*");
assert.ok(view.options.children.some(item => item.textContent === "全部产品组"));
assert.ok(view.options.children.some(item => item.textContent === "未绑定产品组"));
assert.ok(view.options.children.some(item => item.textContent === "日盘期货"));

view.search.value = "夜盘";
view.search.listeners.input();
assert.deepStrictEqual(
  view.options.children.map(item => item.textContent), ["夜盘期货"],
);
view.options.children[0].listeners.click();
assert.strictEqual(view.value, "product-group:night");
assert.deepStrictEqual(changes, ["product-group:night"]);

function tags(node) {
  return [node.tagName, ...(node.children || []).flatMap(tags)];
}
assert.ok(!tags(view.element).includes("SELECT"));
console.log("ok");
