const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.rows = [];
  }
  append(...items) { this.children.push(...items.filter(Boolean)); }
  insertRow() {
    const row = new Element("tr");
    row.cells = [];
    row.insertCell = () => {
      const cell = new Element("td");
      row.cells.push(cell);
      return cell;
    };
    this.rows.push(row);
    this.append(row);
    return row;
  }
  createTHead() { const head = new Element("thead"); head.insertRow = this.insertRow.bind(head); this.append(head); return head; }
  createTBody() { const body = new Element("tbody"); body.insertRow = this.insertRow.bind(body); this.append(body); return body; }
}

global.document = {createElement: tagName => new Element(tagName)};
global.window = {};
const idle = [];
global.requestIdleCallback = callback => idle.push(callback);
vm.runInThisContext(fs.readFileSync(
  "scripts/worktree_manager_web/report/table-view.js", "utf8",
), {filename: "table-view.js"});

const rows = Array.from({length: 200}, (_, index) => [String(index)]);
const shell = window.FTReportTables.render({
  columns: ["value"], rows, context: {},
  renderHeader: value => new Element(`th:${value}`),
  renderCell: value => new Element(`td:${value}`),
  values: row => row,
});
const body = shell.children[0].children.find(item => item.tagName === "tbody");
assert.equal(body.rows.length, 80, "large tables render only the first chunk synchronously");
assert.equal(idle.length, 1);
idle.shift()();
assert.equal(body.rows.length, 160);
idle.shift()();
assert.equal(body.rows.length, 200);

const small = window.FTReportTables.render({
  columns: ["value"], rows: rows.slice(0, 2), context: {},
  renderHeader: value => new Element(`th:${value}`),
  renderCell: value => new Element(`td:${value}`),
  values: row => row,
});
const smallBody = small.children[0].children.find(item => item.tagName === "tbody");
assert.equal(smallBody.rows.length, 2, "small tables remain synchronous");

const staleContext = {renderGeneration: 1};
const stale = window.FTReportTables.render({
  columns: ["value"], rows, context: staleContext,
  renderHeader: value => new Element(`th:${value}`),
  renderCell: value => new Element(`td:${value}`),
  values: row => row,
});
const staleBody = stale.children[0].children.find(item => item.tagName === "tbody");
assert.equal(staleBody.rows.length, 80);
staleContext.renderGeneration = 2;
idle.shift()();
assert.equal(staleBody.rows.length, 80, "detached table chunks must stop after a chapter switch");
console.log("ok");
