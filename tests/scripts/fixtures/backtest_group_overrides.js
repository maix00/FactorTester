const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
global.structuredClone = global.structuredClone
  || (value => JSON.parse(JSON.stringify(value)));
global.FTSettingRules = {
  storageKey: (key, field) => field?.serialization?.storage_key || key,
  isVisible: (field, values) => Object.entries(field?.rules?.visible_if || {}).every(
    ([key, allowed]) => allowed.includes(values[key]),
  ),
  isEditable: () => true,
  valueFor: (key, field, values) => values[field?.serialization?.storage_key || key],
};
class Element {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.listeners = {};
    this.className = ""; this.checked = false; this.textContent = "";
    this.hidden = false;
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
}
global.document = {createElement: tag => new Element(tag)};
vm.runInThisContext(fs.readFileSync(
  require("node:path").join(require("node:path").dirname(process.argv[2]), "tab-chip-content.js"),
  "utf8",
), {filename: "tab-chip-content.js"});
global.FTTabChipContent = window.FTTabChipContent;
global.FTTestSettings = {controlFor: (_key, _field, _manifest, _values, _context, _options, disabled) => {
  const control = new Element("control"); control.disabled = disabled; return control;
}};

vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "backtest-group-overrides.js",
});

const manifest = {
  defaults: {
    engine: {scope_policy: "local_only", tab_key: "engine"},
    engine_mode: {scope_policy: "overridable", tab_key: "engine"},
    split_count: {scope_policy: "group_only", tab_key: "group_strategy"},
    factor: {
      scope_policy: "overridable", tab_key: "factor",
      execution_policy: "authoring_only",
      serialization: {kind: "factor_selection"},
    },
    fee_mode: {scope_policy: "overridable", tab_key: "cost"},
    custom_product_fields: {
      scope_policy: "overridable", tab_key: "engine",
      serialization: {kind: "custom_product_overrides", storage_key: "custom_product_fields"},
    },
    fee_custom_product_fields: {
      scope_policy: "overridable", tab_key: "cost",
      rules: {visible_if: {fee_mode: ["custom"]}},
      serialization: {
        kind: "custom_product_overrides", storage_key: "custom_product_fields",
        module_filter: "fee",
      },
    },
  },
  tab_lists: {"group-settings": [
    {key: "engine", label: "执行引擎"},
    {key: "factor", label: "因子"},
    {key: "group_strategy", label: "分组"},
    {key: "cost", label: "成本"},
  ]},
};

const api = window.FTBacktestGroupOverrides;
assert.deepEqual(api.canonicalKeys(manifest), [
  "engine_mode", "fee_mode", "custom_product_fields",
]);
assert.deepEqual(api.normalize(manifest, {
  engine: "rqalpha",
  engine_mode: "custom",
  factor: "ROC",
  split_count: 5,
  custom_product_fields: [{product: "SI.GFE", field: "OpenRatioByMoney"}],
  unknown: true,
}), {
  engine_mode: "custom",
  custom_product_fields: [{product: "SI.GFE", field: "OpenRatioByMoney"}],
});
assert.equal(
  api.canonicalKey("fee_custom_product_fields", manifest.defaults.fee_custom_product_fields),
  "custom_product_fields",
);
assert.deepEqual(
  api.visibleTabs(manifest, {fee_mode: "auto"}).map(item => item.key),
  ["engine", "cost"],
  "the cost tab remains available for fee_mode even when its custom row is hidden",
);
const view = api.render({
  context: {t: value => value}, manifest,
  inheritedValues: {engine_mode: "auto", fee_mode: "auto", custom_product_fields: []},
  overrides: {},
});
assert.deepEqual(view.value(), {});
const firstRow = view.children[1].children[0].children[0].children[0];
const firstToggle = firstRow.children[0];
assert.equal(firstToggle.checked, false);
firstToggle.checked = true;
firstToggle.listeners.change();
assert.deepEqual(view.value(), {engine_mode: "auto"});
console.log("ok");
