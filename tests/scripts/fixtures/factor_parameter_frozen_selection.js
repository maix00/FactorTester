const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag = "div") {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.listeners = {};
    this.value = "";
    this.textContent = "";
  }
  append(...children) { this.children.push(...children); }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setCustomValidity() {}
}

global.document = {createElement: tag => new Element(tag)};
global.window = globalThis;
global.FTUI = window.FTUI = {helpIcon: () => new Element("span")};
const pickers = [];
window.FTTestObjectPicker = {
  create(_context, options) {
    const picker = {
      element: new Element("div"), options,
      selected: [...(options.selected || [])],
      setValues(values) { this.selected = [...values]; },
    };
    pickers.push(picker);
    return picker;
  },
};

vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-parameter-editor.js", "utf8"),
  {filename: "factor-parameter-editor.js"},
);

const frozen = {
  schema_version: 2,
  ref: `factor:v2:${"a".repeat(43)}`,
  alias: "Nested|N:5d",
  owner_ref: "principal:alice",
  identity: {
    family_alias: "Nested",
    family_formula_fingerprint: "b".repeat(64),
    self_formula_fingerprint: "c".repeat(64),
    params: {N: "5d"},
  },
};
const editor = window.FTFactorParameterEditor.create(
  {t: value => value},
  [{alias: "P", type: "FactorParam", default_value: "CA", options: []}],
  {},
  {
    factorItems: [{value: frozen.ref, label: frozen.alias, factor: frozen}],
    familyItems: [],
  },
);

assert.equal(pickers.length, 3);
assert.equal(pickers[1].options.items[0].label, frozen.alias,
  "factor picker must always present the human-readable alias");
pickers[1].options.onChange([frozen.ref]);
assert.equal(editor.values.P, frozen,
  "library selection must retain the complete frozen factor record");
assert.deepEqual(pickers[1].selected, [frozen.ref]);
console.log("ok");
