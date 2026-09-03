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

  showPopover() {
    this._popoverShown = true;
    this.setAttribute("popover-open", "");
  }

  hidePopover() {
    this._popoverShown = false;
    this.removeAttribute("popover-open");
  }

  closest(selector) {
    let node = this;
    const wanted = String(selector).split(",")[0].trim().replace(/^\[role=/, "").replace(/"$/, "").replace(/^dialog$/, "dialog");
    while (node) {
      if (node.tagName && node.tagName.toUpperCase() === wanted.toUpperCase()) return node;
      node = node.parentNode;
    }
    return null;
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

// Nested mode: a help icon inside an open overlay opens a stacked layer
// instead of replacing the parent overlay.
const childButton = window.FTHelp.create({
  mode: "overlay",
  title: "嵌套因子身份",
  content: new Element("p"),
});
const parentContent = new Element("div");
parentContent.append(childButton);
const parentButton = window.FTHelp.create({
  mode: "overlay",
  title: "外层说明",
  content: parentContent,
});
const overlayCount = () => {
  const collect = node => [
    ...(node.className?.split?.(" ").includes("ft-help-overlay") ? [node] : []),
    ...(node.children || []).flatMap(collect),
  ];
  return collect(body).length;
};
click(parentButton);
assert.equal(overlayCount(), 1);
click(childButton);
assert.equal(overlayCount(), 2, "child overlay must stack above the parent");
assert.equal(
  childButton.getAttribute("aria-expanded"), "true",
);
assert.equal(
  parentButton.getAttribute("aria-expanded"), "true",
  "parent trigger must stay expanded while the nested overlay is open",
);
click(childButton);
assert.equal(overlayCount(), 1, "toggling the child closes only the child");
assert.equal(parentButton.getAttribute("aria-expanded"), "true");
// A trigger outside every open popup replaces the whole stack.
const outsideButton = window.FTHelp.create("外部帮助");
click(outsideButton);
assert.equal(overlayCount(), 0);
assert.equal(parentButton.getAttribute("aria-expanded"), "false");
assert.ok(byClass("ft-help-bubble"));
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

// A help bubble triggered inside a portaled dropdown menu (or any container)
// must paint above the dropdown's expanded menu.  The menu is raised with the
// Popover API into the browser top layer, so the bubble must join the top
// layer too — z-index alone cannot cover a top-layer element.
const insideMenu = new Element("div");
insideMenu.className = "ft-multi-select-menu is-portaled";
const dropdownHelp = window.FTHelp.create("选项行说明");
insideMenu.append(dropdownHelp);
body.append(insideMenu);
click(dropdownHelp);
const raisedBubble = body.children.find(child => (
  child.className.split(" ").includes("ft-help-bubble")
));
assert.ok(raisedBubble, "bubble must open for a trigger inside the dropdown menu");
assert.equal(
  raisedBubble.getAttribute("popover"), "manual",
  "bubble must be raised with the Popover API to paint above the portaled menu",
);
assert.equal(raisedBubble._popoverShown, true);
assert.ok(Number.parseFloat(raisedBubble.style.top) < 40, "bubble stays above the trigger");
// Closing removes it from the top layer again.
click(dropdownHelp);
assert.equal(insideMenu.children.find(child => (
  child.className.split(" ").includes("ft-help-bubble")
)), undefined);

// When the help trigger lives inside a dialog (e.g. an open factor/object
// overlay), the bubble must attach to that dialog — the dialog is its own
// stacking context and makes the rest of the document inert, so a body child
// could not paint above it nor receive input.
const hostDialog = new Element("dialog");
body.append(hostDialog);
const inDialogButton = window.FTHelp.create("对话框内帮助");
hostDialog.append(inDialogButton);
click(inDialogButton);
const hostedBubble = hostDialog.children.find(child => (
  child.className.split(" ").includes("ft-help-bubble")
));
assert.ok(hostedBubble, "bubble must open for a trigger inside a dialog");
assert.equal(hostedBubble.parentNode, hostDialog, "bubble attaches to the nearest dialog");
assert.equal(hostedBubble.getAttribute("popover"), "manual");
click(inDialogButton);
assert.equal(hostDialog.children.find(child => (
  child.className.split(" ").includes("ft-help-bubble")
)), undefined);

// Overlay-mode help (the "?" may open a full overlay dialog, not just a
// bubble) must follow the same hosting rule: attach to the nearest dialog so
// it stacks above both the triggering dialog and any open dropdown menu.
const overlayInDialog = window.FTHelp.create({
  mode: "overlay",
  title: "选项行覆盖层",
  content: new Element("p"),
});
hostDialog.append(overlayInDialog);
click(overlayInDialog);
const hostedOverlay = hostDialog.children.find(child => (
  child.className.split(" ").includes("ft-help-overlay")
));
assert.ok(hostedOverlay, "overlay must open for a trigger inside a dialog");
assert.equal(hostedOverlay.parentNode, hostDialog, "overlay attaches to the nearest dialog");
assert.equal(hostedOverlay.open, true, "overlay dialog is shown modally (top layer)");
window.FTHelp.close();
assert.equal(hostDialog.children.find(child => (
  child.className.split(" ").includes("ft-help-overlay")
)), undefined);

console.log("ok");
