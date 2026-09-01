const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = new Map();
    this.listeners = {};
    this.style = {};
    this.dataset = {};
    this.className = "";
    this.textContent = "";
    this.isConnected = true;
    this.open = false;
  }

  append(...children) {
    children.flat().forEach(child => {
      if (!child) return;
      child.parentNode = this;
      this.children.push(child);
    });
  }

  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index >= 0) this.children.splice(index, 1);
    child.parentNode = null;
    child.isConnected = false;
    return child;
  }

  remove() {
    this.parentNode?.removeChild(this);
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  addEventListener(name, handler) {
    this.listeners[name] = handler;
  }

  contains(node) {
    return this.children.includes(node) || this.children.some(child => child.contains?.(node));
  }

  getBoundingClientRect() {
    return {left: 24, top: 40, bottom: 58, width: 18, height: 18};
  }

  showModal() {
    this.open = true;
    this.setAttribute("open", "");
  }

  close() {
    this.open = false;
    this.removeAttribute("open");
  }

  focus() {
    this.focused = true;
  }
}

const body = new Element("body");
global.window = {
  innerWidth: 1024,
  innerHeight: 768,
  FTI18n: {t: (_key, fallback) => fallback},
  addEventListener() {},
};
global.document = {
  body,
  createElement: tagName => new Element(tagName),
  addEventListener() {},
};

for (const source of process.argv.slice(2)) {
  vm.runInThisContext(fs.readFileSync(source, "utf8"), {filename: source});
}

function click(button) {
  button.listeners.click({
    preventDefault() {},
    stopPropagation() {},
  });
}

function byClass(name) {
  return body.children.find(child => child.className.split(" ").includes(name));
}

const bubbleButton = window.FTHelp.create("这是纯文字帮助");
assert.equal(bubbleButton.tagName, "BUTTON");
assert.equal(bubbleButton.getAttribute("title"), null);
click(bubbleButton);
const bubble = byClass("ft-help-bubble");
assert.ok(bubble);
assert.equal(bubble.getAttribute("role"), "tooltip");
assert.equal(bubble.textContent, "这是纯文字帮助");
assert.ok(Number.parseFloat(bubble.style.top) < 40, "bubble should prefer the trigger's upper side");
assert.equal(bubble.style.left, "24px", "bubble should be horizontally centered on the trigger");
assert.equal(bubbleButton.getAttribute("aria-expanded"), "true");
click(bubbleButton);
assert.equal(byClass("ft-help-bubble"), undefined);
assert.equal(bubbleButton.getAttribute("aria-describedby"), null);

const content = new Element("p");
content.textContent = "这是复杂帮助";
const overlayButton = window.FTHelp.create({
  mode: "overlay",
  title: "字段说明",
  content,
  text: "字段说明正文",
});
click(overlayButton);
const overlay = byClass("ft-help-overlay");
assert.ok(overlay);
assert.equal(overlay.open, true);
assert.equal(overlayButton.getAttribute("aria-haspopup"), "dialog");
assert.equal(overlayButton.getAttribute("aria-controls"), overlay.id);
assert.equal(overlay.children[0].children[2].children[0], content);
overlay.listeners.cancel({preventDefault() {}});
assert.equal(byClass("ft-help-overlay"), undefined);

let loaderCalls = 0;
window.FTHelp.registerLoader("lazy_test", () => {
  loaderCalls += 1;
  const loaded = new Element("strong");
  loaded.textContent = "按需读取的说明";
  return loaded;
});
const lazyButton = window.FTHelp.create({
  mode: "overlay", type: "lazy_test", text: "备用说明",
});
assert.equal(loaderCalls, 0);
click(lazyButton);
assert.equal(loaderCalls, 1);
window.FTHelp.close();

if (process.argv[3]) {
  const manifest = {
    defaults: {
      factor: {
        label: "因子",
        help_text: "选择因子",
        info_overlay: {type: "factor_info"},
      },
    },
  };
  const context = {t: value => `译文:${value}`};
  const descriptor = window.FTTestFieldHelp.forField(
    manifest, ["missing", "factor"], context,
  );
  assert.equal(descriptor.mode, "overlay");
  assert.equal(descriptor.text, "译文:选择因子");
  assert.equal(window.FTTestFieldHelp.forField({}, "missing", context), "");
}

console.log("ok");
