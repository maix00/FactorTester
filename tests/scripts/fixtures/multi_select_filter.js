const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.listeners = {};
    this.parentNode = null;
    this.className = ""; this.value = ""; this.checked = false;
    this.disabled = false; this.hidden = false; this.dataset = {}; this.style = {};
    this.classList = {
      add: (...names) => { this.className = `${this.className} ${names.join(" ")}`.trim(); },
      remove: (...names) => {
        const removed = new Set(names);
        this.className = this.className.split(/\s+/).filter(name => !removed.has(name)).join(" ");
      },
    };
  }
  get childElementCount() { return this.children.length; }
  get isConnected() {
    let current = this;
    while (current) {
      if (current === body) return true;
      current = current.parentNode;
    }
    return false;
  }
  append(...nodes) {
    nodes.forEach(node => {
      if (node.parentNode) {
        node.parentNode.children = node.parentNode.children.filter(child => child !== node);
      }
      node.parentNode = this;
      this.children.push(node);
    });
  }
  replaceChildren(...nodes) {
    this.children.forEach(node => { node.parentNode = null; });
    this.children = [];
    this.append(...nodes);
  }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this[name] = String(value); }
  removeAttribute(name) { if (name === "style") this.style = {}; else delete this[name]; }
  getBoundingClientRect() {
    return this.className.includes("ft-multi-select-menu")
      ? {left: 20, top: 44, right: 340, bottom: 244, width: 320, height: 200}
      : {left: 20, top: 10, right: 340, bottom: 40, width: 320, height: 30};
  }
  closest(selector) {
    let current = this;
    while (current) {
      if (selector === ".ft-multi-select-dropdown"
        && String(current.className).includes("ft-multi-select-dropdown")) return current;
      if (selector === "dialog[open]"
        && current.tagName === "dialog" && current.open === true) return current;
      current = current.parentNode;
    }
    return null;
  }
}

function descendants(root) {
  return [root, ...root.children.flatMap(descendants)];
}

global.window = {
  innerWidth: 1024, innerHeight: 768, listeners: {},
  addEventListener(name, callback) { this.listeners[name] = callback; },
  removeEventListener(name) { delete this.listeners[name]; },
};
const createdElements = [];
const body = new Element("body");
let mutationObserverCallback = null;
global.MutationObserver = class {
  constructor(callback) { mutationObserverCallback = callback; }
  observe() {}
};
global.document = {
  body,
  documentElement: {clientWidth: 1024, clientHeight: 768},
  listeners: {},
  createElement: tag => {
    const element = new Element(tag);
    createdElements.push(element);
    return element;
  },
  addEventListener(name, callback) { this.listeners[name] = callback; },
  dispatchEvent(event) { this.listeners[event.type]?.(event); },
  querySelectorAll(selector) {
    if (selector !== ".ft-multi-select-dropdown[open]") return [];
    return createdElements.filter(element => (
      String(element.className).includes("ft-multi-select-dropdown")
      && element.open === true
    ));
  },
};
for (const path of process.argv.slice(2)) {
  vm.runInThisContext(fs.readFileSync(path, "utf8"), {filename: path});
}

const filter = window.FTMultiSelectFilter.create({t: value => value}, {
  title: "产品分类",
  items: [
    {value: "none", label: "未绑定", exclusive: true},
    {value: "day", label: "日夜盘", description: "日盘与夜盘"},
    {value: "industry", label: "行业"},
  ],
  selected: ["day", "industry"],
});
assert.deepEqual(filter.values, ["day", "industry"]);
assert.equal(filter.summary.children[0].textContent, "已选 2 项");
filter.setValues(["day", "none"]);
assert.deepEqual(filter.values, ["none"]);
assert.equal(filter.summary.children[0].textContent, "未绑定");
const exclusiveRow = filter.optionList.children.find(item => (
  item.className.includes("is-exclusive")
));
assert.ok(exclusiveRow.children.some(item => (
  item.className === "ft-multi-select-exclusive-badge"
)));

const clearableChanges = [];
const multi = window.FTMultiSelectFilter.create({t: value => value}, {
  items: [{value: "a", label: "A"}, {value: "b", label: "B"}],
  selected: ["a"],
  multi: false,
  compact: true,
  onChange: values => { clearableChanges.push(values); },
});
assert.deepEqual(multi.values, ["a"]);
assert.equal(multi.hasSelection, true);
assert.equal(multi.summary.children[0].textContent, "A");
const bInput = multi.optionList.children[1].children[0];
assert.equal(descendants(multi.element).some(item => (
  item.className === "ft-multi-select-selection-note"
)), false, "single choice must not render a redundant selected note");
assert.equal(descendants(multi.element).some(item => (
  item.className === "ft-multi-select-selection-preview"
)), false, "compact single choice must not render a redundant selected preview");
const optionHelp = descendants(multi.optionList).find(item => (
  String(item.className).includes("ft-help-icon")
));
assert.ok(optionHelp, "choice descriptions should use the shared help icon");
assert.equal(optionHelp.textContent, "?");

const trailing = window.FTMultiSelectFilter.create({t: value => value}, {
  items: [{value: "a", label: "A"}],
  selected: [],
  compact: true,
  actionsPlacement: "trailing",
  actions: [{label: "新建因子", onClick: () => {}}],
});
const trailingRow = descendants(trailing.element).find(item => (
  item.className === "ft-multi-select-control-row"
));
assert.ok(trailingRow, "trailing actions must share a row with the picker");
assert.equal(trailingRow.children[0], trailing.dropdown);
assert.ok(String(trailingRow.children[1].className).includes(
  "ft-multi-select-trailing-actions",
));

const locked = window.FTMultiSelectFilter.create({t: value => value}, {
  items: [{value: "a", label: "A"}],
  selected: ["a"],
  multi: true,
  disabled: true,
  disabledReason: "由其他字段自动确定：执行引擎",
});
assert.ok(locked.element.className.includes("is-locked"));
assert.ok(locked.summary.className.includes("is-disabled"));
assert.equal(locked.summary.title, "由其他字段自动确定：执行引擎");
assert.ok(descendants(locked.summary).some(item => (
  item.className === "ft-multi-select-lock-indicator"
)));
locked.dropdown.open = true;
locked.summary.listeners.click({preventDefault() {}});
assert.equal(locked.dropdown.open, false);

(async () => {
  await bInput.listeners.click({preventDefault() {}});
  assert.deepEqual(multi.values, ["b"]);
  assert.equal(multi.optionList.children[0].children[1].textContent, "A",
    "selection must not reorder the option list");
  const selectedBInput = multi.optionList.children[1].children[0];
  await selectedBInput.listeners.click({preventDefault() {}});
  assert.deepEqual(multi.values, []);
  assert.equal(multi.hasSelection, false);
  assert.deepEqual(clearableChanges.at(-1), []);
  assert.equal(multi.summary.children[0].textContent, "未筛选");
  assert.equal(multi.dropdown.open, false,
    "single-select commits immediately and closes the dropdown");

  const legacySingleChanges = [];
  const legacySingle = window.FTMultiSelectFilter.create({t: value => value}, {
    items: [{value: "a", label: "A"}, {value: "b", label: "B"}],
    selected: ["a"], multi: false,
    onApply: values => legacySingleChanges.push(values),
  });
  const legacyB = legacySingle.optionList.children[1].children[0];
  legacyB.checked = true;
  await legacyB.listeners.change();
  assert.deepEqual(legacySingleChanges, [["b"]],
    "single-select also commits legacy onApply callbacks immediately");
  assert.equal(descendants(legacySingle.element).some(item => (
    item.className === "primary ft-multi-select-apply"
  )), false, "single-select must not render a save action");

  const redrawOwner = new Element("div");
  body.append(redrawOwner);
  let replacement = null;
  const redrawSingle = window.FTMultiSelectFilter.create({t: value => value}, {
    items: [{value: "family", label: "已有家族"}, {value: "source", label: "上传源码"}],
    selected: ["family"], multi: false,
    onChange: values => {
      replacement = new Element("section");
      replacement.dataset.mode = values[0];
      redrawOwner.replaceChildren(replacement);
    },
  });
  redrawOwner.append(redrawSingle.element);
  redrawSingle.dropdown.open = true;
  redrawSingle.dropdown.listeners.toggle();
  assert.equal(redrawSingle.menu.parentNode, document.body);
  const sourceInput = redrawSingle.optionList.children[1].children[0];
  sourceInput.checked = true;
  await sourceInput.listeners.change();
  assert.equal(replacement.dataset.mode, "source");
  assert.equal(redrawSingle.dropdown.open, false);
  assert.equal(redrawSingle.menu.parentNode, redrawSingle.dropdown,
    "a single-choice redraw must restore its portaled menu before replacing the field");

  const modal = new Element("dialog");
  modal.open = true;
  body.append(modal);
  const modalSingle = window.FTMultiSelectFilter.create({t: value => value}, {
    items: [{value: "family", label: "已有家族"}, {value: "source", label: "上传源码"}],
    selected: ["family"], multi: false,
  });
  modal.append(modalSingle.element);
  modalSingle.dropdown.open = true;
  modalSingle.dropdown.listeners.toggle();
  assert.equal(modalSingle.menu.parentNode, modal,
    "a modal picker menu must remain inside the interactive dialog subtree");
  modalSingle.dropdown.open = false;
  modalSingle.dropdown.listeners.toggle();
  assert.equal(modalSingle.menu.parentNode, modalSingle.dropdown);

  const multiChanges = [];
  const multiSave = window.FTMultiSelectFilter.create({t: value => value}, {
    items: [
      {value: "a", label: "A"},
      {value: "b", label: "B"},
      {value: "c", label: "C"},
    ],
    selected: ["a"],
    onChange: values => multiChanges.push(values),
  });
  const cInput = multiSave.optionList.children[2].children[0];
  cInput.checked = true;
  cInput.listeners.change();
  assert.deepEqual(multiSave.values, ["a", "c"]);
  assert.deepEqual(multiChanges, [], "multi-select changes stay draft until saved");
  const saveButton = descendants(multiSave.element).find(item => (
    item.className === "primary ft-multi-select-apply"
  ));
  assert.ok(saveButton, "multi-select must expose a save action");
  await saveButton.listeners.click();
  assert.deepEqual(multiChanges, [["a", "c"]]);
  assert.equal(multiSave.dropdown.open, false);

  const exclusiveToggle = window.FTMultiSelectFilter.create({t: value => value}, {
    items: [
      {value: "normal", label: "普通"},
      {value: "exclusive", label: "排他", exclusive: true},
    ],
    selected: ["normal"],
  });
  await exclusiveToggle.optionList.children[1].children[0].listeners.click({
    preventDefault() {},
  });
  assert.deepEqual(exclusiveToggle.values, ["exclusive"],
    "selecting an exclusive item clears normal selections");
  await exclusiveToggle.optionList.children[1].children[0].listeners.click({
    preventDefault() {},
  });
  assert.deepEqual(exclusiveToggle.values, [],
    "clicking a selected exclusive item clears it");

  multiSave.dropdown.open = true;
  multiSave.dropdown.listeners.toggle();
  assert.equal(multiSave.menu.parentNode, document.body,
    "an open menu must be portaled above clipping ancestors");
  assert.ok(multiSave.menu.className.includes("is-portaled"));
  document.dispatchEvent({type: "click", target: new Element("div")});
  multiSave.dropdown.listeners.toggle();
  assert.equal(multiSave.dropdown.open, false,
    "clicking outside a multi-select must close the dropdown");
  assert.equal(multiSave.menu.parentNode, multiSave.dropdown,
    "closing restores the menu to its owning control");

  const owner = new Element("div");
  body.append(owner);
  const orphan = window.FTMultiSelectFilter.create({t: value => value}, {
    items: [], loading: true,
  });
  owner.append(orphan.element);
  orphan.dropdown.open = true;
  orphan.dropdown.listeners.toggle();
  assert.equal(orphan.dropdown.open, false,
    "a loading picker must not open an empty portaled menu");
  const ready = window.FTMultiSelectFilter.create({t: value => value}, {
    items: [{value: "ready", label: "Ready"}],
  });
  owner.append(ready.element);
  ready.dropdown.open = true;
  ready.dropdown.listeners.toggle();
  assert.equal(ready.menu.parentNode, document.body);
  owner.replaceChildren();
  mutationObserverCallback?.();
  assert.equal(ready.dropdown.open, false,
    "removing a picker owner must close its portaled menu");
  assert.equal(ready.menu.parentNode, ready.dropdown,
    "an orphaned portaled menu must be restored outside document.body");

  const cancel = window.FTMultiSelectFilter.create({t: value => value}, {
    items: [{value: "a", label: "A"}, {value: "b", label: "B"}],
    selected: ["a"],
    onChange: values => multiChanges.push(values),
  });
  cancel.dropdown.open = true;
  const cancelB = cancel.optionList.children[1].children[0];
  cancelB.checked = true;
  cancelB.listeners.change();
  assert.deepEqual(cancel.values, ["a", "b"]);
  cancel.dropdown.open = false;
  cancel.dropdown.listeners.toggle();
  assert.deepEqual(cancel.values, ["a"], "closing without saving discards the draft");
  assert.deepEqual(multiChanges, [["a", "c"]]);

  const remoteCalls = [];
  const remote = window.FTMultiSelectFilter.create({t: value => value}, {
    items: [{value: "selected", label: "当前选中"}],
    selected: ["selected"],
    multi: false,
    loadItems: query => new Promise(resolve => remoteCalls.push({query, resolve})),
  });
  remote.dropdown.open = true;
  remote.dropdown.listeners.toggle();
  assert.deepEqual(remoteCalls.map(call => call.query), [""]);
  const wait = delay => new Promise(resolve => setTimeout(resolve, delay));
  remote.search.value = "old";
  remote.search.listeners.input();
  await wait(240);
  assert.deepEqual(remoteCalls.map(call => call.query), ["", "old"]);
  remote.search.value = "new";
  remote.search.listeners.input();
  await wait(240);
  assert.deepEqual(remoteCalls.map(call => call.query), ["", "old", "new"]);
  remoteCalls[2].resolve([{value: "new", label: "新结果"}]);
  await wait(0);
  assert.deepEqual(remote.values, ["selected"]);
  assert.equal(remote.summary.children[0].textContent, "当前选中");
  assert.equal(remote.optionList.children[0].children[1].textContent, "新结果");
  remoteCalls[1].resolve([{value: "old", label: "旧结果"}]);
  await wait(0);
  assert.ok(remote.optionList.children.some(row => (
    row.children[1]?.textContent === "新结果"
  )), "the latest remote result should remain visible");
  assert.equal(remote.optionList.children.some(row => (
    row.children[1]?.textContent === "旧结果"
  )), false, "a stale remote result must not overwrite the latest result");

  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
