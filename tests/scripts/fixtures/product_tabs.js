const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

function element() {
  return {
    children: [], className: "", hidden: false, dataset: {},
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    addEventListener() {}, setAttribute() {},
    querySelector() { return element(); },
  };
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
  fs.readFileSync("scripts/worktree_manager_web/app/tabs.js", "utf8"),
  {filename: "tabs.js"},
);

const state = {
  tabs: [
    {id: "home", path: "/", title: "主页", closable: false},
    {id: "jobs", path: "/jobs", title: "测试任务", closable: false},
    {id: "products", path: "/products", title: "产品", closable: false},
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

tabs.navigate("/jobs?scope=mine");
assert.strictEqual(state.activeTabID, "jobs");
assert.strictEqual(state.tabs.find(tab => tab.id === "jobs").path, "/jobs?scope=mine");

tabs.navigate("/settings/account");
assert.strictEqual(state.activeTabID, "settings");
assert.strictEqual(state.tabs.find(tab => tab.id === "settings").path, "/settings/account");
assert.strictEqual(state.tabs.filter(tab => !tab.closable).length, 4);
console.log("ok");
