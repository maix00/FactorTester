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

function findDescendant(root, predicate) {
  if (predicate(root)) return root;
  for (const child of root.children || []) {
    const match = findDescendant(child, predicate);
    if (match) return match;
  }
  return null;
}

const document = {
  createElement: tagName => new Node(tagName),
  createDocumentFragment: () => new Node("fragment"),
};
const observers = [];
const calls = {blocks: 0};

global.document = document;
global.window = {scrollY: 100, innerHeight: 600};
document.scrollingElement = {scrollHeight: 800};
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
  "server/manager/web/report/component-view.js", "utf8",
);
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/report/lazy-runtime.js", "utf8",
), {filename: "lazy-runtime.js"});
vm.runInThisContext(source, {filename: "component-view.js"});

const context = {lazyObservers: new Set(), lazyRootMargin: "600px 0px"};
const wrapper = window.FTReportComponents.componentView(
  {kind: "paragraph", title: "deferred", body: "render me later"}, [], context,
);
const titledDetails = wrapper.children.find(item => item.tagName === "DETAILS");
assert.ok(titledDetails, "a titled content component must be a disclosure");
assert.equal(titledDetails.open, true, "ordinary titled content is open by default");
assert.equal(calls.blocks, 0, "body parser must not run during initial mount");
assert.equal(observers.length, 1, "one observer should be registered");
const body = titledDetails.children.find(
  item => String(item.className || "").includes("component-body-lazy"),
);
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

const disclosureChanges = [];
const restoredSection = window.FTReportComponents.componentView(
  {component_id: "section:remembered", kind: "section", title: "remember me"},
  [],
  {
    lazyObservers: new Set(),
    disclosureState: {"section:remembered": false},
    setDisclosureState: (key, open) => disclosureChanges.push([key, open]),
  },
);
const restoredDetails = restoredSection.children[0];
assert.equal(restoredDetails.dataset.ftStateKey, "report-component:section:remembered");
assert.equal(restoredDetails.open, false, "saved disclosure state overrides the default");
restoredDetails.open = true;
restoredDetails.listeners.toggle();
assert.deepEqual(disclosureChanges, [["section:remembered", true]]);
const childrenHost = section.children[0].children.find(
  item => String(item.className || "").includes("component-children-lazy"),
);
assert.equal(childrenHost.dataset.lazyState, "pending");
observers[0].trigger(childrenHost, false);
assert.equal(observers.length, 1, "non-visible structural children remain unmounted");
observers[0].trigger(childrenHost, true);
assert.equal(childrenHost.dataset.lazyState, "ready");
assert.equal(observers.length, 1, "the child leaf reuses the report observer");
const nestedBridge = childrenHost.children.find(
  item => String(item.className || "").includes("section-bridge"),
);
assert.ok(nestedBridge, "lazy structural children retain their section bridge");
assert.match(
  String(nestedBridge.children[0]?.className || ""), /depth-1/,
  "nested report sections retain their structural depth",
);
const childBody = findDescendant(
  childrenHost,
  item => String(item.className || "").includes("component-body-lazy"),
);
observers[0].trigger(childBody, true);
assert.equal(calls.blocks, 2, "the child body renders after its own intersection");

const staleContext = {
  lazyObservers: new Set(),
  lazyRootMargin: "600px 0px",
  renderGeneration: 1,
};
const staleWrapper = window.FTReportComponents.componentView(
  {kind: "paragraph", title: "stale", body: "must not render"}, [], staleContext,
);
const staleBody = findDescendant(
  staleWrapper,
  item => String(item.className || "").includes("component-body-lazy"),
);
staleContext.renderGeneration = 2;
const staleObserver = observers[observers.length - 1];
staleObserver.trigger(staleBody, true);
assert.equal(calls.blocks, 2, "detached lazy bodies must stop after a chapter switch");

let deep = {component: {kind: "paragraph", body: "deep"}, children: []};
for (let index = 0; index < 5000; index += 1) {
  deep = {component: {kind: "section", title: `depth-${index}`}, children: [deep]};
}
assert.doesNotThrow(
  () => window.FTReportComponents.componentView(deep.component, deep.children, context),
  "placeholder estimation must not recurse through an unmounted deep tree",
);

const scrollCalls = [];
window.requestAnimationFrame = callback => callback();
window.scrollTo = value => scrollCalls.push(value);
window.FTReportComponents.scheduleDisclosureAnchor(
  {getBoundingClientRect: () => ({top: 132})},
  100,
);
assert.deepEqual(scrollCalls, [{top: 132, behavior: "auto"}]);

scrollCalls.length = 0;
window.scrollY = 780;
window.FTReportComponents.scheduleDisclosureAnchor(
  {getBoundingClientRect: () => ({top: 100})},
  100,
);
assert.deepEqual(
  scrollCalls,
  [{top: 200, behavior: "auto"}],
  "a collapsed bottom section must clamp the viewport to the new document bottom",
);

const resetContext = {lazyObservers: new Set(), lazyRootMargin: "600px 0px"};
const resetWrapper = window.FTReportComponents.componentView(
  {kind: "paragraph", title: "reset", body: "must stop"}, [], resetContext,
);
const resetBody = findDescendant(
  resetWrapper,
  item => String(item.className || "").includes("component-body-lazy"),
);
const resetObserver = observers.at(-1);
window.FTReportLazyRuntime.reset(resetContext);
assert.equal(resetObserver.disconnected, true, "chapter cleanup must disconnect observer");
resetObserver.trigger(resetBody, true);
assert.equal(calls.blocks, 2, "detached observer must not mount a reset body");
console.log("ok");

// Legacy and special siblings share the same depth and structural layout.
for (const kind of ['section', 'subsection', 'special']) {
 const peer = window.FTReportComponents.componentView(
   {kind, title:'同级小节', display_kind:kind==='special'?'external_review':''}, [],
   {t:x=>x}, 4, true);
 assert.match(peer.className, /depth-4/);
 assert.match(peer.className, /bridge-entry/);
 if(kind==='subsection') assert.match(peer.className, / section /);
}
