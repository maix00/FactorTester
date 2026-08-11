const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.window = {};
vm.runInThisContext(
  fs.readFileSync(
    "scripts/worktree_manager_web/catalog/product-tree.js",
    "utf8",
  ),
  {filename: "product-tree.js"},
);

const tree = window.FTProductTree;

assert.deepEqual(
  tree.minimalPaths([
    "Product/Futures/CNFutures",
    "Product/Futures",
    "Product/Futures/CNFutures",
  ]),
  ["Product/Futures"],
);
assert.deepEqual(
  tree.updateSelection(
    ["Product/Futures/CNFutures"],
    "Product/Futures",
    true,
  ),
  ["Product/Futures"],
);
assert.deepEqual(
  tree.updateSelection(
    ["Product/Futures"],
    "Product/Futures/CNFutures",
    true,
  ),
  ["Product/Futures"],
);
assert.deepEqual(
  tree.updateSelection(["Product/Futures"], "Product/Futures", false),
  [],
);

console.log("ok");
