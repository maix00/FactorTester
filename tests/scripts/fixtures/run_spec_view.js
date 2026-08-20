const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.listeners = {};
    this.attributes = new Map();
    this.dataset = {};
    this.className = "";
    this.classList = {toggle() {}};
    this.textContent = "";
    this.open = false;
  }

  append(...children) { this.children.push(...children.flat().filter(Boolean)); }
  replaceChildren(...children) { this.children = children.flat().filter(Boolean); }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  showModal() { this.open = true; }
  close() { this.open = false; }
}

const documentBody = new Element("body");
global.window = {};
global.document = {
  body: documentBody,
  createElement: tagName => new Element(tagName),
};
global.FTUI = window.FTUI = {
  actionButton(label, action) {
    const button = new Element("button");
    button.textContent = label;
    button.listeners.click = action;
    return button;
  },
  code(value) { const node = new Element("pre"); node.value = value; return node; },
  empty(title, detail) {
    const node = new Element("div"); node.textContent = `${title}: ${detail}`; return node;
  },
  loading(label) { const node = new Element("div"); node.textContent = label; return node; },
  table() { return {shell: new Element("table")}; },
};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/research/run-spec-view.js", "utf8",
), {filename: "run-spec-view.js"});

const view = window.FTRunSpecView;
assert.equal(typeof view.openMany, "function");
const hash = "a".repeat(64);
const value = view.model({
  run_spec_hash: hash,
  run_spec_version: 3,
  configuration_id: "configuration-1",
  configuration_revision: 7,
  alias_zh: "日盘 IC 运行配置",
  summary_zh: "两个因子、三个收益期",
  run_spec: {
    workspace_id: "workspace-1",
    configuration_fingerprint: "fingerprint-1",
    analyses: ["ic"],
    retention_mode: "full",
    configuration: {shared: {start_date: "2025-01-01"}, analyses: {ic: {ic_lags: [0, 1]}}},
  },
});

assert.equal(value.identity.run_spec_hash, hash);
assert.equal(value.identity.configuration_revision, 7);
assert.equal(value.identity.workspace_id, "workspace-1");
assert.deepEqual(value.configuration.analyses.ic.ic_lags, [0, 1]);
assert.deepEqual(value.execution, {analyses: ["ic"], retention_mode: "full"});
assert.equal(value.title, "日盘 IC 运行配置");
assert.equal(value.summary, "两个因子、三个收益期");
assert.equal(view.digest(`runspec:sha256:${hash}`), hash);
assert.equal(view.digest(`run-spec:sha256:${hash}`), hash);
assert.equal(view.digest("invalid"), "");

const loaded = [];
const context = {
  tabID: "test-workbench",
  t: value => value,
  async api(path) {
    loaded.push(path);
    return {run_spec: {
      run_spec_hash: path.split("/").at(-1),
      configuration: {task: path},
      execution: {task: path},
    }};
  },
  navigate() {},
};
const secondHash = "b".repeat(64);
const dialog = view.openMany(context, [
  {target: `runspec:sha256:${hash}`, label: "任务 1 · 日盘"},
  {target: `runspec:sha256:${secondHash}`, label: "任务 2 · 夜盘"},
]);
assert.equal(dialog.dataset.ftTabID, "test-workbench");
const card = dialog.children[0];
const tabs = card.children[2];
assert.equal(tabs.children.length, 2);
assert.equal(tabs.children[0].textContent, "任务 1 · 日盘");
assert.equal(tabs.children[0].getAttribute("aria-selected"), "true");
tabs.children[1].listeners.click();
assert.equal(tabs.children[1].getAttribute("aria-selected"), "true");
assert.equal(loaded.length, 2, "each task tab must load its own RunSpec");

const inlineDialog = view.openMany(context, [{
  target: `runspec:sha256:${hash}`,
  label: "预览任务",
  value: {
    run_spec_hash: hash,
    run_spec_version: 3,
    configuration_id: "preview-configuration",
    configuration_revision: 1,
    run_spec: {
      workspace_id: "workspace-1",
      analyses: ["backtest"],
      configuration: {shared: {preview: true}},
    },
  },
}]);
assert.ok(inlineDialog, "inline preview should open the RunSpec overlay");
assert.equal(loaded.length, 2,
  "inline preview must not request a non-persisted RunSpec from the server");
console.log("ok");
