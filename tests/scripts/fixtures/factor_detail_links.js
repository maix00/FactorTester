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
    this.style = {setProperty: (name, value) => { this[name] = value; }};
    this.classList = {
      toggle: (name, enabled) => {
        const values = new Set(this.className.split(/\s+/).filter(Boolean));
        if (enabled) values.add(name); else values.delete(name);
        this.className = [...values].join(" ");
      },
      add: (...names) => {
        const values = new Set(this.className.split(/\s+/).filter(Boolean));
        for (const name of names) values.add(name);
        this.className = [...values].join(" ");
      },
      remove: (...names) => {
        const values = new Set(this.className.split(/\s+/).filter(Boolean));
        for (const name of names) values.delete(name);
        this.className = [...values].join(" ");
      },
      contains: name => this.className.split(/\s+/).includes(name),
    };
  }
  append(...children) { this.children.push(...children); }
  createTHead() { const section = new Element("thead"); this.append(section); return section; }
  createTBody() { const section = new Element("tbody"); this.append(section); return section; }
  insertRow() { const row = new Element("tr"); this.append(row); return row; }
  insertCell() { const cell = new Element("td"); this.append(cell); return cell; }
  replaceChildren(...children) { this.children = children; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  focus() { this.focused = true; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  remove() {
    this.parentNode?.removeChild?.(this);
    this.parentNode = null;
  }
  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index >= 0) this.children.splice(index, 1);
    child.parentNode = null;
    return child;
  }
}

global.Node = Element;
global.document = {
  createElement: tagName => new Element(tagName),
  body: new Element("body"),
};
global.CustomEvent = class CustomEvent { constructor(type, options) {
  this.type = type; this.detail = options?.detail;
} };
global.navigator.clipboard = {async writeText(value) { navigator.copied = value; }};
global.window = {};
window.document = global.document;
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-model.js", "utf8"),
  {filename: "factor-model.js"},
);
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
vm.runInThisContext(
  fs.readFileSync("server/manager/web/core/shared-ui.js", "utf8"),
  {filename: "shared-ui.js"},
);
global.FTUI = window.FTUI = Object.assign(window.FTUI || {}, {
  helpIcon(text) {
    const item = new Element("button");
    item.helpText = text;
    item.className = "ft-help-icon";
    item.textContent = "?";
    return item;
  },
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
});
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
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-catalog-runtime.js", "utf8"),
  {filename: "factor-catalog-runtime.js"},
);
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factors.js", "utf8"),
  {filename: "factors.js"},
);
vm.runInThisContext(
  fs.readFileSync("server/manager/web/workbench/object-overlay.js", "utf8"),
  {filename: "object-overlay.js"},
);
window.FTStaticLoader = {loadGroups: async () => {}};

const alias = "MmRateOfChg|P:[CA]|N:20d|$F:1d";
const factorRef = `factor:v2:${"x".repeat(43)}`;
const setRef = `factor-set:v2:${"y".repeat(43)}`;

const navigated = [];
const apiPaths = [];
const content = new Element();
const toolbar = new Element();
const context = {
  t: value => value, content, toolbar,
  activeNav() {},
  button(label, handler) {
    const button = new Element("button");
    button.textContent = label; button.listeners.click = handler; return button;
  },
  setHeading(name, scope) { this.heading = {name, scope}; },
  updateActiveTab() {},
  navigate(path) { navigated.push(path); },
  isRouteCurrent() { return true; },
  async api(path) {
    apiPaths.push(path);
    if (path === "/api/factor-library/factor-sets") {
      return {items: [{
        target_ref: setRef, set_ref: "legacy-set", owner_username: "alice",
      }]};
    }
    assert.match(path, /factor-sets\/detail/);
    const query = new URLSearchParams(path.split("?")[1] || "");
    const offset = Number(query.get("offset") || 0);
    return {
      factor_set: {
        target_ref: setRef,
        title_zh: "动量集合",
        owner_username: "alice",
        can_edit: false,
        has_more: offset === 0,
        next_offset: 100,
        related_references: offset === 0 ? [{
          kind: "factor", label: alias, target_ref: factorRef,
        }] : [],
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
    resolved_math_expr: String.raw`\textcolor{red}{-}\operatorname{Resample}_{\textcolor{red}{20\,\mathrm{m}}}(P_t)`,
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
assert.match(nestedPreview, /\\textcolor\{blue\}\{\\mathrm\{SgChgPct\}\}_t :=/);
assert.doesNotMatch(nestedPreview, /\\mathrm\{SgChgPct\}_t &:=/);
assert.match(nestedPreview, /\\textcolor\{red\}\{\\mathrm\{CA\}\}/);
assert.match(nestedPreview, /\\textcolor\{blue\}\{\\mathrm\{SgChgPct\}\}/);
assert.match(nestedPreview, /\\textcolor\{blue\}\{\\mathrm\{SgChgPct\}\}_t :=[^]*;/);
assert.doesNotMatch(nestedPreview, /\\operatorname\{argmin\}[^]*;$/);
assert.ok(
    nestedPreview.indexOf("\\mathrm{SgChgPct}_t :=")
    < nestedPreview.indexOf("\\operatorname{argmin}"),
  "nested factor must be rendered as a preceding intermediate definition",
);

(async () => {
  const sourceView = window.FTFactorDetailShared.source(context, {
    source_code: "class MmRateOfChg(FactorFamily):\n    pass\n",
  });
  assert.strictEqual(sourceView.children[0].children[0].textContent, "Python 源码");
  assert.match(sourceView.children[1].children[0].textContent, /MmRateOfChg/);
  await sourceView.children[0].children[1].children[0].listeners.click();
  assert.match(navigator.copied, /FactorFamily/);

  await window.FTFactorDetails.factorDetail(
    context, data, factorRef, async () => {
      throw new Error("native catalog is unavailable");
    },
  );
  assert.strictEqual(context.heading.name, alias);
  assert.ok(
    rendered.some(item => item.expression === String.raw`\textcolor{red}{-}\operatorname{Resample}_{\textcolor{red}{20\,\mathrm{m}}}(P_t)`),
    "view mode must render the backend resolved_math_expr",
  );
  assert.strictEqual(rendered.at(-1).expression, "\\frac{P_t-P_{t-N}}{P_{t-N}}");
  assert.strictEqual(toolbar.children[0].textContent, "查看因子序列");
  toolbar.children[0].listeners.click();
  assert.strictEqual(
    navigated.at(-1), `/factor-series?factor_ref=${encodeURIComponent(factorRef)}`,
  );
  const parameterTable = walk(content).find(item => (
    item.className?.includes("factor-detail-parameter-editor")
  ));
  assert.ok(parameterTable);
  // Factor-instance parameter tables keep the Value column.
  assert.equal(parameterTable.children[0].children.length, 4);
  assert.ok(walk(parameterTable).some(item => item.textContent === "N"));
  assert.ok(walk(parameterTable).some(item => item.textContent === "WindowParam"));
  // Factor pages keep the 参数/值 mode toggle on the parameter-tree header
  // (a family page hides it and stays on the 参数/template rendering).
  const formulaToggles = walk(content).filter(item => (
    item.className === "factor-detail-local-formula-toggle"
  ));
  assert.deepEqual(
    formulaToggles.map(item => item.textContent),
    ["参数", "值"],
    "factor page keeps the 参数/值 toggle; family pages hide it",
  );
  const treeFormula = walk(content).find(item => (
    item.className?.includes("factor-detail-parameter-formula")
  ));
  assert.ok(treeFormula, "parameter-tree header must carry the template formula");
  const provenance = walk(content).find(item => (
    item.headers?.[0] === "RunSpec 字段"
  ));
  const fieldText = value => (
    typeof value === "string" ? value : value?.children?.[0]?.textContent
  );
  assert.ok(provenance.values.some(row => fieldText(row[0]) === "冻结因子家族"));
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
    resolved_math_expr: String.raw`\textcolor{red}{5\,\mathrm{d}}`,
    // Server-provided nested projections carry the typed family definitions;
    // the overlay must render those types instead of falling back to
    // Parameter for every row.
    parameter_definitions: [{
      alias: "N", type: "WindowParam", default_value: "5d",
    }],
  };
  const nestedOuter = {
    schema_version: 2,
    ref: nestedOuterRef,
    alias: "MmOuter|Th:MmThreshold|$F:1d",
    factor_alias: "MmOuter|Th:MmThreshold|$F:1d",
    factor_family_alias: "MmOuter",
    identity: {family_alias: "MmOuter", params: {Th: nestedLeaf}},
    params: [{alias: "Th", value: nestedLeaf}],
    resolved_math_expr: String.raw`\textcolor{blue}{\mathrm{MmThreshold}}_t`,
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
  const outerTree = walk(nestedViewContext.content).find(item => (
    item.className?.includes("factor-detail-parameter-tree")
      && !item.className?.includes("factor-detail-parameter-tree-nested")
  ));
  const nestedViewTree = walk(outerTree).find(item => (
    item.className?.includes("factor-detail-parameter-tree-nested")
  ));
  assert.ok(nestedViewTree, "view mode must render the nested factor table as a full-width row");
  assert.equal(nestedViewTree.dataset.parameterAlias, "Th");
  const nestedViewTable = walk(nestedViewTree).find(item => (
    item.className?.includes("factor-detail-parameter-editor")
  ));
  assert.ok(nestedViewTable);
  assert.ok(walk(nestedViewTable).some(item => item.textContent === "WindowParam"));
  assert.ok(
    !walk(nestedViewTree).some(item => item.headers?.[0] === "RunSpec 字段"),
    "parameter tab must not contain factor identity tables",
  );
  const outerIdentityTable = walk(nestedViewContext.content).find(item => (
    item.headers?.[0] === "RunSpec 字段"
  ));
  assert.ok(outerIdentityTable);
  assert.ok(
    !outerIdentityTable.values.some(row => row?.fullWidth === true),
    "identity tab must not inline nested factor identity rows",
  );
  const nestedParameterRow = walk(outerTree).find(item => (
    item.className?.includes("factor-detail-parameter-row")
      && item.children?.[0]?.textContent === "Th"
  ));
  assert.ok(nestedParameterRow);
  const nestedValueCell = nestedParameterRow.children[3];
  assert.ok(nestedValueCell.children);
  assert.ok(walk(nestedValueCell).some(item => (
    item.textContent === "MmThreshold|N:5d"
  )));
  const nestedValueContent = nestedValueCell.children[0];
  assert.equal(nestedValueContent.children[1], " ",
    "help icon must be separated from the alias by one space");
  const nestedIdentityIcon = walk(nestedValueCell).find(item => (
    item.className === "ft-help-icon"
  ));
  assert.equal(nestedIdentityIcon.className, "ft-help-icon");
  assert.equal(nestedIdentityIcon.textContent, "?");
  assert.ok(rendered.some(item => /MmThreshold/.test(item.expression)));

  // The nested-row "?" opens the nested factor's dedicated page in the shared
  // nested object overlay (FTObjectOverlay).  The overlay heading becomes the
  // nested factor's own page heading (its alias); the parent page heading is
  // never replaced.
  const waitFor = async predicate => {
    for (let attempt = 0; attempt < 100; attempt += 1) {
      if (predicate()) return true;
      await new Promise(resolve => setTimeout(resolve, 5));
    }
    return false;
  };
  const parentHeadingBefore = nestedViewContext.heading?.name || "";
  assert.ok(nestedIdentityIcon.listeners.click);
  nestedIdentityIcon.listeners.click({preventDefault() {}, stopPropagation() {}});
  await waitFor(() => document.body.children.some(item => (
    item.className === "ft-object-overlay-dialog"
  )));
  const overlayDialog = document.body.children.find(item => (
    item.className === "ft-object-overlay-dialog"
  ));
  assert.ok(overlayDialog, "nested viewer must open the shared object overlay");
  await waitFor(() => {
    const heading = walk(overlayDialog).find(item => (
      String(item.className || "").includes("ft-object-overlay-title")
    ));
    return heading?.textContent === "MmThreshold|N:5d";
  });
  const overlayHeading = walk(overlayDialog).find(item => (
    String(item.className || "").includes("ft-object-overlay-title")
  ));
  assert.equal(
    overlayHeading.textContent, "MmThreshold|N:5d",
    "overlay heading must be the nested factor's dedicated page heading",
  );
  assert.notEqual(
    overlayHeading.textContent, "查看内嵌因子 · Th",
    "overlay heading must not be the 查看内嵌因子 placeholder",
  );
  assert.equal(
    nestedViewContext.heading?.name || "", parentHeadingBefore,
    "parent page heading must not be replaced by the nested factor alias",
  );
  assert.ok(
    walk(overlayDialog).some(item => (
      item.className?.includes?.("factor-detail-parameter-editor")
    )),
    "overlay must embed the nested factor's dedicated page content",
  );
  const overlayTypeTexts = walk(overlayDialog)
    .filter(item => item.className === "factor-detail-parameter-type")
    .map(item => item.children?.[0]?.textContent ?? item.textContent);
  assert.ok(
    overlayTypeTexts.includes("WindowParam"),
    "overlay parameter rows must render the real parameter types, not Parameter",
  );
  assert.ok(
    !overlayTypeTexts.some(text => text === "Parameter"),
    "overlay must not fall back to Parameter for every parameter row",
  );

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
  const historicalParameterTable = walk(historicalContext.content).find(item => (
    item.className?.includes("factor-detail-parameter-editor")
  ));
  assert.ok(historicalParameterTable);
  const historicalParameter = walk(historicalParameterTable).find(item => (
    item.className?.includes("factor-detail-parameter-row")
      && item.children?.[0]?.textContent === "N"
  ));
  assert.ok(historicalParameter);
  assert.ok(walk(historicalParameter).some(item => item.textContent === "WindowParam"));
  assert.equal(historicalParameter.children[2].textContent, "20d");

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
    item.className.split(" ").includes("factor-detail-source")
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
    item.className.split(" ").includes("factor-detail-source")
  ));
  assert.match(
    historicalSource.children[1].children[0].textContent,
    /MmRateOfChg/,
  );
  assert.strictEqual(rendered.at(-1).expression, "P_t-P_{t-1}");

  const pickerFactory = window.FTMultiSelectFilter;
  window.FTMultiSelectFilter = undefined;
  let selectionGroupLoaded = false;
  window.FTStaticLoader = {loadGroups: async groups => {
    assert.deepStrictEqual(groups, ["catalog-selection-core"]);
    selectionGroupLoaded = true;
    window.FTMultiSelectFilter = pickerFactory;
  }};
  const lazyFamilyContext = {...familyContext, content: new Element()};
  await window.FTFactorDetails.familyDetail(
    lazyFamilyContext, data, "factor-family:sha256:momentum",
  );
  const lazyHistory = walk(lazyFamilyContext.content).find(item => (
    item.className === "factor-source-version-history"
  ));
  const loadPickerButton = walk(lazyHistory).find(item => (
    item.tagName === "BUTTON"
  ));
  assert.strictEqual(selectionGroupLoaded, false);
  assert.strictEqual(loadPickerButton.textContent, "选择源码版本");
  await loadPickerButton.listeners.click();
  assert.strictEqual(selectionGroupLoaded, true);
  assert.ok(walk(lazyHistory).some(item => (
    item.className === "ft-multi-select-filter"
  )));
  window.FTStaticLoader = {loadGroups: async () => {}};

  // A test-local family (created inline in a test editor, never persisted)
  // must render its carried frozen value without a catalog round-trip and
  // without a server version picker.
  const localFamily = {
    factor_family_alias: "InlineFamily",
    factor_family_name: "InlineFamily",
    math_expr: "P_t-P_{t-1}",
    source_code: "class InlineFamily(FactorFamily):\n    pass\n",
    temporary: true,
    source_origin: "test_inline",
    parameter_definitions: [{
      alias: "N", type: "WindowParam", default_value: "20d",
    }],
  };
  const localFamilyContext = {
    ...context,
    testObjectTemporary: true,
    testObjectInitialValue: localFamily,
    api: async path => {
      throw new Error(`local family view must not call the catalog: ${path}`);
    },
  };
  await window.FTFactorDetails.familyDetail(
    localFamilyContext,
    {families: [localFamily], factors: []},
    "InlineFamily",
    "view",
    {temporary: true, initialValue: localFamily},
  );
  const localSummary = walk(localFamilyContext.content).find(item => (
    item.className === "factor-family-summary"
  ));
  assert.ok(localSummary, "local family view must render its summary");
  assert.strictEqual(
    walk(localFamilyContext.content).some(item => (
      item.className === "factor-source-version-history"
    )),
    false,
    "a local family must not offer a server version history",
  );
  const localSource = walk(localFamilyContext.content).find(item => (
    item.className.split(" ").includes("factor-detail-source")
  ));
  assert.ok(localSource, "local family source tab renders the carried source");
  assert.match(localSource.children[1].children[0].textContent, /InlineFamily/);

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

  // A cold canonical detail route must use the detail projection directly.
  // Loading the full own+subordinate collection first adds an avoidable RTT.
  context.testObjectTemporary = false;
  context.testObjectInitialValue = null;
  const beforeCanonicalRequests = apiPaths.length;
  await window.FTFactors.setDetail(context, setRef, "view");
  assert.deepStrictEqual(
    apiPaths.slice(beforeCanonicalRequests).map(path => path.split("?")[0]),
    ["/api/factor-library/factor-sets/detail"],
    "cold canonical read-only details should not fetch the whole set catalog",
  );
  const memberMountForDirectRead = walk(content).find(item => (
    item.className === "factor-set-members"
  ));
  const loadMore = memberMountForDirectRead.children.find(item => (
    item.textContent === "加载更多"
  ));
  assert.ok(loadMore, "the first detail page should keep member pagination");
  await loadMore.listeners.click();
  assert.match(
    apiPaths.at(-1), /owner_username=alice/,
    "later member pages should reuse the owner returned by the detail projection",
  );

  // Older references still resolve through the catalog's canonical target.
  const beforeLegacyRequests = apiPaths.length;
  await window.FTFactors.setDetail(context, "legacy-set", "view");
  assert.deepStrictEqual(
    apiPaths.slice(beforeLegacyRequests).map(path => path.split("?")[0]),
    ["/api/factor-library/factor-sets", "/api/factor-library/factor-sets/detail"],
    "legacy references should retain catalog-assisted canonicalization",
  );
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
