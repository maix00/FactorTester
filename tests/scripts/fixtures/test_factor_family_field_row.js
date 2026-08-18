const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};

class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.className = "";
    this.textContent = "";
    this.attributes = {};
  }
  append(...children) { this.children.push(...children); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
}

global.document = {createElement: tagName => new Element(tagName)};
global.FTTestFactorCatalog = {
  familyEntries: () => [{
    key: "public:family:roc", title: "MmRateOfChg", description: "变动率",
    sourceKind: "public", ownerRef: "public",
  }],
};
global.FTTestChoicePicker = {
  create: () => ({element: new Element("picker")} ),
};
global.FTTestFieldHelp = {forField: () => "因子家族选择说明"};
global.FTUI = {empty: () => new Element("empty")};

for (const path of process.argv.slice(2)) {
  vm.runInThisContext(fs.readFileSync(path, "utf8"), {filename: path});
  if (window.FTTestFieldRow) global.FTTestFieldRow = window.FTTestFieldRow;
  if (window.FTTestFactorEditor) global.FTTestFactorEditor = window.FTTestFactorEditor;
}

const row = window.FTTestFactorEditor.familyChooser(
  {t: value => value},
  {manifest: {}, factorCatalog: {}},
  () => {},
);
assert.ok(row.className.includes("test-setting-row"));
assert.ok(row.className.includes("test-field-row"));
assert.ok(row.className.includes("test-factor-family-row"));
assert.equal(row.children.length, 2);
assert.equal(row.children[0].children[0].children[0].textContent, "因子家族");
assert.equal(row.children[1].children[0].tagName, "picker");
console.log("ok");
