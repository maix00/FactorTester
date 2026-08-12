const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.listeners = {};
    this.attributes = {};
    this.textContent = "";
    this.multiple = false;
    this.accept = "";
  }
  append(...children) { this.children.push(...children); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this.attributes[name] = value; }
}

global.window = {};
global.document = {createElement: tag => new Element(tag)};
global.FTTestInputState = {
  initialize(state) {
    state.transientStrategySources ||= [];
    state.strategySpecs ||= [];
    state.runInputDependencies ||= [];
    state.runInputStatus ||= {};
  },
  removeDependency() {},
  removeStrategy() {},
};

vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: process.argv[2],
});

const context = {
  t: value => value,
  button(label, action) {
    const button = new Element("button");
    button.textContent = label; button.action = action;
    return button;
  },
};
const state = {};
const empty = window.FTTestSourceUpload.strategyPanel(
  context, state, () => {}, {title: "空输入", description: "无注册控件"},
);
assert.equal(findAll(empty, node => node.tagName === "button").length, 0);

const panel = window.FTTestSourceUpload.strategyPanel(context, state, () => {}, {
  title: "后端运行输入",
  description: "后端说明",
  inputs: [
    {
      kind: "strategy_source", label: "自定义策略源码", accept: ".hook",
      extensions: [".hook"], multiple: false, inspect_endpoint: "/inspect",
      path_prefix: "hooks",
    },
    {
      kind: "run_dependency", label: "自定义依赖", accept: ".cfg",
      extensions: [".cfg"], multiple: true, analyses: ["backtest"],
      default_purpose: "custom", content_types: {".cfg": "text/plain"},
      purposes: [{value: "custom", label: "自定义用途", path_prefix: "custom"}],
    },
  ],
});
assert.deepEqual(
  findAll(panel, node => node.tagName === "button").map(node => node.textContent),
  ["自定义策略源码", "自定义依赖"],
);
const pickers = findAll(panel, node => node.tagName === "input");
assert.deepEqual(pickers.map(node => [node.accept, node.multiple]), [
  [".hook", false], [".cfg", true],
]);
assert.equal(findAll(panel, node => node.tagName === "option")[0].textContent, "自定义用途");

const populated = window.FTTestSourceUpload.strategyPanel(context, {
  transientStrategySources: [{path: "hooks/risk.hook", source_code: "allow = true"}],
  strategySpecs: [{source: "profile:hooks/risk.hook", strategy_id: "risk"}],
  runInputDependencies: [{
    path: "custom/risk.cfg", title_zh: "风险配置", content_type: "text/plain",
    content: "limit=0.4",
  }],
}, () => {}, {title: "运行输入", inputs: []});
const details = findAll(populated, node => node.tagName === "details");
assert.equal(details.length, 2);
assert.equal(findAll(populated, node => node.tagName === "pre").length, 0);
details[0].open = true;
details[0].listeners.toggle();
assert.deepEqual(
  findAll(details[0], node => node.tagName === "code").map(node => node.textContent),
  ["allow = true", JSON.stringify({
    source: "profile:hooks/risk.hook", strategy_id: "risk",
  }, null, 2)],
);
console.log("ok");

function findAll(node, predicate, result = []) {
  if (predicate(node)) result.push(node);
  for (const child of node.children || []) findAll(child, predicate, result);
  return result;
}
