const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class FakeElement {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.dataset = {};
    this.style = {color: ""};
    this.className = "";
    this.hidden = false;
    this.open = false;
    this.isConnected = true;
    this.textContent = "";
    this.value = "";
    this.parentNode = null;
    this.controls = [];
  }

  get firstChild() { return this.children[0] || null; }
  get childNodes() { return this.children; }
  append(...values) {
    values.forEach(value => {
      if (value?.parentNode) {
        value.parentNode.children = value.parentNode.children.filter(item => item !== value);
      }
      value.parentNode = this;
      this.children.push(value);
    });
  }
  appendChild(value) { this.append(value); return value; }
  replaceChildren(...values) {
    this.children.forEach(value => { if (value.parentNode === this) value.parentNode = null; });
    this.children = [];
    this.append(...values);
  }
  querySelector(selector) {
    if (selector === "[data-ft-rerender-on-tab-restore]") return null;
    return new FakeElement();
  }
  querySelectorAll(selector) {
    if (selector.includes("input") || selector.includes("data-ft-scroll-state")) {
      const nested = [];
      const visit = node => {
        node.children?.forEach(child => {
          if (["INPUT", "TEXTAREA", "SELECT", "DETAILS"].includes(child.tagName)
              || child.dataset?.ftScrollState !== undefined) nested.push(child);
          visit(child);
        });
      };
      visit(this);
      return nested.length ? nested : this.controls;
    }
    return [];
  }
  addEventListener() {}
  setAttribute() {}
  removeAttribute(name) { if (name === "open") this.open = false; }
  showModal() { this.open = true; }
  click() {}
}

class FakeFragment extends FakeElement {
  constructor() { super("fragment"); }
}

const opened = new FakeElement();
const caption = new FakeElement();
const content = new FakeElement("main");
const title = new FakeElement("h1");
const eyebrow = new FakeElement("small");
const toolbar = new FakeElement("header");
const notice = new FakeElement("p");
const dialogs = [];
const storage = new Map();
const durableStorage = new Map();

global.document = {
  body: {classList: {contains: () => false}},
  createElement: tag => new FakeElement(tag),
  createDocumentFragment: () => new FakeFragment(),
  querySelector: selector => ({
    "#opened-tabs": opened,
    "#opened-caption": caption,
  }[selector] || null),
  querySelectorAll: selector => selector === "dialog" ? dialogs : [],
};
global.location = {pathname: "/", search: ""};
global.history = {
  pushState(_state, _title, path) {
    const [pathname, search = ""] = String(path).split("?", 2);
    location.pathname = pathname;
    location.search = search ? `?${search}` : "";
  },
};
global.window = {
  scrollY: 17,
  requestAnimationFrame: callback => callback(),
  scrollTo: ({top}) => { window.scrollY = top; },
};
global.sessionStorage = {
  setItem: (key, value) => storage.set(key, value),
  getItem: key => storage.get(key) || null,
  removeItem: key => storage.delete(key),
};
global.localStorage = {
  setItem: (key, value) => durableStorage.set(key, value),
  getItem: key => durableStorage.get(key) || null,
  removeItem: key => durableStorage.delete(key),
};
global.FTIcons = {node: () => new FakeElement(), module: () => "shippingbox"};

vm.runInThisContext(
  fs.readFileSync("server/manager/web/app/tab-workspace.js", "utf8"),
  {filename: "tab-workspace.js"},
);
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
    {id: "products", path: "/products", title: "产品", closable: false},
  ],
  activeTabID: "home", tabSessions: new Map(), modules: [],
  pendingScrollCapture: null,
};
let renderCount = 0;
const tabs = window.FTTabs.create({
  state, embeddedPresentation: false, t: value => value,
  renderRoute() {
    renderCount += 1;
    content.replaceChildren(new FakeElement("section"));
  },
  content, title, eyebrow, toolbar, notice,
  modulePath: value => value.path,
  isPinnedPath: path => ["/", "/products"].includes(String(path).split("?", 1)[0]),
  titleForPath: () => "详情", tabIcon: () => "shippingbox",
});
const workspace = window.FTTabWorkspace.create({
  storage: localStorage, managerKey: "manager", principalKey: "account:alice",
});
tabs.setWorkspace(workspace);

const input = new FakeElement("input");
input.value = "draft value";
input.name = "factor_alias";
content.controls = [input];
content.append(input);
title.textContent = "原始页面";
const dialog = new FakeElement("dialog");
dialog.dataset.ftTabID = "home";
dialog.open = true;
dialogs.push(dialog);

tabs.navigate("/products/product/A.DCE");
assert.strictEqual(renderCount, 1);

assert.strictEqual(dialog.hidden, true);
assert.strictEqual(dialog.open, false);
assert.notStrictEqual(state.activeTabID, "home");

tabs.navigate("/");
assert.strictEqual(state.activeTabID, "home");
assert.strictEqual(content.firstChild, input);
assert.strictEqual(input.value, "draft value");
assert.strictEqual(title.textContent, "原始页面");
assert.strictEqual(dialog.hidden, false);
assert.strictEqual(dialog.open, true);
assert.strictEqual(window.scrollY, 17);
assert.strictEqual(renderCount, 1);

// A language change invalidates the cached home DOM.  Returning to home must
// render it again instead of restoring labels from the previous locale.
tabs.navigate("/products/product/LANGUAGE.DCE");
tabs.discardView("home");
const renderCountBeforeHomeRefresh = renderCount;
tabs.navigate("/");
assert.strictEqual(renderCount, renderCountBeforeHomeRefresh + 1);

// A fourth inactive view causes the oldest inactive view to be coldified. Its
// DOM is released, while the route is re-rendered and control state is restored
// when the tab is selected again.
const first = state.activeTabID;
tabs.navigate("/products/product/B.DCE");
tabs.navigate("/products/product/C.DCE");
tabs.navigate("/products/product/D.DCE");
const coldSession = state.tabSessions.get(first);
assert(coldSession.view?.coldKey);
assert.strictEqual(coldSession.view.content, undefined);
const persistedActiveTabID = state.activeTabID;

// Session changes invalidate the fixed home entry as well as opened tabs;
// home is intentionally not stored in state.tabs in the real shell.
state.activeTabID = "home";
tabs.discardViews();
assert.strictEqual(state.tabSessions.get("home").view, null);

// A browser refresh reconstructs the complete tab registry and active tab,
// while DOM/network state remains cold and is rendered on demand.
const restoredState = {
  tabs: [], activeTabID: "home", tabSessions: new Map(),
  modules: [
    {id: "home", path: "/", title: "主页", pinned: true},
    {id: "products", path: "/products", title: "产品", pinned: true},
  ],
};
const restoredTabs = window.FTTabs.create({
  state: restoredState, embeddedPresentation: false, t: value => value,
  renderRoute() {}, content, title, eyebrow, toolbar, notice,
  modulePath: value => value.path,
  isPinnedPath: path => ["/", "/products"].includes(String(path).split("?", 1)[0]),
  titleForPath: () => "详情", tabIcon: () => "shippingbox",
});
restoredTabs.setWorkspace(workspace);
restoredTabs.initializeTabs(workspace.restore());
assert(restoredState.tabs.some(tab => tab.path === "/products/product/D.DCE"));
assert.strictEqual(restoredState.activeTabID, persistedActiveTabID);

// Restoring an explicit detail URL reuses its stable native tab ID, and a
// closed tab is removed from both the registry and durable session payload.
const beforeExplicit = restoredState.tabs.length;
restoredTabs.navigate("/products/product/D.DCE");
assert.strictEqual(restoredState.tabs.length, beforeExplicit);
const closedTabID = restoredState.activeTabID;
restoredTabs.closeTab(closedTabID);
assert(!workspace.restore().tabs.some(tab => tab.id === closedTabID));
assert.strictEqual(workspace.restoreSession(closedTabID), null);

// Cold restoration identifies controls by a stable semantic key rather than
// their DOM index. Lazy rendering may insert a new control before the saved
// field between capture and restore.
tabs.navigate("/products/product/KEYED-A.DCE");
const keyedTabID = state.activeTabID;
const keyed = new FakeElement("input");
keyed.name = "factor_alias";
keyed.value = "persist me";
content.replaceChildren(keyed);
content.controls = [keyed];
tabs.navigate("/products/product/KEYED-B.DCE");
state.tabSessions.get(keyedTabID).view.lastUsedAt = 1;
tabs.navigate("/products/product/KEYED-C.DCE");
tabs.navigate("/products/product/KEYED-D.DCE");
const keyedSession = state.tabSessions.get(keyedTabID);
assert(keyedSession.view?.coldKey);
const inserted = new FakeElement("input");
inserted.name = "lazy_control";
const rerendered = new FakeElement("input");
rerendered.name = "factor_alias";
tabs.activateTab(keyedTabID);
content.replaceChildren(inserted, rerendered);
content.controls = [inserted, rerendered];
tabs.markActiveViewReady();
assert.strictEqual(inserted.value, "");
assert.strictEqual(rerendered.value, "persist me");
console.log("ok");
