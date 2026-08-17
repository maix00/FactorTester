const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class Node {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.listeners = {};
    this.attributes = {};
    this.className = "";
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.textContent = "";
  }

  append(...children) {
    this.children.push(...children.filter(Boolean));
  }

  replaceChildren(...children) {
    this.children = children.filter(Boolean);
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  addEventListener(name, callback) {
    this.listeners[name] = callback;
  }

  get options() {
    return this.children;
  }
}

function walk(node, predicate, matches = []) {
  if (!node) return matches;
  if (predicate(node)) matches.push(node);
  node.children?.forEach(child => walk(child, predicate, matches));
  return matches;
}

function settle() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

const requests = [];
const charts = [];
const tables = [];
const context = {
  window: {},
  document: {createElement: tagName => new Node(tagName)},
  location: {search: "?data_source=Local"},
  URLSearchParams,
  console,
};
context.window = context;
context.FTUI = {
  empty: () => new Node("div"),
  loading: () => new Node("div"),
  table: (headers, rows) => {
    tables.push({headers, rows});
    return {shell: new Node("div")};
  },
};
context.FTPriceChart = {
  render(_context, _target, payload) {
    charts.push(payload);
  },
};
context.isRouteCurrent = () => true;
context.t = value => value;
context.api = async (_url, options) => {
  const payload = JSON.parse(options.body);
  requests.push(payload);
  const contract = Boolean(payload.contract_uid);
  const alias = payload.data_source || "LocalCNFuturesDAY1";
  const freq = alias.endsWith("MIN1") ? "MIN1" : "DAY1";
  return {
    success: true,
    product: payload.product_name || payload.contract_uid,
    contract_name: contract ? "A2501" : undefined,
    data_source: alias,
    freq,
    adjusted: Boolean(payload.adjusted),
    adjustment_method: payload.adjusted ? "continuous_futures_roll" : "raw",
    adjustment_formula: payload.adjusted
      ? "raw × adjustment_mul + adjustment_add" : "",
    supports_adjusted: !contract,
    available_sources: contract
      ? [{alias: "LocalCNFuturesMIN1", freq: "MIN1"}]
      : [
        {alias: "LocalCNFuturesDAY1", freq: "DAY1"},
        {alias: "LocalCNFuturesMIN1", freq: "MIN1"},
      ],
    count: 1,
    data: [{timestamp: "2025-01-02", open: 1, high: 2, low: 1, close: 2, volume: 3}],
  };
};

vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), context);

(async () => {
  const mount = new Node("div");
  const root = await context.FTProductPricePanel.render(context, mount, {
    product: {name: "SI.GFE"},
    source: "server",
    startDate: "2025-01-01",
    endDate: "2025-01-03",
  });
  const selects = walk(root, node => node.tagName === "SELECT");
  const sourceSelect = selects.find(node => node.className === "product-price-source-select");
  const adjustedSelect = selects.find(node => node.className === "product-price-adjusted-select");
  assert.ok(sourceSelect);
  assert.ok(adjustedSelect);
  assert.strictEqual(selects.some(node => node.className.includes("frequency")), false);
  assert.deepStrictEqual(sourceSelect.options.map(node => node.textContent), [
    "自动", "LocalCNFuturesDAY1 · DAY1", "LocalCNFuturesMIN1 · MIN1",
  ]);
  assert.strictEqual(requests[0].freq, undefined);
  assert.strictEqual(requests[0].data_source, undefined);
  assert.strictEqual(requests[0].adjusted, false);
  assert.strictEqual(tables.at(-1).rows.some(row => row[1] === "未复权"), true);

  sourceSelect.value = "LocalCNFuturesMIN1";
  sourceSelect.listeners.change();
  await settle();
  assert.strictEqual(requests[1].data_source, "LocalCNFuturesMIN1");
  assert.strictEqual(requests[1].freq, undefined);

  adjustedSelect.value = "adjusted";
  adjustedSelect.listeners.change();
  await settle();
  assert.strictEqual(requests[2].data_source, "LocalCNFuturesMIN1");
  assert.strictEqual(requests[2].adjusted, true);
  assert.strictEqual(charts.at(-1).adjusted, true);
  assert.strictEqual(tables.at(-1).rows.some(row => row[1] === "连续合约换月平滑复权"), true);
  assert.strictEqual(tables.at(-1).rows.some(row => row[1] === "raw × adjustment_mul + adjustment_add"), true);

  const contractMount = new Node("div");
  const contractRoot = await context.FTProductPricePanel.render(context, contractMount, {
    contractUID: "DCE|F|A|2501",
    contractName: "A2501",
    source: "server",
  });
  const contractSelects = walk(contractRoot, node => node.tagName === "SELECT");
  assert.deepStrictEqual(
    contractSelects.find(node => node.className === "product-price-source-select")?.options
      .map(node => node.textContent),
    ["自动", "LocalCNFuturesMIN1 · MIN1"],
  );
  assert.strictEqual(
    walk(contractRoot, node => node.className.includes("product-price-adjusted"))[0].hidden,
    true,
  );
  assert.strictEqual(requests.at(-1).contract_uid, "DCE|F|A|2501");
  assert.strictEqual(charts.at(-1).product, "A2501");
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
