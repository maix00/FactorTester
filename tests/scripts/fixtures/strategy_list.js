const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.listeners = {};
    this.className = "";
    this.dataset = {};
    this.hidden = false;
    this.disabled = false;
    this.textContent = "";
    this.style = {setProperty: () => {}};
    this.classList = {
      add: (...names) => { this.className = `${this.className} ${names.join(" ")}`.trim(); },
      toggle: (name, enabled) => {
        const names = new Set(this.className.split(/\s+/).filter(Boolean));
        if (enabled) names.add(name); else names.delete(name);
        this.className = [...names].join(" ");
      },
    };
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this[name] = String(value); }
  focus() { this.focused = true; }
  select() { this.selected = true; }
  dispatch(name, event = {}) { this.listeners[name]?.({...event, target: this}); }
}

global.window = {
  FTIcons: {node: symbol => {
    const icon = new Element("svg"); icon.textContent = symbol; return icon;
  }},
};
global.document = {createElement: tag => new Element(tag)};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "strategy-list.js",
});

function find(root, predicate) {
  if (predicate(root)) return root;
  for (const child of root.children || []) {
    const found = find(child, predicate);
    if (found) return found;
  }
  return null;
}

let batchToggles = 0;
let renameCalls = 0;
let actionCalls = 0;
const context = {
  t: value => value,
  button: (label, action, help) => {
    const button = new Element("button");
    button.textContent = label;
    button.title = help;
    button.listeners.click = action;
    return button;
  },
};
const options = {
  context,
  title: "策略",
  showConfig: true,
  showConfigOpen: true,
  batches: [{
    key: "batch-1", label: "添加批次 1", description: "5 个策略", expanded: true,
    chips: [new Element("span")],
    items: [{
      key: "strategy-1", label: "旧名称", editableName: true,
      detail: "基础组 · 1/5",
      chips: [new Element("span")],
      onRename: value => { renameCalls += 1; assert.equal(value, "新名称"); },
      actions: [{
        label: "编辑", icon: "square.and.pencil", onClick: () => { actionCalls += 1; },
      }],
    }],
  }],
  onToggleBatch: (_key, open) => { batchToggles += 1; assert.equal(open, false); },
};

const root = window.FTStrategyList.render(options);
const disclosure = find(root, node => node.className === "strategy-list-disclosure");
const body = find(root, node => node.className === "strategy-list-batch-body");
assert.ok(disclosure && body);
const row = find(root, node => node.className === "strategy-list-row");
assert.ok(row);
const batch = find(root, node => node.className === "strategy-list-batch");
const batchHeader = find(batch, node => node.className.includes("strategy-list-batch-header"));
assert.ok(batchHeader);
assert.equal(find(batchHeader, node => node.className === "strategy-list-chips"), null,
  "batch headers must not own strategy-specific override chips");
assert.equal(find(row, node => node.className === "strategy-list-chips") != null, true,
  "strategy-specific override chips must render under the strategy row");
assert.equal(find(row, node => node.tagName === "small"), null,
  "strategy rows must not render a subtitle");
assert.equal(body.hidden, false);
disclosure.dispatch("click");
assert.equal(body.hidden, true, "batch disclosure must update the current DOM immediately");
assert.equal(batchToggles, 1, "shared buttons must not bind the batch callback twice");
assert.equal(disclosure["aria-expanded"], "false");

const name = find(root, node => node.className === "strategy-list-name");
name.dispatch("click");
const input = find(root, node => node.className === "strategy-list-name-input");
assert.ok(input, "strategy name should become an inline input after clicking the name");
input.value = "新名称";
input.dispatch("blur");
assert.equal(renameCalls, 1);

const action = find(root, node => node.className === "strategy-list-action");
assert.equal(action.children[0].textContent, "square.and.pencil");
action.dispatch("click");
assert.equal(actionCalls, 1, "row action callbacks must run once");
console.log("ok");
