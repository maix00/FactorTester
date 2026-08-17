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
  table: () => ({shell: new Node("div")}),
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
  const alias = payload.data_source || "LocalCNFuturesDAY1";
  const freq = alias.endsWith("MIN1") ? "MIN1" : "DAY1";
  return {
    success: true,
    product: payload.product_name,
    data_source: alias,
    freq,
    adjusted: Boolean(payload.adjusted),
    supports_adjusted: true,
    available_sources: [
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
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
