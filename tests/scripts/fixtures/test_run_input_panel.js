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
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this.hidden = false;
    this.open = false;
    this.dataset = {};
    this.multiple = false;
    this.accept = "";
    this.className = "";
    this.classList = {add: (...names) => {
      this.className = `${this.className} ${names.join(" ")}`.trim();
    }};
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = [...children]; }
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

for (const path of process.argv.slice(2)) {
  vm.runInThisContext(fs.readFileSync(path, "utf8"), {filename: path});
  if (window.FTMultiSelectFilter) {
    global.FTMultiSelectFilter = window.FTMultiSelectFilter;
  }
  if (window.FTTestObjectPicker) {
    global.FTTestObjectPicker = window.FTTestObjectPicker;
    global.FTTestChoicePicker = window.FTTestChoicePicker;
  }
}

const context = {
  t: value => value,
  button(label, action) {
    const button = new Element("button");
    button.textContent = label; button.action = action;
    return button;
  },
};
const state = {};
const empty = window.FTTestSourceUpload.customStrategyPanel(
  context, state, () => {}, {title: "空输入", description: "无注册控件"},
);
assert.equal(findAll(empty, node => node.tagName === "button").length, 0);

const strategyPanel = window.FTTestSourceUpload.customStrategyPanel(context, state, () => {}, {
  title: "自定义策略",
  description: "后端说明",
  inputs: [
    {
      kind: "strategy_source", label: "自定义策略源码", accept: ".hook",
      extensions: [".hook"], multiple: false, inspect_endpoint: "/inspect",
      path_prefix: "hooks",
    },
  ],
});
const dependencyPanel = window.FTTestSourceUpload.dependencyPanel(
  context, state, () => {}, {
    title: "运行输入",
    inputs: [{
      kind: "run_dependency", label: "自定义依赖", accept: ".cfg",
      extensions: [".cfg"], multiple: true, analyses: ["backtest"],
      default_purpose: "custom", content_types: {".cfg": "text/plain"},
      purposes: [{value: "custom", label: "自定义用途", path_prefix: "custom"}],
    }],
  },
);
assert.deepEqual(
  [...findAll(strategyPanel, node => node.tagName === "button"
    && !node.className.split(" ").includes("ft-help-icon")
    && !node.className.split(" ").includes("ft-multi-select-sync-toggle")
    && node.textContent !== "×"), ...findAll(dependencyPanel, node => node.tagName === "button"
    && !node.className.split(" ").includes("ft-help-icon")
    && !node.className.split(" ").includes("ft-multi-select-sync-toggle")
    && node.textContent !== "×")]
    .map(node => node.textContent),
  ["自定义策略源码", "自定义依赖"],
);
const pickers = [strategyPanel, dependencyPanel].flatMap(panel => (
  findAll(panel, node => node.tagName === "input" && node.accept)
));
assert.deepEqual(pickers.map(node => [node.accept, node.multiple]), [
  [".hook", false], [".cfg", true],
]);
const usageLabels = findAll(dependencyPanel, node => node.tagName === "span"
    && node.className === "ft-multi-select-option-label"
    && node.textContent !== "×")
    .map(node => node.textContent);
assert.ok(usageLabels.includes("自定义用途"),
  "selected 自定义用途 appears in the menu (已选 + candidates sections)");

const populatedState = {
  transientStrategySources: [{path: "hooks/risk.hook", source_code: "allow = true"}],
  strategySpecs: [{source: "profile:hooks/risk.hook", strategy_id: "risk"}],
  runInputDependencies: [{
    path: "custom/risk.cfg", title_zh: "风险配置", content_type: "text/plain",
    content: "limit=0.4",
  }],
};
const populatedStrategy = window.FTTestSourceUpload.customStrategyPanel(
  context, populatedState, () => {}, {title: "自定义策略", inputs: []},
);
const populatedDependencies = window.FTTestSourceUpload.dependencyPanel(
  context, populatedState, () => {}, {title: "运行输入", inputs: []},
);
const details = [populatedStrategy, populatedDependencies].flatMap(panel => (
  findAll(panel, node => node.tagName === "details")
));
assert.equal(details.length, 2);
assert.equal([populatedStrategy, populatedDependencies].flatMap(panel => (
  findAll(panel, node => node.tagName === "pre")
)).length, 0);
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
