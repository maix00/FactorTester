const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.listeners = {};
    this.dataset = {};
    this.hidden = false;
    this.open = false;
    this.textContent = "";
  }

  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  showModal() { this.open = true; }
  close() {
    this.open = false;
    this.listeners.close?.();
  }
  remove() { this.removed = true; }
}

const body = new Element("body");
global.document = {
  body,
  createElement: tagName => new Element(tagName),
};
global.window = globalThis;
global.FTUI = window.FTUI = {
  empty: (title, message) => {
    const element = new Element();
    element.textContent = `${title}: ${message}`;
    return element;
  },
};

const factorRef = "factor:v1:profile-maxa:path:alias:commit:blob";
const setRef = "factor-set:v1:profile-maxa:path:set:commit:blob";
const calls = {loads: [], sets: [], factors: []};
window.FTStaticLoader = {
  async loadGroups(groups) { calls.loads.push(groups); },
};
window.FTFactors = {
  async setDetail(context, ref) {
    calls.sets.push({ref, viewOnly: context.testObjectViewOnly});
    const member = context.button("因子成员", () => context.openFactor({
      target_ref: factorRef,
      label: "Momentum|N:20d",
      factor_git_commit: "historical-commit",
      math_expr: "P_t - P_{t-1}",
    }));
    context.content.append(member);
  },
  async factorDetail(context, ref, mode) {
    calls.factors.push({
      ref,
      mode,
      viewOnly: context.testObjectViewOnly,
      commit: context.testObjectInitialValue?.factor_git_commit || "",
    });
  },
};
window.FTProducts = {};

vm.runInThisContext(
  fs.readFileSync("server/manager/web/workbench/test-object-editor-overlay.js", "utf8"),
  {filename: "test-object-editor-overlay.js"},
);

const context = {
  tabID: "ic-test:configuration",
  t: value => value,
  button(label, handler) {
    const button = new Element("button");
    button.textContent = label;
    button.listeners.click = handler;
    return button;
  },
};

(async () => {
  const pending = window.FTTestObjectEditorOverlay.open(context, {
    kind: "factor_set", ref: setRef, mode: "view",
  });
  await Promise.resolve();
  await Promise.resolve();

  const dialog = body.children[0];
  const card = dialog.children[0];
  const heading = card.children[0];
  const back = heading.children[0];
  const mount = card.children[1];
  assert.equal(calls.sets.length, 1);
  assert.equal(calls.sets[0].viewOnly, true);
  assert.equal(calls.loads.length, 1);
  assert.equal(back.hidden, true);

  mount.children[0].listeners.click();
  await Promise.resolve();
  await Promise.resolve();
  assert.deepEqual(calls.factors, [{
    ref: factorRef, mode: "view", viewOnly: true, commit: "historical-commit",
  }]);
  assert.equal(back.hidden, false);

  back.listeners.click();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(calls.sets.length, 2);
  assert.equal(back.hidden, true);

  heading.children[2].listeners.click();
  await pending;
  assert.equal(dialog.removed, true);
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
