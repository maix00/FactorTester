const assert = require("node:assert/strict");
const fs = require("node:fs");

global.window = globalThis;
eval(fs.readFileSync("server/manager/web/core/test-type-registry.js", "utf8"));

class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.attributes = {};
    this.className = "";
    this.textContent = "";
    this.title = "";
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attributes[name] = value; }
}

global.document = {createElement: tagName => new Element(tagName)};
global.FTIcons = {
  node(symbol) {
    const icon = new Element("icon");
    icon.symbol = symbol;
    return icon;
  },
};
global.FTUI = {
  empty: () => new Element("empty"),
  formatDate: value => value,
  table(headers, rows) {
    const shell = new Element("table");
    shell.headers = headers;
    shell.rows = rows;
    return {shell};
  },
};

eval(fs.readFileSync(process.argv[2], "utf8"));

const calls = [];
const context = {
  t: value => value,
  button(label, action, help = label) {
    const button = new Element("button");
    button.textContent = label;
    button.title = help;
    button.action = action;
    return button;
  },
  navigate: path => calls.push(["view", path]),
};
const template = {
  configuration_id: "template-1",
  name: "IC 模板",
  revision: 3,
  updated_at: "2026-08-12",
  payload: {
    analyses: {ic: {}},
    shared: {factors: [{alias: "ROC 1m"}]},
  },
};
const panel = FTTestTemplates.panel(context, [template], "ic", {
  save: () => calls.push(["save"]),
  load: item => calls.push(["load", item.configuration_id]),
  overwrite: item => calls.push(["overwrite", item.configuration_id]),
  delete: item => calls.push(["delete", item.configuration_id]),
});

assert.equal(FTTestTemplates.list, undefined);
assert.equal(panel.className, "test-template-section");
assert.equal(panel.children[0].className, "test-template-toolbar");
const table = panel.children[1];
const actions = table.rows[0][3];
assert.equal(actions.className, "row-actions template-icon-actions");
assert.deepEqual(actions.children.map(item => item.children[0].symbol), [
  "arrow.down.circle", "eye", "square.and.pencil", "trash",
]);
assert.deepEqual(actions.children.map(item => item.title), [
  "加载", "查看", "覆盖", "删除",
]);
assert.deepEqual(actions.children.map(item => item.attributes["aria-label"]), [
  "加载", "查看", "覆盖", "删除",
]);
actions.children.forEach(item => item.action());
assert.deepEqual(calls, [
  ["load", "template-1"],
  ["view", "/test-templates/template-1"],
  ["overwrite", "template-1"],
  ["delete", "template-1"],
]);
console.log("ok");
