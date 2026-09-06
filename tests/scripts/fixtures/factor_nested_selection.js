const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag = "div") {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.listeners = {};
    this.className = "";
    this.value = "";
    this.textContent = "";
    this.dataset = {};
    this.classList = {
      add: name => { this.className += ` ${name}`; },
      toggle: (name, enabled) => {
        const values = new Set(this.className.split(/\s+/).filter(Boolean));
        if (enabled) values.add(name); else values.delete(name);
        this.className = [...values].join(" ");
      },
    };
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setCustomValidity() {}
  setAttribute() {}
}

global.document = {createElement: tag => new Element(tag)};
global.window = globalThis;
window.FTUI = {
  helpIcon: () => new Element("button"),
  iconButton(_context, _symbol, label, handler) {
    const button = new Element("button");
    button.className = "icon-action-button";
    button.textContent = label;
    button.addEventListener("click", handler);
    return button;
  },
  table(headers, values) {
    const shell = new Element("table");
    shell.headers = headers;
    shell.values = values;
    return {shell};
  },
};
window.FTFactorModel = {factorExpression: value => value?.math_expr || ""};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-detail-shared.js", "utf8"),
  {filename: "factor-detail-shared.js"},
);
vm.runInThisContext(
  fs.readFileSync(
    "server/manager/web/catalog/shared/factor-parameter-section.js", "utf8",
  ),
  {filename: "factor-parameter-section.js"},
);
const pickers = [];
function descendants(root) {
  const result = [];
  for (const child of root?.children || []) {
    result.push(child, ...descendants(child));
  }
  return result;
}
window.FTTestObjectPicker = {
  create(_context, options) {
    const picker = {
      element: new Element("div"), options,
      selected: [...(options.selected || [])],
      setValues(values) { this.selected = [...values]; },
      setItems(items) { this.options.items = items; },
    };
    pickers.push(picker);
    return picker;
  },
};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-parameter-editor.js", "utf8"),
  {filename: "factor-parameter-editor.js"},
);

const childRef = `factor:v2:${"c".repeat(43)}`;
const compactChild = {
  schema_version: 2,
  ref: childRef,
  alias: "SgChgPct|P:[CA]|M:0.6|B:1|N:200d|$F:1d",
  factor_alias: "SgChgPct|P:[CA]|M:0.6|B:1|N:200d|$F:1d",
  factor_family_alias: "SgChgPct",
  identity: {family_alias: "SgChgPct", params: {
    P: "CA", M: 0.6, B: "1", N: "200d", $F: "1d", $Rev: 0,
  }},
  params: [
    {alias: "P", value: "CA"},
    {alias: "M", value: 0.6},
    {alias: "B", value: "1"},
    {alias: "N", value: "200d"},
    {alias: "$F", value: "1d"},
    {alias: "$Rev", value: 0},
  ],
};
const childFamily = {
  factor_family_alias: "SgChgPct",
  math_expr: String.raw`\textcolor{red}{\$Rev}\cdot \operatorname{Resample}_{\textcolor{red}{\$F}}(R_{\textcolor{red}{N}}Q_{\textcolor{red}{M}}(\textcolor{red}{P}_t-\textcolor{red}{P}_{t-\textcolor{red}{B}}))`,
  parameter_definitions: [
    {alias: "P", type: "FactorParam", default_value: "CA"},
    {alias: "M", type: "FactorParam", default_value: 0.9},
    {alias: "B", type: "WindowParam", default_value: "5m"},
    {alias: "N", type: "WindowParam", default_value: "20d"},
    {alias: "$F", type: "FactorFrequencyParam", default_value: "1d"},
    {alias: "$Rev", type: "ReverseSignalParam", default_value: 0},
  ],
};
const outerFamily = {
  factor_family_alias: "SgChgDurDay",
  math_expr: String.raw`D_t(\textcolor{red}{Th}_t)`,
  parameter_definitions: [{alias: "Th", type: "FactorParam", default_value: 0.001}],
};
assert.equal(
  window.FTFactorDetailShared.parameterRows({
    parameter_definitions: [{alias: "N", type: "Parameter", default_value: "20d"}],
    family_parameter_definitions: [{alias: "N", type: "WindowParam", default_value: "20d"}],
  })[0].type,
  "WindowParam",
  "a specific family parameter type must win over a generic projection",
);

let latestValues = {};
let resolveCalls = 0;
const editor = window.FTFactorParameterEditor.create(
  {t: value => value},
  outerFamily.parameter_definitions,
  {},
  {
    factorItems: [{
      value: childRef, label: compactChild.alias, factor: compactChild,
      family: childFamily,
    }],
    familyItems: [],
    onSelectFactor: async factor => {
      resolveCalls += 1;
      return {
        ...factor,
        ...childFamily,
        params: factor.params,
        parameter_definitions: childFamily.parameter_definitions,
      };
    },
    onChange: values => { latestValues = values; },
  },
);
const valuePicker = pickers.find(item => item.options.name === "factor-param-Th");
assert.ok(valuePicker, "FactorParam must expose the unified multi-type value picker");
assert.equal(valuePicker.options.multi, false, "FactorParam is a single-select");
assert.equal(valuePicker.options.groupByType, true, "candidates are grouped by type");
assert.ok(valuePicker.options.exclusiveManual, "FactorParam exposes 手填排他");
assert.ok(valuePicker.options.onAddCandidateForType, "FactorParam supports on-the-fly creation");

(async () => {
  // Selecting a factor resolves through the host (nested family source fixed)
  // and renders a read-only nested parameter table carrying saved identity
  // values (not family defaults), with family parameter types.
  await valuePicker.options.onChange([childRef]);
  assert.equal(resolveCalls, 1, "selected factors must be resolved lazily");
  assert.equal(latestValues.Th.parameter_definitions[2].type, "WindowParam",
    "enriched factor carries the family parameter types");
  assert.equal(latestValues.Th.identity.params.M, 0.6,
    "saved identity value is kept, not the family default");
  const nested = descendants(editor.root).find(item => (
    item.className?.includes("factor-detail-parameter-editor")
      && item !== editor.root
  ));
  assert.ok(nested, "selected factors render a nested read-only parameter table");
  assert.ok(descendants(nested).some(item => item.textContent === "WindowParam"));
  assert.equal(descendants(nested).filter(item => item.tagName === "INPUT").length, 0,
    "the factor parameter table stays read-only");
  const pencil = descendants(nested).find(item => item.textContent === "编辑");
  assert.ok(pencil);
  const beforePencil = latestValues.Th;
  const changesBeforePencil = {...latestValues.Th};
  await pencil.listeners.click({preventDefault() {}, stopPropagation() {}});
  assert.equal(latestValues.Th, beforePencil, "pencil alone does not replace the factor");
  assert.deepEqual(latestValues.Th, changesBeforePencil, "pencil does not mark the factor temporary");
  const editableInputs = descendants(editor.root).filter(item => item.tagName === "INPUT");
  const windowInput = editableInputs.find(item => item.value === "200d");
  assert.ok(windowInput, "pencil exposes the existing typed parameter editor");
  windowInput.value = "25d";
  windowInput.listeners.input();
  assert.equal(latestValues.Th.parameter_values.N, "25d");
  assert.equal(latestValues.Th.__factor_family_draft, true,
    "changed parameters reuse the existing save-time freezer");
  assert.equal(latestValues.Th.parameter_values.M, 0.6, "untouched values survive");
  assert.equal(latestValues.Th.__factor_family.math_expr, childFamily.math_expr,
    "first nested edit retains the loaded source template for the outer preview");
  assert.equal(compactChild.identity.params.N, "200d", "library identity remains immutable");

  // Editing a nested reverse flag refreshes the already-mounted local formula
  // in place.  This is the regression for `$Rev=1` missing the red minus in
  // edit mode; the outer onChange callback alone does not redraw this section.
  const nestedFormula = descendants(editor.root).find(item => (
    item.className?.includes("factor-detail-local-formula")
  ));
  assert.ok(nestedFormula, "nested factor keeps its local formula mount");
  assert.ok(nestedFormula.children[1].textContent.includes(String.raw`\textcolor{red}{\$Rev}\cdot `),
    "parameter mode shows the symbolic red direction multiplier");
  const reverseInput = descendants(editor.root).find(item => (
    item.tagName === "INPUT" && String(item.value) === "0"
  ));
  assert.ok(reverseInput, "editable nested table exposes the $Rev input");
  const valueToggle = descendants(nestedFormula).find(item => (
    item.tagName === "BUTTON" && item.textContent === "值"
  ));
  assert.ok(valueToggle, "nested formula exposes the values mode");
  valueToggle.listeners.click();
  reverseInput.value = "1";
  reverseInput.listeners.input();
  assert.match(
    nestedFormula.children[1].textContent,
    /\\textcolor\{red\}\{-\}\\operatorname\{Resample\}/,
    "nested formula redraws with the red reverse sign",
  );

  // Reopening a frozen factor value renders its read-only nested table (and the
  // value picker shows the frozen factor selected), without degrading to manual.
  const reopened = window.FTFactorParameterEditor.create(
    {t: value => value},
    outerFamily.parameter_definitions,
    {Th: compactChild},
    {
      factorItems: [{
        value: childRef, label: compactChild.alias,
        factor: compactChild, family: childFamily,
      }],
      familyItems: [], onChange: () => {},
    },
  );
  assert.equal(reopened.values.Th, compactChild,
    "a frozen factor value is preserved on reopen");
  const reopenedPicker = pickers.filter(item => item.options.name === "factor-param-Th").at(-1);
  assert.deepEqual(reopenedPicker.selected, [childRef],
    "reopened frozen factor shows the factor candidate selected");
  assert.ok(descendants(reopened.root).some(item => (
    item.className?.includes("factor-detail-parameter-editor")
      && item !== reopened.root
  )), "reopened frozen factor renders its read-only nested parameter table");

  // A same-alias library row must not replace a different frozen version.
  const aliasReopen = window.FTFactorParameterEditor.create(
    {t: value => value},
    outerFamily.parameter_definitions,
    {Th: compactChild},
    {
      factorItems: [{
        value: `factor:v2:${"a".repeat(43)}`,
        label: compactChild.alias,
        factor: {...compactChild, ref: `factor:v2:${"a".repeat(43)}`},
        family: childFamily,
      }],
      familyItems: [], onChange: () => {},
    },
  );
  assert.equal(aliasReopen.values.Th.ref, compactChild.ref,
    "an alias match preserves the selected immutable identity");

  // Hand-typed numeric constant → ConstExpr preview.
  const numericParam = window.FTFactorParameterEditor.create(
    {t: value => value},
    outerFamily.parameter_definitions,
    {Th: "0.6"},
    {factorItems: [], familyItems: [], onChange: () => {}},
  );
  const numericPreview = descendants(numericParam.root).find(
    item => item.className === "factor-param-manual-preview",
  );
  assert.ok(numericPreview, "numeric manual value must show a parse preview");
  assert.ok((numericPreview.textContent || "").includes("ConstExpr 0.6"),
    "numeric manual value parses as ConstExpr");

  // Hand-typed bare data column → ColumnRef preview.
  const columnParam = window.FTFactorParameterEditor.create(
    {t: value => value},
    outerFamily.parameter_definitions,
    {Th: "CLOSE"},
    {factorItems: [], familyItems: [], onChange: () => {}},
  );
  const columnPreview = descendants(columnParam.root).find(
    item => item.className === "factor-param-manual-preview",
  );
  assert.ok(columnPreview, "column manual value must show a parse preview");
  assert.ok((columnPreview.textContent || "").includes("ColumnRef CLOSE"),
    "column manual value parses as ColumnRef");

  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
