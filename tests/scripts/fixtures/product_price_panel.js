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
const loadedGroups = [];
let disposed = 0;
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
  iconButton: (_context, _symbol, label, action) => {
    const button = new Node("button");
    button.className = "icon-action-button";
    button.textContent = label;
    button.listeners.click = action;
    return button;
  },
  dialogRoot: () => {
    const dialog = new Node("dialog");
    dialog.showModal = () => {};
    return dialog;
  },
  table: (headers, rows) => {
    tables.push({headers, rows});
    return {shell: new Node("div")};
  },
};
const pickers = [];
context.FTMultiSelectFilter = {create: (_context, options) => {
  const element = new Node("section");
  element.className = options.className;
  const picker = {
    element, options, items: options.items || [], values: options.selected || [],
    setItems(items) { this.items = items; },
    setValues(values) { this.values = values; },
    setStatus() {},
    select(value) { options.onChange([value]); },
  };
  pickers.push(picker);
  return picker;
}};
context.document.body = new Node("body");
context.FTPriceChart = {
  barsOf: payload => payload.data.map(row => ({...row, timestamp: Date.parse(row.timestamp),
    openInterest: row.open_interest ?? null})),
};
context.FTStaticLoader = {loadGroups: async groups => loadedGroups.push(...groups)};
context.FTChartWorkbench = {mountPriceChart: (target, options) => {
  charts.push({target, options});
  return () => { disposed += 1; };
}};
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
  const sourcePicker = pickers.find(node => node.element.className === "product-price-source-filter");
  const adjustedPicker = pickers.find(node => node.element.className === "product-price-adjusted-filter");
  assert.ok(sourcePicker);
  assert.ok(adjustedPicker);
  assert.deepStrictEqual(Array.from(sourcePicker.items, node => node.label), [
    "自动选择", "LocalCNFuturesDAY1 · DAY1", "LocalCNFuturesMIN1 · MIN1",
  ]);
  assert.strictEqual(requests[0].freq, undefined);
  assert.strictEqual(requests[0].data_source, undefined);
  assert.strictEqual(requests[0].adjusted, false);
  const info = walk(root, node => node.className === "icon-action-button")[0];
  info.listeners.click();
  assert.strictEqual(tables.at(-1).rows.some(row => row[1] === "未复权"), true);

  sourcePicker.select("LocalCNFuturesMIN1");
  await settle();
  assert.strictEqual(requests[1].data_source, "LocalCNFuturesMIN1");
  assert.strictEqual(requests[1].freq, undefined);
  assert.strictEqual(requests[1].max_points, 600);
  assert.ok(requests[1].start_date);

  adjustedPicker.select("adjusted");
  await settle();
  assert.strictEqual(requests[2].data_source, "LocalCNFuturesMIN1");
  assert.strictEqual(requests[2].adjusted, true);
  assert.ok(loadedGroups.includes("chart-workbench-price"));
  assert.strictEqual(charts.at(-1).options.bars[0].close, 2);
  assert.strictEqual(disposed, 2);
  await charts.at(-1).options.loadRange(Date.parse("2025-01-01"),
    Date.parse("2025-01-03"), 2400);
  assert.strictEqual(requests.at(-1).max_points, 2400);
  info.listeners.click();
  assert.strictEqual(tables.at(-1).rows.some(row => row[1] === "连续合约换月平滑复权"), true);
  assert.strictEqual(tables.at(-1).rows.some(row => row[1] === "raw × adjustment_mul + adjustment_add"), true);

  const contractMount = new Node("div");
  const contractRoot = await context.FTProductPricePanel.render(context, contractMount, {
    contractUID: "DCE|F|A|2501",
    contractName: "A2501",
    source: "server",
  });
  const contractPickers = pickers.slice(2);
  assert.deepStrictEqual(
    Array.from(contractPickers[0].items, node => node.label),
    ["自动选择", "LocalCNFuturesMIN1 · MIN1"],
  );
  assert.strictEqual(
    contractPickers[1].element.hidden,
    true,
  );
  assert.strictEqual(requests.at(-1).contract_uid, "DCE|F|A|2501");
  assert.strictEqual(charts.at(-1).options.bars[0].close, 2);
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
