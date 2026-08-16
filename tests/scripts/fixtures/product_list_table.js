const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.window = {};
vm.runInThisContext(
  fs.readFileSync(
    "server/manager/web/catalog/product-list-table.js",
    "utf8",
  ),
  {filename: "product-list-table.js"},
);

const table = window.FTProductListTable;
assert.deepEqual(table.paginationModel(0, 1, 20), {
  page: 1, limit: 20, total: 0, totalPages: 1,
  hasPrevious: false, hasNext: false,
});
assert.deepEqual(table.paginationModel(41, 2, 20), {
  page: 2, limit: 20, total: 41, totalPages: 3,
  hasPrevious: true, hasNext: true,
});
assert.deepEqual(table.paginationModel(41, 99, 20), {
  page: 3, limit: 20, total: 41, totalPages: 3,
  hasPrevious: true, hasNext: false,
});

console.log("ok");
