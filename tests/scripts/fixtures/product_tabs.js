const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

function element() {
  const value = {
    children: [], className: "", hidden: false, dataset: {},
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    addEventListener() {}, setAttribute() {},
    querySelector() { return element(); },
  };
  const classes = new Set();
  value.classList = {
    add: name => classes.add(name),
    remove: name => classes.delete(name),
    contains: name => classes.has(name),
  };
  return value;
}

const opened = element();
const caption = element();
global.document = {
  body: {classList: {contains: () => false}},
  createElement: () => element(),
  querySelector: selector => selector === "#opened-tabs" ? opened : caption,
};
global.location = {pathname: "/", search: ""};
global.history = {
  pushState(_state, _title, path) {
    const [pathname, search = ""] = String(path).split("?", 2);
    location.pathname = pathname;
    location.search = search ? `?${search}` : "";
  },
};
global.window = {scrollY: 0};
global.FTIcons = {node: () => element(), module: () => "shippingbox"};

vm.runInThisContext(
  fs.readFileSync("server/manager/web/app/tab-view-cache.js", "utf8"),
  {filename: "tab-view-cache.js"},
);
vm.runInThisContext(
  fs.readFileSync("server/manager/web/app/tabs.js", "utf8"),
  {filename: "tabs.js"},
);

const state = {
  tabs: [
    {id: "home", path: "/", title: "主页", closable: false},
    {id: "jobs", path: "/jobs?section=types", title: "测试台", closable: false},
    {id: "products", path: "/products", title: "产品库", closable: false},
    {id: "settings", path: "/settings", title: "设置", closable: false},
  ],
  activeTabID: "home", tabSessions: new Map(), modules: [],
  pendingScrollCapture: null,
};
const tabs = window.FTTabs.create({
  state, embeddedPresentation: false, t: value => value, renderRoute() {},
  modulePath: value => value.path,
  isPinnedPath: path => ["/", "/products", "/products/sources", "/products/groups"]
    .includes(String(path).split("?", 1)[0]),
  titleForPath: () => "产品详情", tabIcon: () => "shippingbox",
});

tabs.navigate("/products/sources?source=local");
assert.strictEqual(state.tabs.length, 4);
assert.strictEqual(state.activeTabID, "products");
assert.strictEqual(
  state.tabs.find(tab => tab.id === "products").path,
  "/products/sources?source=local",
);

tabs.navigate("/products/product/A.DCE?data_source=Local");
const productTab = state.tabs.find(tab => tab.id === "product-detail:product:A.DCE");
assert(productTab);
assert.strictEqual(productTab.closable, true);

tabs.navigate("/products/product/A.DCE?source=local&data_source=LocalCNFuturesDAY1");
assert.strictEqual(
  state.tabs.filter(tab => tab.id === "product-detail:product:A.DCE").length,
  1,
);
assert.strictEqual(
  state.tabs.find(tab => tab.id === "product-detail:product:A.DCE").path,
  "/products/product/A.DCE?source=local&data_source=LocalCNFuturesDAY1",
);
tabs.navigate("/products/product/DCE%7CA%7C2501?product=A.DCE&contract=DCE%7CA%7C2501&contract_has_data=1");
assert.strictEqual(state.activeTabID, "product-detail:product:DCE|A|2501");
assert.strictEqual(
  state.tabs.some(tab => tab.id === "product-detail:contract:DCE|A|2501"),
  false,
);
assert.strictEqual(
  state.tabs.find(tab => tab.id === "product-detail:product:DCE|A|2501").path,
  "/products/product/DCE%7CA%7C2501?product=A.DCE&contract=DCE%7CA%7C2501&contract_has_data=1",
);

tabs.navigate("/jobs?scope=mine");
assert.strictEqual(state.activeTabID, "jobs");
assert.strictEqual(state.tabs.find(tab => tab.id === "jobs").path, "/jobs?scope=mine");

const jobPath = "/jobs/8141/job-one?server_id=public-1";
tabs.navigate(jobPath);
const jobTabID = "job-detail:8141:public-1:job-one";
assert.strictEqual(state.activeTabID, jobTabID);
assert.strictEqual(state.tabs.find(tab => tab.id === jobTabID).path, jobPath);
assert.strictEqual(state.tabs.find(tab => tab.id === jobTabID).closable, true);
tabs.navigate(jobPath);
assert.strictEqual(state.tabs.filter(tab => tab.id === jobTabID).length, 1);
tabs.navigate("/jobs?section=tasks");
assert.strictEqual(state.activeTabID, "jobs");

// A missing submitted-task path must not duplicate the current workbench tab.
const activeBeforeEmptyNavigation = state.activeTabID;
tabs.navigate("");
assert.strictEqual(state.activeTabID, activeBeforeEmptyNavigation);

tabs.navigate("/settings/account");
assert.strictEqual(state.activeTabID, "settings");
assert.strictEqual(state.tabs.find(tab => tab.id === "settings").path, "/settings/account");

const hash = "a".repeat(64);
tabs.navigate(`/reference?kind=run_spec&target=runspec%3Asha256%3A${hash}&label=first`);
const runSpecTabID = `reference-detail:run-spec:sha256:${hash}`;
assert.strictEqual(state.activeTabID, runSpecTabID);
assert.strictEqual(
  tabs.detailTabIDForPath(`/reference?kind=run-spec&target=run_spec%3Asha256%3A${hash}`),
  runSpecTabID,
);
tabs.navigate(`/reference?kind=run-spec&target=run-spec%3Asha256%3A${hash}&label=second`);
assert.strictEqual(state.activeTabID, runSpecTabID);
assert.strictEqual(state.tabs.filter(tab => tab.id === runSpecTabID).length, 1);
assert.match(state.tabs.find(tab => tab.id === runSpecTabID).path, /label=second$/);
assert.strictEqual(state.tabs.filter(tab => !tab.closable).length, 4);

// The research feature tab owns the report list. A concrete report gets a
// stable closable tab so its reading state cannot be shared by other reports.
tabs.navigate("/research/public-report%3A1");
const reportTabID = "research-report:public-report%3A1";
assert.strictEqual(state.activeTabID, reportTabID);
assert.strictEqual(state.tabs.find(tab => tab.id === reportTabID).closable, true);
tabs.navigate("/research/public-report%3A1?chapter=methods");
assert.strictEqual(state.tabs.filter(tab => tab.id === reportTabID).length, 1);
assert.strictEqual(
  state.tabs.find(tab => tab.id === reportTabID).path,
  "/research/public-report%3A1?chapter=methods",
);

// Closing the final user-opened tab must land on home, not on the nearest
// pinned feature tab that happens to precede it in state.tabs.
const closeState = {
  tabs: [
    {id: "home", path: "/", title: "主页", closable: false},
    {id: "products", path: "/products", title: "产品库", closable: false},
    {id: "settings", path: "/settings", title: "设置", closable: false},
  ],
  activeTabID: "home", tabSessions: new Map(), modules: [],
  pendingScrollCapture: null,
};
const closeTabs = window.FTTabs.create({
  state: closeState, embeddedPresentation: false, t: value => value,
  renderRoute() {}, modulePath: value => value.path,
  isPinnedPath: () => false, titleForPath: () => "产品详情",
  tabIcon: () => "shippingbox",
});
closeTabs.navigate("/products/product/CN.SHF");
const lastTabID = closeState.activeTabID;
closeTabs.closeTab(lastTabID);
assert.strictEqual(closeState.activeTabID, "home");
assert.strictEqual(location.pathname, "/");
assert.strictEqual(closeState.tabs.filter(tab => tab.closable).length, 0);

// With multiple detail tabs, closing one still selects the adjacent detail
// tab before the final close returns to home.
closeTabs.navigate("/products/product/A.SHF");
const firstDetailTabID = closeState.activeTabID;
closeTabs.navigate("/products/product/B.SHF");
const secondDetailTabID = closeState.activeTabID;
closeTabs.closeTab(secondDetailTabID);
assert.strictEqual(closeState.activeTabID, firstDetailTabID);
closeTabs.closeTab(firstDetailTabID);
assert.strictEqual(closeState.activeTabID, "home");

const nativeMessages = [];
window.webkit = {messageHandlers: {researchNavigation: {
  postMessage: value => nativeMessages.push(value),
}}};
const embedded = window.FTTabs.create({
  state, embeddedPresentation: true, t: value => value, renderRoute() {},
  modulePath: value => value.path,
  isPinnedPath: () => false,
  titleForPath: () => "因子序列", tabIcon: () => "function",
});
const tabCount = state.tabs.length;
embedded.navigate(
  "/factor-series?factor_ref=factor%3Av1%3Aroc&group_ref=product-group%3Anight",
);
assert.deepStrictEqual(nativeMessages, [{
  path: "/factor-series?factor_ref=factor%3Av1%3Aroc&group_ref=product-group%3Anight",
}]);
assert.strictEqual(state.tabs.length, tabCount);
console.log("ok");

// Feature utilities are lazy singletons. Closing removes only the page;
// service/VPN state is deliberately not represented by a tab lifecycle call.
closeState.modules.push({id:'mihomo', path:'/mihomo', title:'Mihomo', tab_behavior:'singleton'});
const utility = closeState.modules.at(-1);
closeTabs.openModule(utility);
closeTabs.openModule(utility);
assert.strictEqual(closeState.tabs.filter(tab => tab.id === 'mihomo').length, 1);
assert.strictEqual(closeState.tabs.find(tab => tab.id === 'mihomo').closable, true);
closeTabs.closeTab('mihomo');
assert.strictEqual(closeState.tabs.some(tab => tab.id === 'mihomo'), false);
closeTabs.openModule(utility);
assert.strictEqual(closeState.tabs.filter(tab => tab.id === 'mihomo').length, 1);

// Dedicated objects are unique per folder, while each folder keeps its own view.
closeTabs.openTab('/products/product/A.SHF');
const rootObject = closeState.activeTabID;
closeTabs.openTab('/products/product/A.SHF', {forceNew:true});
assert.equal(closeState.activeTabID, rootObject);
closeTabs.openTab('/products/product/A.SHF', {parentTabID:'research:one', parentFolder:'research'});
const folderObject = closeState.activeTabID;
assert.notEqual(folderObject, rootObject);
closeTabs.openTab('/products/product/A.SHF?mode=edit', {parentTabID:'research:one', parentFolder:'research'});
assert.equal(closeState.activeTabID, folderObject);
assert.equal(closeState.tabs.find(t=>t.id===folderObject).path, '/products/product/A.SHF?mode=edit');
assert.equal(closeState.tabs.filter(t=>t.path.startsWith('/products/product/A.SHF')).length,2);
