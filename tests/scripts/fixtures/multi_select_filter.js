const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.listeners = {};
    this.className = ""; this.value = ""; this.checked = false;
    this.disabled = false; this.hidden = false; this.dataset = {};
    this.classList = {
      add: (...names) => { this.className = `${this.className} ${names.join(" ")}`.trim(); },
    };
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this[name] = String(value); }
}

function descendants(root) {
  return [root, ...root.children.flatMap(descendants)];
}

global.window = {};
global.document = {createElement: tag => new Element(tag)};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: process.argv[2],
});

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
filter.setValues(["day", "none"]);
assert.deepEqual(filter.values, ["none"]);
assert.equal(filter.summary.children[0].textContent, "已选 1 个");
const exclusiveRow = filter.optionList.children.find(item => (
  item.className.includes("is-exclusive")
));
assert.ok(exclusiveRow.children.some(item => (
  item.className === "ft-multi-select-exclusive-badge"
)));

const multi = window.FTMultiSelectFilter.create({t: value => value}, {
  items: [{value: "a", label: "A"}, {value: "b", label: "B"}],
  selected: ["a"],
  multi: false,
  compact: true,
});
assert.deepEqual(multi.values, ["a"]);
assert.equal(multi.summary.children[0].textContent, "A");
const bInput = multi.optionList.children[1].children[0];
bInput.checked = true;
bInput.listeners.change();
assert.deepEqual(multi.values, ["b"]);
assert.equal(multi.summary.children[0].textContent, "B");
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

(async () => {
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
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
