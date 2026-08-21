const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class ClassList {
  constructor() { this.values = new Set(); }
  toggle(name, enabled) {
    if (enabled) this.values.add(name); else this.values.delete(name);
  }
}

class Element {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = []; this.listeners = {}; this.classList = new ClassList();
    this.attributes = {}; this.value = ""; this.textContent = ""; this.parent = null;
  }
  append(...nodes) { nodes.forEach(node => { node.parent = this; this.children.push(node); }); }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  focus() {} select() {}
  async fire(name, event = {}) {
    event.preventDefault ||= () => {}; event.stopPropagation ||= () => {};
    for (const callback of this.listeners[name] || []) await callback(event);
  }
}

global.window = {};
global.document = {createElement: tag => new Element(tag)};
global.confirm = () => true;
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "result-tabs.js",
});

const changes = [];
const context = {t: value => value};
const tabs = [
  {key: "builtin", label: "结果"},
  {
    key: "custom-analysis:one", label: "分析一", renamable: true,
    onRename: async value => changes.push(["rename", value]),
    closable: true, onClose: async () => changes.push(["close"]),
  },
];
const view = window.FTJobResultTabs.create(context, {
  tabs, active: "builtin", onChange: key => changes.push(["change", key]),
});
const custom = view.tabs.children[1];
const [select, edit, close] = custom.children;

(async () => {
  await edit.fire("click");
  assert.deepEqual(changes, [], "edit must not activate the tab");
  const input = custom.children[0]; input.value = "新名字";
  await input.fire("keydown", {key: "Enter"});
  assert.deepEqual(changes, [["rename", "新名字"]]);
  assert.equal(custom.children[0], select);
  await close.fire("click");
  assert.deepEqual(changes, [["rename", "新名字"], ["close"]]);
  await select.fire("click");
  assert.deepEqual(changes.at(-1), ["change", "custom-analysis:one"]);
  console.log("ok");
})().catch(error => { console.error(error); process.exitCode = 1; });
