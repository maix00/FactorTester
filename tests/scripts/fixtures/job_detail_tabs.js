const assert = require("node:assert/strict");
const fs = require("node:fs");

class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.listeners = {};
    this.attributes = {};
    this.className = "";
    this.hidden = false;
    this.tabIndex = 0;
    this.classList = {
      toggle: (name, active) => {
        const names = new Set(this.className.split(/\s+/).filter(Boolean));
        if (active) names.add(name); else names.delete(name);
        this.className = [...names].join(" ");
      },
      contains: name => this.className.split(/\s+/).includes(name),
    };
  }
  append(...children) { this.children.push(...children); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  dispatchEvent(event) { this.listeners[event.type]?.(event); }
  click() { this.listeners.click?.(); }
}

const stored = new Map([["job:one", "results"]]);
global.window = globalThis;
global.document = {createElement: tagName => new Element(tagName)};
global.sessionStorage = {
  getItem: key => stored.get(key) || null,
  setItem: (key, value) => stored.set(key, value),
};
global.CustomEvent = class CustomEvent {
  constructor(type, options) { this.type = type; this.detail = options.detail; }
};

eval(fs.readFileSync(process.argv[2], "utf8"));
const view = FTJobDetailTabs.create({t: value => value}, "job:one");
assert.equal(view.current(), "results");
assert.equal(view.panels.results.hidden, false);
assert.equal(view.panels.overview.hidden, true);
assert.equal(view.root.children.length, 6);

let selected = "";
view.root.addEventListener("job-detail-tab-change", event => {
  selected = event.detail.id;
});
view.select("artifacts", true);
assert.equal(selected, "artifacts");
assert.equal(view.panels.artifacts.hidden, false);
assert.equal(view.panels.results.hidden, true);
assert.equal(stored.get("job:one"), "artifacts");
console.log("ok");
