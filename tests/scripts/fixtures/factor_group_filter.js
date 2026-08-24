const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

function element(tagName) {
  let ownText = "";
  const node = {
    tagName: tagName.toUpperCase(),
    children: [],
    listeners: {},
    dataset: {},
    classList: {add() {}, toggle() {}},
    value: "",
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    addEventListener(name, handler) { this.listeners[name] = handler; },
    setAttribute() {},
    focus() {},
  };
  Object.defineProperty(node, "textContent", {
    get() { return ownText || node.children.map(item => item.textContent || "").join(""); },
    set(value) { ownText = String(value || ""); node.children = []; },
  });
  return node;
}

global.document = {createElement: element};
global.window = {
  FTFactorModel: {
    groupRef(group) { return group.group_ref || `product-group:${group.id}`; },
  },
};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/shared/multi-select-filter.js", "utf8"),
  {filename: "multi-select-filter.js"},
);
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-group-filter.js", "utf8"),
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
assert.strictEqual(typeof view.setItems, "function");
assert.strictEqual(view.value, "*");
const rowLabel = item => item.children[1]?.textContent || item.textContent;
assert.ok(view.options.children.some(item => rowLabel(item) === "全部产品组"));
assert.ok(view.options.children.some(item => rowLabel(item) === "未绑定产品组"));
assert.ok(view.options.children.some(item => rowLabel(item) === "日盘期货"));

view.search.value = "夜盘";
view.search.listeners.input();
assert.deepStrictEqual(
  view.options.children.map(rowLabel), ["夜盘期货"],
);
view.options.children[0].children[0].checked = true;
view.options.children[0].children[0].listeners.change();
assert.strictEqual(view.value, "product-group:night");
assert.deepStrictEqual(changes, []);
const save = find(view.element, item => item.className === "primary ft-multi-select-apply");
assert.ok(save);
save.listeners.click();
assert.deepStrictEqual(changes, [["product-group:night"]]);
view.clear.listeners.click();
assert.strictEqual(rowLabel(view.options.children[0]), "夜盘期货");
const day = view.options.children.find(item => rowLabel(item) === "日盘期货");
day.children[0].checked = true;
day.children[0].listeners.change();
assert.deepStrictEqual(view.values, ["product-group:night", "product-group:day"]);
const all = view.options.children.find(item => rowLabel(item) === "全部产品组");
all.children[0].checked = true;
all.children[0].listeners.change();
assert.deepStrictEqual(view.values, ["*"]);

view.setItems([
  {group_ref: "product-group:updated", name: "更新后的产品组"},
]);
assert.ok(view.options.children.some(item => rowLabel(item) === "更新后的产品组"));

function tags(node) {
  return [node.tagName, ...(node.children || []).flatMap(tags)];
}

function find(node, predicate) {
  if (predicate(node)) return node;
  for (const child of node.children || []) {
    const result = find(child, predicate);
    if (result) return result;
  }
  return null;
}

assert.ok(!tags(view.element).includes("SELECT"));
console.log("ok");
