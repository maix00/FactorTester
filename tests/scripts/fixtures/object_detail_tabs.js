const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class Element {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.listeners = {};
    this.dataset = {};
    this.attributes = {};
    this.className = "";
    this.classList = {
      toggle: (name, enabled) => {
        const values = new Set(this.className.split(/\s+/).filter(Boolean));
        if (enabled) values.add(name); else values.delete(name);
        this.className = [...values].join(" ");
      },
    };
  }
  append(...values) { this.children.push(...values); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  dispatchEvent(event) { this.lastEvent = event; }
  focus() { this.focused = true; }
  querySelector(selector) {
    const className = selector.startsWith(".") ? selector.slice(1) : "";
    const all = [];
    const visit = value => {
      if (!value || typeof value !== "object") return;
      all.push(value); (value.children || []).forEach(visit);
    };
    visit(this);
    return all.find(value => value.className?.split(/\s+/).includes(className)) || null;
  }
}

global.document = {createElement: tag => new Element(tag)};
global.CustomEvent = class CustomEvent { constructor(type, options) {
  this.type = type; this.detail = options?.detail;
} };
global.window = {};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/shared/object-detail-tabs.js", "utf8"),
  {filename: "object-detail-tabs.js"},
);

const context = {t: value => value};
const definitions = window.FTObjectDetailTabs.definitions("family", {
  overview: {save_mode: "auto"},
  source: {save_mode: "auto"},
  members: {hidden: true},
});
assert.deepStrictEqual(
  definitions.map(item => item.key),
  ["overview", "source", "parameters", "identity", "jobs"],
);

const createFactorDefinitions = window.FTObjectDetailTabs.definitions("factor", {
  overview: {hidden: true},
  jobs: {hidden: true},
});
assert.deepStrictEqual(
  createFactorDefinitions.map(item => item.key),
  ["parameters", "identity"],
  "factor instances compose their frozen family and values in the parameters tab",
);

const panels = Object.fromEntries(definitions.map(item => [
  item.key, Object.assign(new Element(), {textContent: item.key}),
]));
const tabs = window.FTObjectDetailTabs.create(context, {
  objectKind: "family", mode: "edit", tabs: definitions, panels,
});
assert.strictEqual(tabs.current(), "overview");
assert.strictEqual(tabs.buttons.overview.attributes["aria-selected"], "true");
assert.strictEqual(tabs.panels.source.hidden, true);
assert.match(
  tabs.buttons.overview.children[0].children[1].textContent,
  /自动保存/,
);
assert.match(
  tabs.buttons.source.children[0].children[1].textContent,
  /自动保存/,
);
assert.match(
  tabs.buttons.parameters.children[0].children[1].textContent,
  /只读/,
);

tabs.buttons.source.listeners.click();
assert.strictEqual(tabs.current(), "source");
assert.strictEqual(tabs.panels.source.hidden, false);
tabs.setDirty("source", true);
assert.match(
  tabs.buttons.source.children[0].children[1].textContent,
  /未保存/,
);

tabs.buttons.source.listeners.keydown({key: "ArrowRight", preventDefault() {}});
assert.strictEqual(tabs.current(), "parameters");
assert.strictEqual(tabs.buttons.parameters.focused, true);
console.log("ok");
