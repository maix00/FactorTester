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
  }

  append(...items) { this.children.push(...items.filter(Boolean)); }
  addEventListener() {}
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
  "scripts/worktree_manager_web/report/rich-text.js",
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
console.log("ok");
