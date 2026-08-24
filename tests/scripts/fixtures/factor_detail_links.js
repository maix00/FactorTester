const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class Element {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.listeners = {};
    this.dataset = {};
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
}

global.Node = Element;
global.document = {createElement: tagName => new Element(tagName)};
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
global.FTUI = window.FTUI = {
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
const encodedPath = Buffer.from("custom_factors/MmRateOfChg.py").toString("base64url");
const encodedAlias = Buffer.from(alias).toString("base64url");
const factorRef = `factor:v1:profile-maxa:${encodedPath}:${encodedAlias}:${
  "a".repeat(40)
}:${"b".repeat(40)}`;
const setRef = `factor-set:v1:profile-maxa:${
  Buffer.from(".factortester/factor-sets/one.json").toString("base64url")
}:${Buffer.from("one").toString("base64url")}:${"a".repeat(40)}:${"c".repeat(40)}`;

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
    factor_ref: "factor:sha256:server-projection",
    factor_alias: alias,
    factor_family_name: "MmRateOfChg",
    factor_family_alias: "MmRateOfChg",
    math_expr: "\\frac{P_t-P_{t-N}}{P_{t-N}}",
    description: "端点变化率",
    owner_alias: "MaxA",
  }],
  sets: [{target_ref: setRef, visibility: "server"}],
};

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

  await window.FTFactorDetails.setDetail(context, data, setRef, async () => ({}));
  const memberMount = content.children[0].children.at(-1);
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
  const detailRows = content.children[0].children[0].values;
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
