const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.listeners = {};
    this.className = ""; this.value = ""; this.checked = false;
    this.disabled = false; this.hidden = false; this.dataset = {};
    this.classList = {
      add: (...names) => { this.className = `${this.className} ${names.join(" ")}`.trim(); },
    };
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this[name] = String(value); }
}

global.window = {};
global.document = {createElement: tag => new Element(tag)};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: process.argv[2],
});

const filter = window.FTMultiSelectFilter.create({t: value => value}, {
  title: "产品分类",
  items: [
    {value: "none", label: "未绑定", exclusive: true},
    {value: "day", label: "日夜盘", description: "日盘与夜盘"},
    {value: "industry", label: "行业"},
  ],
  selected: ["day", "industry"],
});
assert.deepEqual(filter.values, ["day", "industry"]);
filter.setValues(["day", "none"]);
assert.deepEqual(filter.values, ["none"]);
assert.equal(filter.summary.children[0].textContent, "已选 1 个");
const exclusiveRow = filter.optionList.children.find(item => (
  item.className.includes("is-exclusive")
));
assert.ok(exclusiveRow.children.some(item => (
  item.className === "ft-multi-select-exclusive-badge"
)));

const multi = window.FTMultiSelectFilter.create({t: value => value}, {
  items: [{value: "a", label: "A"}, {value: "b", label: "B"}],
  selected: ["a"],
  multi: false,
});
assert.deepEqual(multi.values, ["a"]);
const bInput = multi.optionList.children[1].children[0];
bInput.checked = true;
bInput.listeners.change();
assert.deepEqual(multi.values, ["b"]);
console.log("ok");
