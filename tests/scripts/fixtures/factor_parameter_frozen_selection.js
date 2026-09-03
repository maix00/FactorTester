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
    this.dataset = {};
    this.classList = {add: name => { this.className += ` ${name}`; }};
  }
  append(...children) { this.children.push(...children); }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setCustomValidity() {}
}

global.document = {createElement: tag => new Element(tag)};
global.window = globalThis;
global.FTUI = window.FTUI = {helpIcon: () => new Element("span")};
window.FTFactorDetailShared = {
  createParameterList(_context, parameters, initial, options) {
    const values = {...initial};
    const root = new Element("section");
    root.className = "factor-detail-parameter-editor";
    for (const parameter of parameters) {
      const row = new Element("div");
      const value = new Element("div");
      const alias = parameter.alias || parameter.name;
      values[alias] = values[alias] ?? parameter.default_value ?? "";
      const rendered = options.renderValue(
        value, parameter, values[alias], values, row,
      );
      row.append(value);
      root.append(row);
      if (rendered?.nested) root.append(rendered.nested);
    }
    return {root, values};
  },
  familySourceHelp: () => new Element("span"),
  localFormula: () => ({root: new Element("div"), update() {}}),
  previewExpression: () => "",
  parameterRows(value) {
    const list = value?.parameter_definitions || value?.params || [];
    return Array.isArray(list)
      ? list.map(parameter => ({...parameter, alias: parameter.alias || parameter.name}))
      : [];
  },
  parameterSection(_context, _value, rows, depth = 0, options = {}) {
    const root = new Element("details");
    root.className = "factor-detail-parameter-tree"
      + (depth ? " factor-detail-parameter-tree-nested" : "");
    if (options.content) root.append(options.content);
    return {root, update() {}};
  },
};
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
  factor_family_alias: "Nested",
  parameter_definitions: [{
    alias: "N", type: "WindowParam", value: "5d", default_value: "5d",
  }],
};
const nestedFamily = {
  family_ref: "factor-family:v2:nested",
  factor_family_alias: "NestedFamily",
  params: [],
};
const loadedNestedFamily = {
  ...nestedFamily,
  params: [{alias: "N", type: "WindowParam", default_value: "5d"}],
};
let parameterChanges = 0;
const editor = window.FTFactorParameterEditor.create(
  {t: value => value},
  [{alias: "P", type: "FactorParam", default_value: "CA", options: []}],
  {},
  {
    factorItems: [{value: frozen.ref, label: frozen.alias, factor: frozen}],
    familyItems: [{
      value: nestedFamily.family_ref,
      label: nestedFamily.factor_family_alias,
      family: nestedFamily,
    }],
    onSelectFamily: async () => loadedNestedFamily,
    onValidateFactorAlias: async () => ({
      valid: true, factor_alias: frozen.alias, factor: frozen,
    }),
    onChange: () => { parameterChanges += 1; },
  },
);
const descendants = root => [root, ...(root.children || []).flatMap(descendants)];
const nestedMount = editor.root.children.find(item => (
  String(item.className).includes("factor-param-nested-factor-mount")
));
assert.ok(nestedMount, "nested parameters must mount beside the outer row, not inside Value");

assert.equal(pickers.length, 4);
const sourcePicker = pickers.find(picker => (
  picker.options.name === "factor-param-source-P"
));
const factorPicker = pickers.find(picker => (
  picker.options.name === "factor-param-factor-P"
));
const familyPicker = pickers.find(picker => (
  picker.options.name === "factor-param-family-P"
));
assert.ok(sourcePicker, "FactorParam must expose a source-type picker");
assert.ok(factorPicker, "FactorParam must expose a factor picker");
assert.ok(familyPicker, "FactorParam must expose a family picker");
assert.equal(factorPicker.options.items[0].label, frozen.alias,
  "factor picker must always present the human-readable alias");
factorPicker.options.onChange([frozen.ref]);
assert.equal(editor.values.P, frozen,
  "library selection must retain the complete frozen factor record");
assert.deepEqual(factorPicker.selected, [frozen.ref]);
assert.ok(descendants(nestedMount).some(item => (
  String(item.className).includes("factor-detail-parameter-tree")
)), "selected factor must render its read-only nested parameter tree");
assert.equal(descendants(nestedMount).filter(item => item.tagName === "INPUT").length, 0,
  "selected factor parameter tree must not expose editable inputs");
assert.equal(parameterChanges, 1,
  "picker changes must notify the durable page-draft owner");
factorPicker.options.onChange([]);
assert.equal(editor.values.P, "",
  "clearing the selected picker must release the mutually-exclusive value");
assert.equal(parameterChanges, 2);
assert.equal(factorPicker.selected.length, 0,
  "clearing a picker must leave it with no selected object");
sourcePicker.options.onChange(["manual"]);
const manualInput = descendants(editor.root).find(item => item.tagName === "INPUT");
assert.ok(manualInput, "FactorParam must expose its manual input");
manualInput.value = "0";
manualInput.listeners.change();
assert.equal(editor.values.P, 0,
  "a zero constant must remain a value rather than being treated as empty");
manualInput.value = "";
manualInput.listeners.input();
assert.equal(editor.values.P, "",
  "emptying the manual input must release the mutually-exclusive value");
assert.equal(parameterChanges, 5);
const referenceControl = descendants(editor.root).find(item => (
  String(item.className).includes("factor-param-reference-control")
));
assert.ok(referenceControl, "FactorParam must keep the source picker and value control on one row");
const factorRow = descendants(editor.root).find(item => (
  String(item.className).includes("factor-detail-parameter-row")
));
assert.ok(factorRow, "FactorParam must render as a parameter row");
assert.ok(String(factorRow.className).includes("factor-detail-parameter-row-factor"),
  "FactorParam row must keep a divider before its nested parameter mount");

const restored = window.FTFactorParameterEditor.create(
  {t: value => value},
  [{alias: "P", type: "FactorParam", default_value: "CA", options: []}],
  {P: frozen.alias},
  {
    factorItems: [{value: frozen.ref, label: frozen.alias, factor: frozen}],
    familyItems: [],
  },
);
assert.equal(restored.values.P, frozen,
  "a persisted factor alias should be normalised to its frozen record");
assert.ok(descendants(restored.root).some(item => (
  String(item.className).includes("factor-detail-parameter-tree")
)), "a restored factor alias must render its read-only nested parameter tree");

(async () => {
  await familyPicker.options.onChange([nestedFamily.family_ref]);
  assert.deepEqual(familyPicker.selected, [nestedFamily.family_ref],
    "selected family must remain selected after its parameters load");
  assert.equal(editor.values.P.__factor_family.factor_family_alias,
    nestedFamily.factor_family_alias);
  assert.ok(descendants(nestedMount).some(item => (
    String(item.className).includes("factor-detail-parameter-editor")
  )), "selected family must render its nested parameter table");
  assert.ok(descendants(nestedMount).some(item => item.tagName === "INPUT"),
    "nested family parameter table must expose editable parameter fields");
  manualInput.value = frozen.alias;
  await manualInput.listeners.change();
  assert.ok(descendants(nestedMount).some(item => (
    String(item.className).includes("factor-detail-parameter-tree")
  )), "an alias resolved from manual input must render a read-only factor tree");
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
