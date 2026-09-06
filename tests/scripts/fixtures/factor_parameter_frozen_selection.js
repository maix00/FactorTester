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
  parameterDisplayValue: parameter => String(parameter?.value ?? ""),
  parameterSection(_context, _value, rows, depth = 0, options = {}) {
    const root = new Element("details");
    root.className = "factor-detail-parameter-tree"
      + (depth ? " factor-detail-parameter-tree-nested" : "");
    if (options.content) root.append(options.content);
    for (const row of (rows || [])) {
      const line = new Element("div");
      line.value = row?.value ?? "";
      root.append(line);
    }
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
  parameter_definitions: [{alias: "N", type: "WindowParam", value: "5d", default_value: "5d"}],
};
const descendants = root => [root, ...(root.children || []).flatMap(descendants)];

(async () => {
  let parameterChanges = 0;
  const editor = window.FTFactorParameterEditor.create(
    {t: value => value},
    [{alias: "P", type: "FactorParam", default_value: "CA", options: [
      {value: "CA", label: "CA"},
    ]}],
    {},
    {
      factorItems: [{value: frozen.ref, label: frozen.alias, factor: frozen}],
      onSelectFactor: async factor => factor,
    onValidateFactorAlias: async () => ({valid: true, factor_alias: frozen.alias, factor: frozen}),
      onChange: () => { parameterChanges += 1; },
    },
  );
  const nestedMount = editor.root.children.find(item => (
    String(item.className).includes("factor-param-nested-factor-mount")
  ));
  assert.ok(nestedMount, "nested parameters must mount beside the outer row");

  assert.equal(pickers.length, 1, "only the unified value picker is created");
  const valuePicker = pickers[0];
  assert.equal(valuePicker.options.multi, false, "FactorParam is single-select");
  assert.equal(valuePicker.options.groupByType, true, "candidates are grouped by type");
  assert.ok(valuePicker.options.exclusiveManual, "FactorParam exposes the 手填排他 manual entry");
  assert.ok(valuePicker.options.onAddCandidateForType, "FactorParam supports on-the-fly creation");
  assert.equal(valuePicker.options.onAddCandidateForType("column", {}, {}), undefined,
    "a DataColumn cannot be created on the fly");

  const factorItem = valuePicker.options.items.find(item => item.type === "factor");
  assert.ok(factorItem, "factor candidates are present");
  assert.equal(factorItem.label, frozen.alias, "factor picker presents the alias");
  assert.equal(Boolean(factorItem.onsite || factorItem.temporary), false,
    "a catalog factor does not receive an onsite badge");
  assert.ok(valuePicker.options.items.some(item => item.type === "column"),
    "DataColumn candidates are present");

  await valuePicker.options.onChange([frozen.ref]);
  assert.equal(editor.values.P, frozen, "library selection retains the complete frozen record");
  assert.ok(descendants(nestedMount).some(item => (
    String(item.className).includes("factor-detail-parameter-tree")
  )), "selected factor renders its read-only nested parameter table");
  assert.equal(descendants(nestedMount).filter(item => item.tagName === "INPUT").length, 0,
    "selected factor parameter table must NOT expose editable inputs (read-only)");
  assert.equal(parameterChanges, 1, "selection notifies the durable page-draft owner");

  await valuePicker.options.onChange([]);
  assert.equal(editor.values.P, "", "clearing the value releases it");
  assert.equal(parameterChanges, 2);

  const edited = {...frozen, ref: `factor:v2:${"e".repeat(43)}`,
    alias: "Nested|N:10d", identity: {...frozen.identity, params: {N: "10d"}}};
  const editedItem = {...factorItem, value: edited.ref, label: edited.alias, factor: edited};
  valuePicker.options.onTemporaryCandidateUpdated(factorItem, editedItem, edited);
  await valuePicker.options.onChange([edited.ref]);
  assert.equal(editor.values.P, edited, "edited candidate updates the owner's frozen configuration");
  valuePicker.options.onTemporaryCandidateRemoved(editedItem);
  await valuePicker.options.onChange([]);
  assert.equal(editor.values.P, "", "deleting the selected candidate releases its frozen reference");

  await valuePicker.options.onChange(["0"]);
  assert.equal(editor.values.P, 0, "a numeric constant remains a value (ConstExpr)");
  await valuePicker.options.onChange(["Nested|N:5d"]);
  assert.ok(descendants(nestedMount).some(item => (
    String(item.className).includes("factor-detail-parameter-tree")
  )), "an alias resolved from manual input renders a read-only factor tree");

  const restored = window.FTFactorParameterEditor.create(
    {t: value => value},
    [{alias: "P", type: "FactorParam", default_value: "CA", options: []}],
    {P: frozen.alias},
    {factorItems: [{value: frozen.ref, label: frozen.alias, factor: frozen}]},
  );
  assert.equal(restored.values.P, frozen, "a persisted factor alias normalises to its frozen record");
  assert.ok(descendants(restored.root).some(item => (
    String(item.className).includes("factor-detail-parameter-tree")
  )), "a restored factor alias renders its read-only nested parameter table");

  const isolated = window.FTFactorParameterEditor.create(
    {t: value => value},
    [{alias: "P", type: "FactorParam", options: []}],
    {P: frozen}, {factorItems: []},
  );
  const isolatedPicker = pickers.at(-1);
  assert.equal(isolated.values.P.ref, frozen.ref);
  assert.deepEqual(isolatedPicker.selected, [frozen.ref]);
  assert.equal(isolatedPicker.options.items.find(x => x.value === frozen.ref)?.label,
    frozen.alias, "a frozen nested value remains displayable outside the global catalog");
  assert.equal(isolatedPicker.options.items.find(x => x.value === frozen.ref)?.onsite,
    true, "a selected factor outside the catalog receives the onsite badge");
  const otherRevision = {...frozen, ref: "factor:v2:other-revision"};
  const exact = window.FTFactorParameterEditor.create(
    {t: value => value}, [{alias: "P", type: "FactorParam", options: []}],
    {P: frozen}, {factorItems: [{value: otherRevision.ref, factor: otherRevision}]},
  );
  assert.equal(exact.values.P.ref, frozen.ref, "matching alias must not replace a frozen identity");
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
