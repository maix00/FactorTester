const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.dataset = {};
    this.className = "";
    this.listeners = {};
    this.classList = {add: name => { this.className += ` ${name}`; }};
  }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  click(event = {}) {
    this.listeners.click?.({
      preventDefault() {}, stopPropagation() {}, ...event,
    });
  }
  querySelectorAll() { return []; }
  scrollIntoView() {}
}

global.window = {
  FTStaticLoader: {loadGroups: async () => {}},
  FTObjectOverlay: {open: async (_context, options) => options},
};
global.document = {createElement: tag => new Element(tag)};
global.FTUI = {
  loading: message => Object.assign(new Element("div"), {textContent: message}),
  empty: (title, body) => Object.assign(new Element("div"), {title, textContent: body}),
  refreshButton: () => new Element("button"),
  table: (headers, rows) => {
    const shell = new Element("div");
    shell.className = "table-shell";
    shell.headers = headers;
    shell.rows = rows;
    return {shell, body: {rows: rows.map(() => new Element("tr"))}, rows};
  },
  actionButton: (label, onClick) => Object.assign(new Element("button"), {
    textContent: label, click: onClick,
  }),
};

vm.runInThisContext(fs.readFileSync(
  "server/manager/web/catalog/source-family-detail.js", "utf8",
), {filename: "catalog/source-family-detail.js"});

const context = {
  content: new Element("main"),
  t: value => value,
  servicePath: path => `${path}?port=8001`,
  api: async path => {
    assert.equal(path, "/api/nautilus/capabilities?port=8001");
    return {
      market_data_sources: {available: true, members: []},
      simulated_venue_config: {fields: [{path: "book_type", options: ["L1_MBP", "L2_MBP", "L3_MBO"]}]},
    };
  },
};
const descriptor = {
  id: "Local", family_id: "Local", family_name: "本地期货",
  provider_kind: "historical", server_provided: true,
  availability: {status: "ready", product_count: 1, frequency_names: ["MIN1"]},
  members: [{
    id: "LocalCNFuturesContractMIN1", label: "期货合约分钟线", frequency: "MIN1",
    dimensions: {data_kind: "ohlcv_bar", market_depth: "not_applicable"},
    product_count: 1, timezone: "Asia/Shanghai",
    nautilus_capability: {
      adapter_available: true, adapter_id: "local_contract_min1_v1",
      supported_book_types: ["L1_MBP"], instrument_scope: "physical_contract",
      sampling_mode: "bar", data_kind: "ohlcv_bar", market_depth: "not_applicable",
      delivery_mode: "historical_snapshot", timezone: "Asia/Shanghai",
      bar_time_semantics: "interval_end", raw_timestamp_unit: "ms",
      layout: "parquet_ohlcv", naming_scheme: "local_uid_v1",
      time_columns: {trade_time: "MIN1"}, data_columns: {open: "OPEN"}, reason: "",
    },
  }],
};

(async () => {
  const opened = await window.FTProductSourceFamilyDetail.openFamilyOverlay(context, descriptor);
  assert.equal(opened.kind, "data_source_family");
  assert.equal(opened.initialValue.family_id, "Local");
  await window.FTProductSourceFamilyDetail.familyOverlay(
    context, "Local", "view", {initialValue: descriptor},
  );
  const tables = [];
  const visit = node => {
    if (node?.className === "table-shell") tables.push(node);
    for (const child of node?.children || []) visit(child);
  };
  visit(context.content);
  const sourceRows = tables.flatMap(table => table.rows || []);
  assert.ok(sourceRows.some(row => row[0] === "BookType 支持" && row[1] === "L1_MBP"));
  assert.ok(sourceRows.some(row => row[0] === "Nautilus 可配置 BookType"
    && row[1] === "L1_MBP\nL2_MBP\nL3_MBO"));
  assert.ok(sourceRows.some(row => row[0] === "Bar 时间语义" && row[1] === "interval_end"));

  vm.runInThisContext(fs.readFileSync(
    "server/manager/web/catalog/source-list.js", "utf8",
  ), {filename: "catalog/source-list.js"});
  const pageContext = {
    content: new Element("main"), toolbar: new Element("div"),
    t: value => value, activeNav() {}, setHeading() {},
    showNotice: message => { throw new Error(message); },
  };
  const sourceHelpers = {
    sourceOf: () => "server", pathFor: path => path,
    catalogSwitch() {}, sourceSummary: () => new Element("div"),
    isCurrent: () => true, localCatalogAvailable: () => false,
    request: async () => ({sources: [descriptor]}),
  };
  window.FTProductSourceFamilyDetail = {
    openFamilyOverlay: async (_context, item) => (
      window.FTObjectOverlay.open(_context, {
        kind: "data_source_family", ref: item.family_id,
      })
    ),
  };
  const sharedOverlayCalls = [];
  window.FTObjectOverlay = {open: async (_context, options) => {
    sharedOverlayCalls.push(options);
    return options;
  }};
  window.FTStaticLoader = {loadGroups: async () => {}};
  window.FTProductSources.list(pageContext, sourceHelpers);
  await new Promise(resolve => setImmediate(resolve));
  let sourceTable = null;
  const findTable = node => {
    if (node?.className === "table-shell") sourceTable = node;
    for (const child of node?.children || []) findTable(child);
  };
  findTable(pageContext.content);
  assert.deepEqual(sourceTable.headers, [
    "数据源族", "数据源 / 频率", "数据类型 / 深度", "可用性", "提供服务器", "Nautilus 属性",
  ]);
  assert.equal(sourceTable.rows[0][5].textContent, "查看属性");
  sourceTable.rows[0][5].click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(sharedOverlayCalls[0].kind, "data_source_family");
  sourceTable.rows[0][4].click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(sharedOverlayCalls[1].kind, "data_source_providers");

  console.log("nautilus source overlay contract passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
