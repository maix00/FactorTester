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
    P: "CA", M: 0.6, B: "1", N: "200d",
  }},
  params: [
    {alias: "P", value: "CA"},
    {alias: "M", value: 0.6},
    {alias: "B", value: "1"},
    {alias: "N", value: "200d"},
  ],
};
const childFamily = {
  factor_family_alias: "SgChgPct",
  math_expr: String.raw`R_{\textcolor{red}{N}}Q_{\textcolor{red}{M}}(\textcolor{red}{P}_t-\textcolor{red}{P}_{t-\textcolor{red}{B}})`,
  parameter_definitions: [
    {alias: "P", type: "FactorParam", default_value: "CA"},
    {alias: "M", type: "FactorParam", default_value: 0.9},
    {alias: "B", type: "WindowParam", default_value: "5m"},
    {alias: "N", type: "WindowParam", default_value: "20d"},
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
const factorPicker = pickers.find(item => (
  item.options.name === "factor-param-factor-Th"
));
assert.ok(factorPicker, "FactorParam must expose a factor picker");

// Reopening an editor whose FactorParam already holds a frozen factor value
// (chosen earlier from the factor library) must land on the 因子库 source
// again — never degrade into a hand-typed manual ref/alias text box.
const reopened = window.FTFactorParameterEditor.create(
  {t: value => value},
  outerFamily.parameter_definitions,
  {Th: compactChild},
  {
    factorItems: [{
      value: childRef, label: compactChild.alias,
      factor: compactChild, family: childFamily,
    }],
    familyItems: [],
    onChange: () => {},
  },
);
const reopenedSource = pickers.filter(item => (
  item.options.name === "factor-param-source-Th"
)).at(-1);
const reopenedFactor = pickers.filter(item => (
  item.options.name === "factor-param-factor-Th"
)).at(-1);
assert.ok(reopenedSource, "reopened FactorParam must expose a source picker");
assert.ok(reopenedFactor, "reopened FactorParam must expose the factor-library picker");
assert.deepEqual(
  reopenedSource.selected, ["factor"],
  "a frozen factor-library value must reopen on the 因子库 source, not manual",
);
// The factor-library source renders the factor picker, not a text input.
const reopenedManualInputs = descendants(reopened.root).filter(
  item => item.tagName === "INPUT" && item.placeholder === "填写",
);
assert.equal(
  reopenedManualInputs.length, 0,
  "the factor-library source must not show a hand-typed text box",
);
// Reopening must also render the nested parameter table of the referenced
// factor, carrying the frozen identity values (not family defaults).
const reopenedNested = descendants(reopened.root).find(item => (
  item.className?.includes("factor-detail-parameter-editor")
    && item !== reopened.root
));
assert.ok(
  reopenedNested,
  "reopened frozen factor must render its nested parameter table",
);
const nestedText = descendants(reopenedNested).map(item => item.textContent);
assert.ok(
  nestedText.includes("0.6"),
  "nested table must show the saved identity value (M:0.6), not the family default",
);

// A hand-typed alias stays on the manual source with its text intact.
const manual = window.FTFactorParameterEditor.create(
  {t: value => value},
  outerFamily.parameter_definitions,
  {Th: "SgChgPct|P:[CA]|M:0.6|B:1|N:200d|$F:1d"},
  {factorItems: [], familyItems: [], onChange: () => {}},
);
const manualSource = pickers.filter(item => (
  item.options.name === "factor-param-source-Th"
)).at(-1);
assert.deepEqual(
  manualSource.selected, ["manual"],
  "a hand-typed alias must reopen on the manual source",
);
// The hand-typed alias parses into a read-only nested parameter table.
const manualNested = descendants(manual.root).find(item => (
  item.className?.includes("factor-detail-parameter-editor")
    && item !== manual.root
));
assert.ok(
  manualNested,
  "a hand-typed alias must parse into a read-only nested parameter table",
);
const manualText = descendants(manualNested).map(item => item.textContent);
assert.ok(
  manualText.includes("M") && manualText.includes("0.6"),
  "alias rows must carry the parsed parameter names and values",
);

// Manual numeric constants parse into a ConstExpr preview…
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
assert.ok(
  (numericPreview.textContent || "").includes("ConstExpr 0.6"),
  "numeric manual value must parse as ConstExpr",
);
// …and bare data columns parse into a ColumnRef preview.
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
assert.ok(
  (columnPreview.textContent || "").includes("ColumnRef CLOSE"),
  "column manual value must parse as ColumnRef",
);

(async () => {
  await factorPicker.options.onChange([childRef]);
  assert.equal(resolveCalls, 1, "selected factors must be enriched lazily");
  assert.equal(latestValues.Th.parameter_definitions[2].type, "WindowParam");
  const nested = descendants(editor.root).find(item => (
    item.className?.includes("factor-detail-parameter-editor")
      && item !== editor.root
  ));
  assert.ok(nested, "selected factors must render a nested read-only table");
  assert.ok(descendants(nested).some(item => item.textContent === "WindowParam"));

  const preview = window.FTFactorDetailShared.previewExpression(
    outerFamily, latestValues,
  );
  assert.match(preview, /\\textcolor\{blue\}\{\\mathrm\{SgChgPct\}\}_t :=/);
  assert.match(preview, /\\textcolor\{red\}\{200\\,\\mathrm\{d\}\}/);
  assert.match(preview, /D_t\(\\textcolor\{blue\}\{\\mathrm\{SgChgPct\}\}_t\)/);
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
