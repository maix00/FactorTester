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
      if (typeof node === "string") {
        this.children.push(node);
        return;
      }
      if (node.parentNode) {
        node.parentNode.children = node.parentNode.children.filter(child => child !== node);
      }
      node.parentNode = this;
      this.children.push(node);
    });
  }
  replaceChildren(...nodes) {
    this.children.forEach(node => {
      if (typeof node !== "string") node.parentNode = null;
    });
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
  return [root, ...root.children.filter(child => typeof child !== "string").flatMap(descendants)];
}

global.window = {
  innerWidth: 1024, innerHeight: 768, listeners: {},
  FTUI: {
    iconButton(_context, _symbol, label, handler) {
      const button = new Element("button");
      button.className = "icon-action-button ft-multi-select-option-remove";
      button.textContent = label;
      button.addEventListener("click", handler);
      return button;
    },
  },
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
// Rows now live inside menu sections; locate by the row input value.
function optionRows(picker) {
  return descendants(picker.optionList).filter(item => (
    String(item.className || "").includes("ft-multi-select-option")
    && item.children[0]?.tagName === "input"
  ));
}
function inputOf(picker, value) {
  const row = optionRows(picker).find(item => item.children[0].value === String(value));
  return row ? row.children[0] : null;
}
const noneRow = optionRows(filter).find(item => (
  String(item.className).includes("is-exclusive")
));
assert.ok(noneRow, "exclusive candidate renders in the menu");
assert.ok(descendants(noneRow).some(item => (
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
assert.equal(descendants(multi.element).some(item => (
  item.className === "ft-multi-select-selection-note"
)), false, "single choice must not render a redundant selected note");
assert.equal(descendants(multi.element).some(item => (
  item.className === "ft-multi-select-selection-preview"
)), false, "compact single choice must not render a redundant selected preview");
assert.ok(descendants(multi.optionList).some(item => (
  String(item.className).includes("ft-help-icon")
)), "choice descriptions should use the shared help icon");

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
  await inputOf(multi, "b").listeners.click({preventDefault() {}});
  assert.deepEqual(multi.values, ["b"]);
  assert.equal(multi.dropdown.open, false,
    "single-select commits immediately and closes the dropdown");
  await inputOf(multi, "b").listeners.click({preventDefault() {}});
  assert.deepEqual(multi.values, []);
  assert.equal(multi.hasSelection, false);
  assert.deepEqual(clearableChanges.at(-1), []);
  assert.equal(multi.summary.children[0].textContent, "未筛选");

  const legacySingleChanges = [];
  const legacySingle = window.FTMultiSelectFilter.create({t: value => value}, {
    items: [{value: "a", label: "A"}, {value: "b", label: "B"}],
    selected: ["a"], multi: false,
    onApply: values => legacySingleChanges.push(values),
  });
  const legacyB = inputOf(legacySingle, "b");
  legacyB.checked = true;
  await legacyB.listeners.change();
  assert.deepEqual(legacySingleChanges, [["b"]],
    "single-select also commits legacy onApply callbacks immediately");
  assert.equal(descendants(legacySingle.element).some(item => (
    item.className === "primary ft-multi-select-apply"
  )), false, "no save action is rendered at all");

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
  assert.equal(redrawSingle.menu.parentNode, redrawSingle.dropdown,
    "menu stays in-flow inside the dropdown");
  const sourceInput = inputOf(redrawSingle, "source");
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
  assert.ok(descendants(modal).includes(modalSingle.menu),
    "in-flow menu stays inside the open modal dialog");

  // Multi: pick, then outside-close commits (no apply button).
  const multiChanges = [];
  const multiSave = window.FTMultiSelectFilter.create({t: value => value}, {
    items: [{value: "a", label: "A"}, {value: "b", label: "B"}, {value: "c", label: "C"}],
    selected: ["a"], multi: true,
    onChange: values => multiChanges.push(values),
  });
  assert.equal(descendants(multiSave.element).some(item => (
    item.className === "primary ft-multi-select-apply"
  )), false, "multi-select must not render a save action");
  await inputOf(multiSave, "c").listeners.click({preventDefault() {}});
  assert.deepEqual(multiSave.values, ["a", "c"], "picks accumulate until commit");
  assert.equal(multiChanges.length, 0, "multi does not commit on each pick");
  multiSave.dropdown.open = false;
  await multiSave.dropdown.listeners.toggle();
  assert.deepEqual(multiChanges.at(-1), ["a", "c"], "outside close commits multi");

  const exclusiveToggle = window.FTMultiSelectFilter.create({t: value => value}, {
    items: [
      {value: "normal", label: "普通"},
      {value: "exclusive", label: "排他", exclusive: true},
    ],
    selected: ["normal"],
  });
  await inputOf(exclusiveToggle, "exclusive").listeners.click({preventDefault() {}});
  assert.deepEqual(exclusiveToggle.values, ["exclusive"],
    "selecting an exclusive item clears normal selections");
  await inputOf(exclusiveToggle, "exclusive").listeners.click({preventDefault() {}});
  assert.deepEqual(exclusiveToggle.values, [],
    "clicking a selected exclusive item clears it");

  // Caller-declared hand-typed exclusive entry (manual exclusive).
  const manualChanges = [];
  const withManual = window.FTMultiSelectFilter.create({t: value => value}, {
    items: [{value: "a", label: "A"}],
    selected: [], multi: true,
    exclusiveManual: {placeholder: "输入排他项…"},
    onChange: values => manualChanges.push(values),
  });
  const manualInput = descendants(withManual.optionList).find(item => (
    String(item.className).includes("ft-multi-select-manual-exclusive")
  ))?.children[0];
  assert.ok(manualInput, "declared manual exclusive entry renders");
  manualInput.value = "自定义";
  await manualInput.listeners.keydown({key: "Enter", preventDefault() {}});
  assert.deepEqual(withManual.values, ["自定义"], "manual exclusive becomes the pick");
  assert.deepEqual(manualChanges.length, 0, "multi manual pick waits for commit");
  withManual.dropdown.open = false;
  await withManual.dropdown.listeners.toggle();
  assert.deepEqual(manualChanges.at(-1), ["自定义"]);

  // On-the-fly ("+") candidates are session-only: cancelling the pick and
  // closing the menu drops them from the pool.
  const tmpChanges = [];
  const tmp = window.FTMultiSelectFilter.create({t: value => value}, {
    items: [{value: "a", label: "A"}],
    selected: [], multi: true,
    onChange: values => tmpChanges.push(values),
    onAddCandidate: (_ctx, {add}) => {
      add({value: "tmp1", label: "临时候选", temporary: true});
    },
  });
  const addToggle = descendants(tmp.element).find(item => (
    String(item.className || "").includes("ft-multi-select-add-toggle")
  ));
  assert.ok(addToggle, "+ entry rendered for onAddCandidate");
  addToggle.listeners.click({preventDefault() {}, stopPropagation() {}});
  assert.ok(optionRows(tmp).some(item => String(item.children[1]?.textContent) === "临时候选"),
    "on-the-fly candidate joins the pool");
  const tmpRow = optionRows(tmp).find(item => item.children[1]?.textContent === "临时候选");
  tmpRow.children[0].listeners.click({preventDefault() {}});
  assert.deepEqual(tmp.values, ["tmp1"], "temporary candidate is selectable");
  // Cancel: unpick it, then closing drops it.
  const tmpRow2 = optionRows(tmp).find(item => item.children[1]?.textContent === "临时候选");
  tmpRow2.children[0].listeners.click({preventDefault() {}});
  assert.deepEqual(tmp.values, [], "temporary candidate can be deselected");
  tmp.dropdown.open = false;
  await tmp.dropdown.listeners.toggle();
  assert.equal(optionRows(tmp).some(item => item.children[1]?.textContent === "临时候选"), true,
    "deselected on-the-fly candidate is kept on close (lifecycle is by the delete icon)");

  // Delete entry (icon) removes the on-the-fly candidate and notifies caller.
  let removedCandidate = null;
  const tmpDel = window.FTMultiSelectFilter.create({t: value => value}, {
    items: [{value: "a", label: "A"}], selected: [], multi: true,
    onChange: () => {},
    onAddCandidate: (_ctx, {add}) => { add({value: "t2", label: "消除", temporary: true}); },
    onTemporaryCandidateRemoved: item => { removedCandidate = item; },
  });
  const addBtn2 = descendants(tmpDel.element).find(item => (
    String(item.className || "").includes("ft-multi-select-add-toggle")
  ));
  addBtn2.listeners.click({preventDefault() {}, stopPropagation() {}});
  const delIcon = descendants(tmpDel.element).find(item => (
    String(item.className || "").includes("ft-multi-select-option-remove")
  ));
  assert.ok(delIcon, "on-the-fly row shows a delete icon");
  delIcon.listeners.click({preventDefault() {}});
  assert.equal(optionRows(tmpDel).some(item => item.children[1]?.textContent === "消除"), false,
    "delete removes the on-the-fly candidate");
  assert.equal(removedCandidate?.value, "t2", "caller notified of the removal");

  console.log("ok");
})();
