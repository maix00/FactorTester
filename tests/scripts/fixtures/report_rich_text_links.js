const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Node {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.dataset = {};
    this.className = "";
    this.textContent = "";
    this.listeners = {};
  }

  append(...items) { this.children.push(...items.filter(Boolean)); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  click() {
    this.listeners.click?.({preventDefault() {}, stopPropagation() {}});
  }
}

class Fragment extends Node {
  constructor() { super("#fragment"); }
}

global.document = {
  createElement: tagName => new Node(tagName),
  createDocumentFragment: () => new Fragment(),
  createTextNode: value => ({tagName: "#text", textContent: String(value)}),
};
global.window = global;
global.FTIcons = {
  node: () => new Node("span"),
  reference: () => "link",
};

vm.runInThisContext(fs.readFileSync(
  "server/manager/web/report/rich-text.js",
  "utf8",
), {filename: "rich-text.js"});

const source =
  "[SgCPS|P:[[CA]]|N:[20d]](factortester://factor/factor%3Aone)";
const rendered = window.FTRichText.inline(source);
assert.equal(rendered.children.length, 1);
const link = rendered.children[0];
assert.equal(link.tagName, "A");
assert.equal(link.dataset.referenceTarget, "factortester://factor/factor%3Aone");
assert.equal(link.children[1].textContent, "SgCPS|P:[[CA]]|N:[20d]");

const embeddedReferences = [];
const embeddedLocalResources = [];
const embeddedContext = {
  nativeReference: true,
  captureScrollPosition() {},
  openReference(target, label) { embeddedReferences.push({target, label}); },
  openLocalResource(target, label) { embeddedLocalResources.push({target, label}); },
};
const embedded = document.createDocumentFragment();
window.FTRichText.appendLink(
  embedded,
  "factor [P:[[CA]]]",
  "factortester://factor/factor%3Atwo",
  embeddedContext,
);
window.FTRichText.appendLink(
  embedded,
  "paper [section [A]]",
  "https://example.test/paper#a",
  embeddedContext,
);
window.FTRichText.appendLink(
  embedded,
  "terminal output",
  "factortester-local://terminal-1",
  embeddedContext,
);
embedded.children[0].click();
embedded.children[1].click();
embedded.children[2].click();
assert.deepEqual(embeddedReferences, [
  {target: "factortester://factor/factor%3Atwo", label: "factor [P:[[CA]]]"},
  {target: "factortester://file/terminal-1", label: "terminal output"},
]);
// A web URL stays browser navigation even inside the client bridge, so it is
// never reported as a FactorTester object reference.
assert.equal(embedded.children[1].href, "https://example.test/paper#a");
assert.equal(embedded.children[1].target, "_blank");
assert.deepEqual(embeddedLocalResources, []);

const standalone = document.createDocumentFragment();
window.FTRichText.appendLink(
  standalone,
  "paper",
  "https://example.test/standalone",
  {nativeReference: false},
);
assert.equal(standalone.children[0].href, "https://example.test/standalone");
assert.equal(standalone.children[0].target, "_blank");
console.log("ok");

