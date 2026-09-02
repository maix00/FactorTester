const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class Element {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.listeners = {};
    this.dataset = {};
    this.attributes = {};
    this.className = "";
    this.classList = {
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
  setAttribute(name, value) { this.attributes[name] = String(value); }
  focus() { this.focused = true; }
}

global.Node = Element;
global.document = {createElement: tagName => new Element(tagName)};
global.CustomEvent = class CustomEvent { constructor(type, options) {
  this.type = type; this.detail = options?.detail;
} };
global.navigator.clipboard = {async writeText(value) { navigator.copied = value; }};
global.window = {};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-model.js", "utf8"),
  {filename: "factor-model.js"},
);
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-detail-shared.js", "utf8"),
  {filename: "factor-detail-shared.js"},
);
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-display-enrichment.js", "utf8"),
  {filename: "factor-display-enrichment.js"},
);
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/shared/object-detail-tabs.js", "utf8"),
  {filename: "object-detail-tabs.js"},
);
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/shared/object-job-table.js", "utf8"),
  {filename: "object-job-table.js"},
);
global.FTUI = window.FTUI = {
  helpIcon(text) { const item = new Element("button"); item.helpText = text; return item; },
  code(value, options = {}) {
    const pre = new Element("pre");
    pre.className = ["json-code", "code-viewer", options.className || ""]
      .filter(Boolean).join(" ");
    const body = new Element("code");
    body.textContent = String(value || "");
    body.className = options.language ? `language-${options.language}` : "";
    pre.append(body);
    return pre;
  },
  fieldRows(value) { return Object.entries(value || {}); },
  loading(label) { const item = new Element(); item.textContent = label; return item; },
  table(headers, values) {
    const shell = new Element("table");
    shell.headers = headers;
    shell.values = values;
    const body = {rows: values.map(() => new Element("tr"))};
    shell._row = body.rows[0];
    return {shell, body};
  },
};
window.FTMultiSelectFilter = {
  create(_context, options = {}) {
    const element = new Element("section");
    element.className = "ft-multi-select-filter";
    element.pickerOptions = options;
    return {
      element,
      setItems(items) { element.items = items; },
    };
  },
};
const rendered = [];
global.katex = window.katex = {
  render(expression, mount, options) {
    rendered.push({expression, mount, options});
  },
};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-details.js", "utf8"),
  {filename: "factor-details.js"},
);

const alias = "MmRateOfChg|P:[CA]|N:20d|$F:1d";
const factorRef = `factor:v2:${"x".repeat(43)}`;
const setRef = `factor-set:v2:${"y".repeat(43)}`;

const navigated = [];
const content = new Element();
const toolbar = new Element();
const context = {
  t: value => value, content, toolbar,
  button(label, handler) {
    const button = new Element("button");
    button.textContent = label; button.listeners.click = handler; return button;
  },
  setHeading(name, scope) { this.heading = {name, scope}; },
  updateActiveTab() {},
  navigate(path) { navigated.push(path); },
  isRouteCurrent() { return true; },
  async api(path) {
    assert.match(path, /factor-sets\/detail/);
    return {
      factor_set: {
        target_ref: setRef,
        title_zh: "动量集合",
        has_more: false,
        related_references: [{
          kind: "factor", label: alias, target_ref: factorRef,
        }],
      },
    };
  },
};
const data = {
  factors: [{
    schema_version: 2,
    ref: factorRef,
    alias,
    owner_ref: "profile:maxa",
    identity: {
      family_ref: `factor-family:v2:${"z".repeat(43)}`,
      family_alias: "MmRateOfChg",
      family_formula_fingerprint: "a".repeat(64),
      self_formula_fingerprint: "b".repeat(64),
      params: {N: "20d"},
    },
    factor_ref: factorRef,
    factor_alias: alias,
    factor_family_name: "MmRateOfChg",
    factor_family_alias: "MmRateOfChg",
    math_expr: "\\frac{P_t-P_{t-N}}{P_{t-N}}",
    description: "端点变化率",
    owner_alias: "MaxA",
    params: [{alias: "N", value: "20d"}],
  }],
  families: [{
    family_ref: "factor-family:sha256:momentum",
    factor_family_alias: "MmRateOfChg",
    factor_family_name: "MmRateOfChg",
    factor_kind: "custom",
    owner_username: "alice",
    owner_alias: "Alice",
    description: "动量变化率",
    source_code: "class MmRateOfChg(FactorFamily):\n    pass\n",
    parameter_definitions: [{
      alias: "N", type: "WindowParam", default_value: "20d",
      input_help: "填写窗口长度，例如 20d。",
    }],
    factor_refs: [],
  }],
  sets: [{target_ref: setRef, visibility: "server"}],
};

function walk(root) {
  const result = [];
  const visit = value => {
    if (!value || typeof value !== "object") return;
    result.push(value);
    (value.children || []).forEach(visit);
  };
  visit(root);
  return result;
}

assert.deepStrictEqual(
  window.FTFactorDetailShared.familyIdentity({factor_family_ref: "family:momentum"}),
  {alias: "", fingerprint: ""},
);

const preview = window.FTFactorDetailShared.previewExpression({
  math_expr: String.raw`x_{\textcolor{red}{N},\textcolor{red}{P}}`,
  parameter_definitions: [
    {alias: "N", value: "20d"},
    {alias: "P", value: "CA"},
  ],
}, {N: "5m", P: 0.9});
assert.match(preview, /5\\,\\mathrm\{m\}/);
assert.match(preview, /\\mathrm\{0\.9\}/);

const nestedFamily = {
  factor_family_alias: "SgChgPct",
  math_expr: "\\operatorname{Quantile}_{\\textcolor{red}{M}}"
    + "(\\textcolor{red}{P}_t-\\textcolor{red}{P}_{t-\\textcolor{red}{B}})",
  parameter_definitions: [
    {alias: "P", value: "CA"},
    {alias: "B", value: "5m"},
    {alias: "M", value: 0.9},
  ],
};
const nestedPreview = window.FTFactorDetailShared.previewExpression({
  factor_family_alias: "SgChgDurDay",
  math_expr: "\\operatorname{argmin}(\\textcolor{red}{Th}_t)",
  parameter_definitions: [{
    alias: "Th", type: "FactorParam", value: {
      __factor_family_draft: true,
      __factor_family: nestedFamily,
      parameter_values: {P: "CA", B: "5m", M: 0.9},
    },
  }],
}, {});
assert.match(nestedPreview, /\\begin\{aligned\}/);
assert.match(nestedPreview, /\\mathrm\{SgChgPct\}_t &:=/);
assert.match(nestedPreview, /\\textcolor\{red\}\{\\mathrm\{CA\}\}/);
assert.match(nestedPreview, /\\textcolor\{red\}\{\\mathrm\{SgChgPct\}\}/);
assert.ok(
  nestedPreview.indexOf("\\mathrm{SgChgPct}_t &:=")
    < nestedPreview.indexOf("\\operatorname{argmin}"),
  "nested factor must be rendered as a preceding intermediate definition",
);

(async () => {
  const sourceView = window.FTFactorDetailShared.source(context, {
    source_code: "class MmRateOfChg(FactorFamily):\n    pass\n",
  });
  assert.strictEqual(sourceView.children[0].children[0].textContent, "Python 源码");
  assert.match(sourceView.children[1].children[0].textContent, /MmRateOfChg/);
  await sourceView.children[0].children[1].listeners.click();
  assert.match(navigator.copied, /FactorFamily/);

  await window.FTFactorDetails.factorDetail(
    context, data, factorRef, async () => {
      throw new Error("native catalog is unavailable");
    },
  );
  assert.strictEqual(context.heading.name, alias);
  assert.strictEqual(rendered.at(-1).expression, "\\frac{P_t-P_{t-N}}{P_{t-N}}");
  assert.strictEqual(toolbar.children[0].textContent, "查看因子序列");
  toolbar.children[0].listeners.click();
  assert.strictEqual(
    navigated.at(-1), `/factor-series?factor_ref=${encodeURIComponent(factorRef)}`,
  );
  const parameterTable = walk(content).find(item => (
    item.headers?.[0] === "参数"
  ));
  assert.ok(parameterTable);
  assert.deepStrictEqual(parameterTable.headers, ["参数", "参数类别", "值"]);
  assert.ok(parameterTable.values.some(row => row[0] === "N"));
  assert.strictEqual(parameterTable.values[0][1].children[0].textContent, "WindowParam");
  assert.match(parameterTable.values[0][1].children[1].helpText, /窗口长度/);
  const provenance = walk(content).find(item => (
    item.headers?.[0] === "RunSpec 字段"
  ));
  assert.ok(provenance.values.some(row => row[0] === "冻结因子家族"));
  assert.ok(provenance.values.some(row => row[1].children?.[0]?.textContent === "MmRateOfChg"));

  const nestedFactorRef = `factor:v2:${"n".repeat(43)}`;
  const nestedOuterRef = `factor:v2:${"o".repeat(43)}`;
  const nestedLeaf = {
    schema_version: 2,
    ref: nestedFactorRef,
    alias: "MmThreshold|N:5d",
    factor_alias: "MmThreshold|N:5d",
    factor_family_alias: "MmThreshold",
    identity: {family_alias: "MmThreshold", params: {N: "5d"}},
    params: [{alias: "N", value: "5d"}],
  };
  const nestedOuter = {
    schema_version: 2,
    ref: nestedOuterRef,
    alias: "MmOuter|Th:MmThreshold|$F:1d",
    factor_alias: "MmOuter|Th:MmThreshold|$F:1d",
    factor_family_alias: "MmOuter",
    identity: {family_alias: "MmOuter", params: {Th: nestedLeaf}},
    params: [{alias: "Th", value: nestedLeaf}],
  };
  const nestedViewContext = {
    ...context,
    content: new Element(), toolbar: new Element(),
  };
  await window.FTFactorDetails.factorDetail(nestedViewContext, {
    factors: [nestedOuter],
    families: [{
      family_ref: "family:mm-outer", factor_family_alias: "MmOuter",
      description: "嵌套外层因子",
      math_expr: String.raw`\textcolor{red}{Th}_t`,
      parameter_definitions: [{alias: "Th", type: "FactorParam", value: nestedLeaf}],
    }, {
      family_ref: "family:mm-threshold", factor_family_alias: "MmThreshold",
      description: "嵌套阈值因子",
      math_expr: String.raw`\textcolor{red}{N}`,
      parameter_definitions: [{alias: "N", type: "WindowParam", default_value: "20d"}],
    }],
  }, nestedOuterRef);
  const nestedViewTree = walk(nestedViewContext.content).find(item => (
    item.className?.includes("factor-detail-parameter-tree-nested")
  ));
  assert.ok(nestedViewTree, "view mode must render the nested factor table");
  const nestedViewTable = walk(nestedViewTree).find(item => (
    item.headers?.[0] === "参数"
  ));
  assert.ok(nestedViewTable);
  assert.strictEqual(nestedViewTable.values[0][1].children[0].textContent, "WindowParam");
  assert.ok(rendered.some(item => /MmThreshold/.test(item.expression)));

  const historicalFactorRef = "factor:sha256:historical-factor";
  const historicalCommit = "c".repeat(40);
  const historicalContext = {
    ...context,
    content: new Element(),
    toolbar: new Element(),
    api: async path => {
      assert.match(path, /factor-sources\/custom\/MmRateOfChg\/versions/);
      return {
        success: true,
        commit: historicalCommit,
        source_code: "class MmRateOfChg(FactorFamily):\n    pass\n",
        math_expr: "P_t-P_{t-1}",
        // These are family defaults/definitions, not the registered factor's
        // concrete parameter values.
        params: [{alias: "N", default_value: "5d"}],
      };
    },
  };
  await window.FTFactorDetails.factorDetail(
    historicalContext,
    {
      ...data,
      factors: [{
        ...data.factors[0],
        factor_ref: historicalFactorRef,
        factor_git_commit: historicalCommit,
        factor_params: [{
          alias: "N", value: "20d", type: "WindowParam",
          input_help: "填写窗口长度，例如 20d。",
        }],
        params: [{
          alias: "N", value: "20d", type: "WindowParam",
          input_help: "填写窗口长度，例如 20d。",
        }],
      }],
    },
    historicalFactorRef,
  );
  const historicalParameterTable = walk(historicalContext.content).find(
    item => item.headers?.[0] === "参数",
  );
  assert.ok(historicalParameterTable);
  const historicalParameter = historicalParameterTable.values.find(row => row[0] === "N");
  assert.strictEqual(historicalParameter[1].children[0].textContent, "WindowParam");
  assert.strictEqual(historicalParameter[2], "20d");

  const currentFamilyContext = {
    ...context,
    content: new Element(),
    toolbar: new Element(),
    api: async path => {
      assert.match(path, /family-sources\/custom\/MmRateOfChg\/versions\/current/);
      return {
        success: true,
        source_code: "class MmRateOfChg(FactorFamily):\n    pass\n",
        math_expr: "P_t-P_{t-1}",
        family_formula_fingerprint: "c".repeat(64),
        params: [{alias: "N", default_value: "10d"}],
      };
    },
  };
  await window.FTFactorDetails.familyDetail(
    currentFamilyContext,
    {
      ...data,
      families: [{
        ...data.families[0],
        source_code: "",
        family_formula_fingerprint: "c".repeat(64),
      }],
    },
    "factor-family:sha256:momentum",
  );
  const currentSource = walk(currentFamilyContext.content).find(item => (
    item.className === "factor-detail-source"
  ));
  assert.match(currentSource.children[1].children[0].textContent, /MmRateOfChg/);

  const familyContext = {...context, api: async path => {
    assert.match(path, /family-sources\/custom\/MmRateOfChg\/versions/);
    if (path.includes(`/${"b".repeat(64)}`)) {
      return {
        success: true,
        family_formula_fingerprint: "b".repeat(64),
        source_code: "class MmRateOfChg(FactorFamily):\n    pass\n",
        source_hash: "historical-hash",
        math_expr: "P_t-P_{t-1}",
        params: [{alias: "N", value: "10d"}],
      };
    }
    return {
      success: true,
      available: true,
      current_fingerprint: "a".repeat(64),
      versions: [{
        family_formula_fingerprint: "b".repeat(64), subject: "旧版本",
      }],
    };
  }};
  await window.FTFactorDetails.familyDetail(
    familyContext, data, "factor-family:sha256:momentum",
  );
  assert.strictEqual(
    walk(familyContext.content).find(item => (
      item.className === "factor-source-version-history"
    )).className,
    "factor-source-version-history",
  );
  const history = walk(familyContext.content).find(item => (
    item.className === "factor-source-version-history"
  ));
  assert.ok(history.children[0]);
  const historyPicker = walk(history).find(item => item.pickerOptions);
  await historyPicker.pickerOptions.onChange(["b".repeat(64)]);
  await new Promise(resolve => setTimeout(resolve, 0));
  const historicalSource = walk(familyContext.content).find(item => (
    item.className === "factor-detail-source"
  ));
  assert.match(
    historicalSource.children[1].children[0].textContent,
    /MmRateOfChg/,
  );
  assert.strictEqual(rendered.at(-1).expression, "P_t-P_{t-1}");

  await window.FTFactorDetails.setDetail(context, data, setRef, async () => ({}));
  const memberMount = walk(content).find(item => item.className === "factor-set-members");
  const table = memberMount.children[0];
  assert.strictEqual(table.values[0][0], alias);
  assert.ok(table._row);
  table._row.listeners.click();
  assert.strictEqual(
    navigated.at(-1), `/factors/factor/${encodeURIComponent(factorRef)}`,
  );

  const temporarySet = {
    target_ref: "factor-candidates:temporary",
    title_zh: "因子候选（1）",
    temporary: true,
    source_factors: [{target_ref: factorRef, label: alias}],
    source_factor_sets: [{target_ref: setRef, label: "动量集合"}],
    related_references: [{target_ref: factorRef, label: alias}],
  };
  context.testObjectTemporary = true;
  context.testObjectInitialValue = temporarySet;
  await window.FTFactorDetails.setDetail(
    context, {sets: [temporarySet], factors: []}, temporarySet.target_ref,
    async () => ({}),
  );
  const detailRows = walk(content).find(item => (
    item.values?.some(row => row[0] === "来源因子")
  )).values;
  const sourceFactorRow = detailRows.find(row => row[0] === "来源因子");
  const sourceSetRow = detailRows.find(row => row[0] === "来源因子集合");
  assert.ok(sourceFactorRow);
  assert.ok(sourceSetRow);
  const factorLink = sourceFactorRow[1].children[0];
  const setLink = sourceSetRow[1].children[0];
  factorLink.listeners.click({preventDefault() {}});
  assert.strictEqual(
    navigated.at(-1), `/factors/factor/${encodeURIComponent(factorRef)}`,
  );
  setLink.listeners.click({preventDefault() {}});
  assert.strictEqual(
    navigated.at(-1), `/factors/set/${encodeURIComponent(setRef)}`,
  );
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
