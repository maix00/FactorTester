const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Node {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.dataset = {};
    this.style = {removeProperty: key => { delete this.style[key]; }};
    this.listeners = {};
  }
  append(...items) { this.children.push(...items.filter(Boolean)); }
  replaceChildren(...items) { this.children = []; this.append(...items); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  querySelectorAll() { return []; }
  setAttribute() {}
}

const document = {
  createElement: tagName => new Node(tagName),
  createDocumentFragment: () => new Node("fragment"),
};
const observers = [];
const calls = {blocks: 0};

global.document = document;
global.window = {};
global.IntersectionObserver = class {
  constructor(callback, options) {
    this.callback = callback;
    this.options = options;
    this.targets = new Set();
    observers.push(this);
  }
  observe(node) { this.targets.add(node); }
  unobserve(node) { this.targets.delete(node); }
  disconnect() { this.disconnected = true; this.targets.clear(); }
  trigger(node, isIntersecting) { this.callback([{target: node, isIntersecting}]); }
};
global.FTRichText = {
  blocks() { calls.blocks += 1; return new Node("p"); },
  inline() { return new Node("span"); },
  appendLink() {},
};
global.FTIcons = {
  node() { return new Node("svg"); },
  section() { return "section"; },
};
global.katex = {render() {}};

const source = fs.readFileSync(
  "scripts/worktree_manager_web/report/component-view.js", "utf8",
);
vm.runInThisContext(source, {filename: "component-view.js"});

const context = {lazyObservers: new Set(), lazyRootMargin: "600px 0px"};
const wrapper = window.FTReportComponents.componentView(
  {kind: "paragraph", title: "deferred", body: "render me later"}, [], context,
);
assert.equal(calls.blocks, 0, "body parser must not run during initial mount");
assert.equal(observers.length, 1, "one observer should be registered");
const body = wrapper.children.find(item => item.className.includes("component-body-lazy"));
assert.equal(body.dataset.lazyState, "pending");
observers[0].trigger(body, false);
assert.equal(calls.blocks, 0, "non-visible content must remain deferred");
observers[0].trigger(body, true);
assert.equal(calls.blocks, 1, "visible content should render once");
assert.equal(body.dataset.lazyState, "ready");
observers[0].trigger(body, true);
assert.equal(calls.blocks, 1, "a rendered body must not render twice");

const section = window.FTReportComponents.componentView(
  {kind: "section", title: "deferred children"},
  [{component: {kind: "paragraph", title: "child", body: "child body"}, children: []}],
  context,
);
assert.equal(observers.length, 1, "all deferred report content should share one observer");
const childrenHost = section.children[0].children.find(
  item => String(item.className || "").includes("component-children-lazy"),
);
assert.equal(childrenHost.dataset.lazyState, "pending");
observers[0].trigger(childrenHost, false);
assert.equal(observers.length, 1, "non-visible structural children remain unmounted");
observers[0].trigger(childrenHost, true);
assert.equal(childrenHost.dataset.lazyState, "ready");
assert.equal(observers.length, 1, "the child leaf reuses the report observer");
const childBody = childrenHost.children[0].children[0].children.find(
  item => String(item.className || "").includes("component-body-lazy"),
);
observers[0].trigger(childBody, true);
assert.equal(calls.blocks, 2, "the child body renders after its own intersection");
console.log("ok");
