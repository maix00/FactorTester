const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.Node = class {};
global.document = {
  createElement(tagName) {
    return {
      tagName: tagName.toUpperCase(),
      listeners: {},
      addEventListener(name, handler) { this.listeners[name] = handler; },
    };
  },
};
global.window = {};
vm.runInThisContext(
  fs.readFileSync("scripts/worktree_manager_web/core/shared-ui.js", "utf8"),
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
console.log("ok");
