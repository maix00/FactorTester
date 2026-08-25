const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.Node = class {};
global.document = {
  createElement(tagName) {
    return {
      tagName: tagName.toUpperCase(),
      children: [],
      listeners: {},
      attributes: {},
      append(...items) { this.children.push(...items); },
      addEventListener(name, handler) { this.listeners[name] = handler; },
      setAttribute(name, value) { this.attributes[name] = value; },
      removeAttribute(name) { delete this.attributes[name]; },
      focus() { this.focused = true; },
    };
  },
};
let highlighted = 0;
global.window = {hljs: {highlightElement() { highlighted += 1; }}};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/core/shared-ui.js", "utf8"),
  {filename: "shared-ui.js"},
);

let clicked = false;
const button = window.FTUI.actionButton("应用分类", () => {
  clicked = true;
}, {variant: "primary", help: "应用所选分类"});

assert.strictEqual(button.tagName, "BUTTON");
assert.strictEqual(button.type, "button");
assert.strictEqual(button.textContent, "应用分类");
assert.strictEqual(button.title, "应用所选分类");
assert.strictEqual(button.className, "action-button primary");
button.listeners.click();
assert.strictEqual(clicked, true);

const editor = window.FTUI.codeEditor("value = 1", {
  language: "python", required: true, placeholder: "Python source",
});
assert.strictEqual(editor.element.className, "editable-code-editor");
assert.strictEqual(editor.textarea.value, "value = 1");
assert.strictEqual(editor.textarea.required, true);
assert.strictEqual(editor.element.children[0].children[0].className, "language-python");
assert.strictEqual(highlighted, 1);
editor.textarea.value = "value = 2";
editor.textarea.listeners.input();
assert.strictEqual(editor.value(), "value = 2");
assert.strictEqual(highlighted, 2);
console.log("ok");
