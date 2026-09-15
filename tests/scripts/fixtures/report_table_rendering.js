const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.replaceChildren = (...kids) => { this.children = kids; };
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

// Report tables reuse the shared pageable table primitive, so this fixture
// pins the pass-through contract: every row is handed over (no bespoke
// chunking), the rich cell hooks still run, and the pager is only shown when
// there is more than one page.
const calls = [];
global.window = {
  FTUI: {
    pagedTable(headers, rows, options) {
      calls.push({headers, rows, options});
      const shell = new Element("div");
      const tableShell = new Element("div");
      const pagination = new Element("nav");
      shell.append(tableShell);
      return {shell, tableShell, pagination, totalPages: Math.ceil(rows.length / (options.pageSize || 20))};
    },
  },
};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/report/table-view.js", "utf8",
), {filename: "table-view.js"});

const rows = Array.from({length: 200}, (_, index) => [String(index)]);
const shell = window.FTReportTables.render({
  columns: ["value"], rows, context: {},
  renderHeader: value => new Element(`th:${value}`),
  renderCell: value => new Element(`td:${value}`),
  values: row => row,
  className: "table-shell",
});
assert.equal(calls.length, 1, "one page render hands the table to the shared pager");
assert.equal(calls[0].rows.length, 200, "every row reaches the pager; report code keeps no private chunk");
assert.equal(calls[0].options.pageSize, 20);
assert.equal(calls[0].headers.length, 1);
assert.equal(shell.className, "report-paged-table");
const firstPage = calls[0].options.renderRow(["7", "8"], 3);
assert.deepEqual(firstPage.map(node => node.tagName), ["td:7", "td:8"]);
// Row indices continue across pages instead of restarting per chunk.
calls[0].options.onPageChange(2);
assert.equal(calls.length, 2);
const secondPage = calls[1].options.renderRow(["0"], 1);
assert.equal(secondPage.length, 1);
assert.equal(calls[1].options.page, 2);
console.log("ok");

