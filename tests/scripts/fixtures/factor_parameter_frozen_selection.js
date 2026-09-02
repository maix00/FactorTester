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
    this.className = "";
    this.classList = {add: name => { this.className += ` ${name}`; }};
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
let parameterChanges = 0;
const editor = window.FTFactorParameterEditor.create(
  {t: value => value},
  [{alias: "P", type: "FactorParam", default_value: "CA", options: []}],
  {},
  {
    factorItems: [{value: frozen.ref, label: frozen.alias, factor: frozen}],
    familyItems: [],
    onChange: () => { parameterChanges += 1; },
  },
);
const descendants = root => [root, ...(root.children || []).flatMap(descendants)];

assert.equal(pickers.length, 3);
assert.equal(pickers[1].options.items[0].label, frozen.alias,
  "factor picker must always present the human-readable alias");
pickers[1].options.onChange([frozen.ref]);
assert.equal(editor.values.P, frozen,
  "library selection must retain the complete frozen factor record");
assert.deepEqual(pickers[1].selected, [frozen.ref]);
assert.equal(parameterChanges, 1,
  "picker changes must notify the durable page-draft owner");
pickers[1].options.onChange([]);
assert.equal(editor.values.P, "",
  "clearing the selected picker must release the mutually-exclusive value");
assert.equal(parameterChanges, 2);
assert.equal(pickers.every(item => item.options.clearable === true), true,
  "all mutually-exclusive FactorParam pickers must allow clearing their selection");
const familyGroup = descendants(editor.root).find(item => (
  String(item.className).includes("factor-param-choice-family")
));
assert.ok(familyGroup, "family picker and create action must share the family choice row");
const nestedMount = editor.root.children.find(item => (
  String(item.className).includes("factor-param-nested-family-mount")
));
assert.ok(nestedMount, "nested parameters must mount beside the outer row, not inside Value");
console.log("ok");
