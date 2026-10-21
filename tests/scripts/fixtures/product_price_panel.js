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
    this.classList = {
      add: value => { this.className += ` ${value}`; },
      remove: value => { this.className = this.className.split(/\s+/)
        .filter(item => item !== value).join(" "); },
      contains: value => this.className.split(/\s+/).includes(value),
    };
  }

  append(...children) {
    this.children.push(...children.filter(Boolean));
  }

  replaceChildren(...children) {
    this.children = children.filter(Boolean);
  }

  remove() {}

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
const notices = [];
let disposed = 0;
const tables = [];
const context = {
  window: {},
  document: {createElement: tagName => new Node(tagName)},
  location: {search: "?data_source=Local"},
  URLSearchParams,
  setTimeout,
  clearTimeout,
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
  actionButton: label => {
    const button = new Node("button");
    button.textContent = label;
    return button;
  },
  dialogRoot: () => {
    const dialog = new Node("dialog");
    dialog.showModal = () => {};
    dialog.close = () => { dialog.closed = true; dialog.listeners.close?.(); };
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
    select(value) { this.values = [value]; options.onChange([value]); },
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
  const handle = () => { disposed += 1; };
  handle.mergeOverview = rows => { charts.at(-1).overview = rows; };
  handle.fitContent = () => { charts.at(-1).fitted = true; };
  handle.setTimeZone = timeZone => { charts.at(-1).displayTimeZone = timeZone; };
  handle.setRangeBands = ranges => { charts.at(-1).rangeBands = ranges; };
  handle.selectRangeBand = id => { charts.at(-1).selectedBand = id; return true; };
  return handle;
}};
context.isRouteCurrent = () => true;
context.t = value => value;
context.showNotice = (message, isError) => notices.push({message, isError});
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
    timezone: "Asia/Shanghai",
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
  const timezonePicker = pickers.find(node => node.element.className === "product-price-timezone-filter");
  const intervalPicker = pickers.find(node => node.element.className === "product-price-interval-filter");
  const rangePicker = pickers.find(node => node.element.className === "product-price-range-filter");
  assert.ok(sourcePicker);
  assert.ok(adjustedPicker);
  assert.ok(timezonePicker);
  assert.ok(intervalPicker);
  assert.ok(rangePicker);
  assert.strictEqual(charts.at(-1).options.timeZone, "Asia/Shanghai");
  assert.strictEqual(walk(root, node => node.className === "product-price-controls").length, 0,
    "filters live in the shared settings dialog instead of consuming a page row");
  const settings = walk(root, node => node.textContent === "图表设置")[0];
  settings.listeners.click();
  const settingsDialog = context.document.body.children.at(-1);
  const save = walk(settingsDialog, node => node.textContent === "保存并加载")[0];
  assert.strictEqual(walk(context.document.body,
    node => node.className === "product-price-controls").length, 1);
  timezonePicker.select("utc");
  assert.strictEqual(charts.at(-1).options.timeZone, "Asia/Shanghai",
    "time zone remains unchanged until Save");
  assert.deepStrictEqual(Array.from(sourcePicker.items, node => node.label), [
    "自动选择", "LocalCNFuturesDAY1 · DAY1", "LocalCNFuturesMIN1 · MIN1",
  ]);
  assert.strictEqual(requests[0].freq, undefined);
  assert.strictEqual(requests[0].data_source, undefined);
  assert.strictEqual(requests[0].adjusted, false);
  assert.strictEqual(requests[0].chart_interval, "DAY1");
  assert.strictEqual(requests[0].chart_mode, "fixed");
  assert.strictEqual(requests[0].start_date, "2025-01-01");
  const info = walk(root, node => node.className === "icon-action-button")[0];
  info.listeners.click();
  assert.strictEqual(tables.at(-1).rows.some(row => row[1] === "未复权"), true);

  sourcePicker.select("LocalCNFuturesMIN1");
  adjustedPicker.select("adjusted");
  intervalPicker.select("HOUR1");
  rangePicker.select("all");
  assert.strictEqual(requests.length, 1,
    "draft settings must not trigger a request");
  await save.listeners.click();
  await settle();
  assert.strictEqual(requests.length, 2);
  assert.strictEqual(requests.at(-1).data_source, "LocalCNFuturesMIN1");
  assert.strictEqual(requests.at(-1).adjusted, true);
  assert.strictEqual(requests.at(-1).chart_interval, "HOUR1");
  assert.strictEqual(requests.at(-1).start_date, undefined);
  assert.strictEqual(charts.at(-1).options.timeZone, "UTC");
  assert.strictEqual(settingsDialog.closed, true);
  assert.ok(loadedGroups.includes("chart-workbench-price"));
  assert.strictEqual(charts.at(-1).options.bars[0].close, 2);
  const showAll = walk(root, node => node.textContent === "适配当前时间范围")[0];
  showAll.listeners.click();
  assert.strictEqual(charts.at(-1).fitted, true);
  assert.strictEqual(disposed, 0);
  assert.strictEqual(charts.at(-1).options.loadRange, undefined,
    "fixed-frequency chart zoom must not trigger another source request");
  info.listeners.click();
  assert.strictEqual(tables.at(-1).rows.some(row => row[1] === "连续合约换月平滑复权"), true);
  assert.strictEqual(tables.at(-1).rows.some(row => row[1] === "raw × adjustment_mul + adjustment_add"), true);

  const existingChartCount = charts.length;
  const normalApi = context.api;
  settings.listeners.click();
  const retryDialog = context.document.body.children.at(-1);
  const retrySave = walk(retryDialog, node => node.textContent === "保存并加载")[0];
  context.api = async () => { throw new Error("temporary source failure"); };
  intervalPicker.select("SOURCE");
  assert.strictEqual(charts.length, existingChartCount);
  await retrySave.listeners.click();
  await settle();
  assert.strictEqual(charts.length, existingChartCount,
    "a failed setting request must leave the previous chart visible");
  assert.strictEqual(intervalPicker.values[0], "SOURCE",
    "a failed request must retain the user's draft selection");
  assert.strictEqual(retryDialog.closed, undefined);
  assert.strictEqual(walk(retryDialog, node => node.className ===
    "product-price-settings-error")[0].textContent, "temporary source failure");
  assert.deepStrictEqual(notices.at(-1), {
    message: "temporary source failure", isError: true,
  });
  context.api = normalApi;
  intervalPicker.select("DAY1");
  await retrySave.listeners.click();
  await settle();
  assert.strictEqual(charts.length, existingChartCount + 1);
  assert.strictEqual(retryDialog.closed, true);

  const liveEntries = context.FTProductPricePanel.sourceEntries([
    {alias: "FutureLiveMIN1", freq: "MIN1", delivery_mode: "live_stream"},
  ]);
  assert.strictEqual(liveEntries[0].deliveryMode, "live_stream");

  const recentMount = new Node("div");
  const recentRoot = await context.FTProductPricePanel.render(context, recentMount, {
    product: {name: "AU.SHF"}, source: "server",
  });
  assert.strictEqual(requests.at(-1).chart_range, undefined);
  assert.strictEqual(requests.at(-1).start_date, undefined,
    "product charts initially load all daily history");
  recentRoot.setTermRanges([{uid: "contract-1", start: "2025-01-01",
    end: "2025-01-31"}]);
  recentRoot.selectTermRange({uid: "contract-1"});
  assert.strictEqual(charts.at(-1).rangeBands.length, 1);
  assert.strictEqual(charts.at(-1).selectedBand, "contract-1");
  assert.strictEqual(requests.at(-1).chart_range, undefined,
    "selecting a term-structure row must not narrow the data request");
  walk(recentRoot, node => node.textContent === "图表设置")[0].listeners.click();
  const recentRangePicker = pickers.slice(5)[4];
  recentRangePicker.select("year");
  const recentDialog = context.document.body.children.at(-1);
  await walk(recentDialog, node => node.textContent === "保存并加载")[0].listeners.click();
  assert.strictEqual(requests.at(-1).chart_range, "year");
  assert.strictEqual(requests.at(-1).start_date, undefined,
    "recent periods are resolved against the source's last bar on the server");

  context.api = async (...args) => {
    const response = await normalApi(...args);
    response.available_sources.push({alias: "FutureLiveMIN1", freq: "MIN1",
      delivery_mode: "live_stream"});
    return response;
  };
  const liveMount = new Node("div");
  const liveRoot = await context.FTProductPricePanel.render(context, liveMount, {
    product: {name: "AU.SHF"}, source: "server",
  });
  const livePickers = pickers.slice(10);
  walk(liveRoot, node => node.textContent === "图表设置")[0].listeners.click();
  livePickers[0].select("FutureLiveMIN1");
  assert.strictEqual(livePickers[3].values[0], "LIVE");
  assert.ok(livePickers[3].items.some(item => item.label === "实时"));
  const liveDialog = context.document.body.children.at(-1);
  await walk(liveDialog, node => node.textContent === "保存并加载")[0].listeners.click();
  assert.strictEqual(requests.at(-1).chart_interval, "LIVE");
  context.api = normalApi;

  const contractMount = new Node("div");
  const contractRoot = await context.FTProductPricePanel.render(context, contractMount, {
    contractUID: "DCE|F|A|2501",
    contractName: "A2501",
    source: "server",
  });
  const contractPickers = pickers.slice(15);
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
