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
  fs.readFileSync("server/manager/web/catalog/shared/multi-select-filter/type-filter.js", "utf8"),
  {filename: "multi-select-filter/type-filter.js"},
);
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/shared/multi-select-filter/index.js", "utf8"),
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
function walk(node, out = []) {
  for (const child of node.children || []) {
    if (typeof child === "string") continue;
    out.push(child);
    walk(child, out);
  }
  return out;
}
function optionRows(picker) {
  return walk(picker.optionList).filter(item => (
    String(item.className || "").includes("ft-multi-select-option")
    && String(item.tagName).toLowerCase() === "label"
  ));
}
const rowLabel = item => item.children[1]?.textContent || item.textContent;
function findRow(label) {
  return optionRows(view).find(item => rowLabel(item) === label);
}
assert.ok(findRow("全部产品组"));
assert.ok(findRow("未绑定产品组"));
assert.ok(findRow("日盘期货"));

view.search.value = "夜盘";
view.search.listeners.input();
const filteredRows = optionRows(view).map(rowLabel);
assert.ok(filteredRows.includes("夜盘期货"), "search narrows candidates");
assert.ok(filteredRows.includes("全部产品组"),
  "search must not filter the already-selected section");
const night = findRow("夜盘期货");
night.children[0].checked = true;
night.children[0].listeners.change();
assert.strictEqual(changes.length, 0, "multi pick waits for outside-close commit");
view.dropdown.open = false;
view.dropdown.listeners.toggle();
assert.deepStrictEqual(changes, [["product-group:night"]]);
view.clear.listeners.click();
assert.ok(findRow("夜盘期货"), "clearing search restores candidates");
const day = findRow("日盘期货");
day.children[0].checked = true;
day.children[0].listeners.change();
view.dropdown.open = false;
view.dropdown.listeners.toggle();
assert.deepStrictEqual(changes.at(-1), ["product-group:night", "product-group:day"]);
assert.equal(optionRows(view).some(item => (
  String(item.className).includes("ft-multi-select-apply")
)), false, "no save action is rendered");
console.log("ok");
