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
    this.classes = new Set();
    this.style = {setProperty: (name, value) => { this[name] = value; }};
    this.classList = {
      toggle: (name, enabled) => enabled
        ? this.classes.add(name) : this.classes.delete(name),
    };
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
global.crypto = {randomUUID: (() => { let value = 0; return () => `frame-${++value}`; })()};
global.FTUI = window.FTUI = {
  empty: (title, message) => {
    const element = new Element();
    element.textContent = `${title}: ${message}`;
    return element;
  },
};

const factorRef = `factor:v2:${"a".repeat(43)}`;
const setRef = `factor-set:v2:${"b".repeat(43)}`;
const calls = {loads: [], sets: [], factors: []};
window.FTStaticLoader = {
  async loadGroups(groups) { calls.loads.push(groups); },
};
window.FTFactors = {
  async setDetail(context, ref) {
    calls.sets.push({ref, viewOnly: context.testObjectViewOnly});
    const member = context.button("因子成员", () => context.openFactor({
      schema_version: 2,
      ref: factorRef,
      alias: "Momentum|N:20d",
      owner_ref: "profile:maxa",
      identity: {
        family_ref: `factor-family:v2:${"c".repeat(43)}`,
        family_alias: "Momentum",
        family_formula_fingerprint: "d".repeat(64),
        self_formula_fingerprint: "e".repeat(64),
        params: {N: "20d"},
      },
      math_expr: "P_t - P_{t-1}",
    }));
    context.content.append(member);
  },
  async factorDetail(context, ref, mode) {
    calls.factors.push({
      ref,
      mode,
      viewOnly: context.testObjectViewOnly,
      alias: context.testObjectInitialValue?.alias || "",
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
  const close = heading.children[1];
  const overlayBody = card.children[1];
  const tree = overlayBody.children[0];
  const mount = overlayBody.children[1];
  assert.equal(calls.sets.length, 1);
  assert.equal(calls.sets[0].viewOnly, true);
  assert.equal(calls.loads.length, 1);
  assert.deepEqual(calls.loads[0], ["factor-catalog-detail"]);
  assert.equal(tree.hidden, true);

  mount.children[0].children[0].listeners.click();
  await Promise.resolve();
  await Promise.resolve();
  assert.deepEqual(calls.factors, [{
    ref: factorRef, mode: "view", viewOnly: true, alias: "Momentum|N:20d",
  }]);
  assert.deepEqual(calls.loads[1], ["factor-catalog-detail-rendering"]);
  assert.equal(tree.hidden, false);
  assert.equal(tree.children.length, 2);

  tree.children[0].children[1].listeners.click();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(calls.sets.length, 1);
  assert.equal(tree.children.length, 2, "parent navigation must preserve the child frame");
  mount.children[0].children[0].listeners.click();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(tree.children.length, 3, "parallel children must share one tree branch");
  tree.children[0].children[1].listeners.click();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(tree.children.length, 3, "returning to the parent must preserve all siblings");
  tree.children[1].children[1].listeners.click();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(tree.children[1].classes.has("active"), true,
    "preserved child frame must remain navigable");
  tree.children[1].children[2].listeners.click({
    preventDefault() {}, stopPropagation() {},
  });
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(tree.children.length, 2, "tree cancel must remove only the selected sibling");
  assert.equal(tree.children[0].classes.has("active"), true);

  close.listeners.click();
  await pending;
  assert.equal(dialog.removed, true);
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
