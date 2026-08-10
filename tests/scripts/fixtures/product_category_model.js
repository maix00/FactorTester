const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.window = {};
vm.runInThisContext(
  fs.readFileSync(
    "scripts/worktree_manager_web/catalog/product-category-model.js",
    "utf8",
  ),
  {filename: "product-category-model.js"},
);

const model = window.FTProductCategoryModel;
const sources = [
  {id: "Empty", catalog_product_count: 0},
  {id: "ServerDAY1", catalog_product_count: 12},
  {id: "ServerMIN1", availability: {product_count: 8}},
];
assert.deepEqual(model.availableSourceIDs(sources), ["ServerDAY1", "ServerMIN1"]);

const definitions = [
  {id: "day_night", title_zh: "日夜盘", composable: true},
  {id: "sector", title_zh: "行业", composable: true},
  {id: "exchange", title_zh: "交易所", composable: true},
];
const dayNightSector = model.multiply(definitions, ["sector", "day_night"]);
assert.deepEqual(dayNightSector, {
  id: "day_night_x_sector",
  alias: "日夜盘×行业",
  title_zh: "日夜盘×行业",
  dimensions: ["day_night", "sector"],
  composable: false,
  is_composite: true,
});
assert.deepEqual(
  model.multiply([...definitions, dayNightSector], [dayNightSector.id, "exchange"]),
  {
    id: "day_night_x_sector_x_exchange",
    alias: "日夜盘×行业×交易所",
    title_zh: "日夜盘×行业×交易所",
    dimensions: ["day_night", "sector", "exchange"],
    composable: false,
    is_composite: true,
  },
);
assert.throws(
  () => model.multiply(definitions, ["day_night"]),
  /选择两个/,
);
assert.throws(
  () => model.multiply([...definitions, dayNightSector], [dayNightSector.id, "sector"]),
  /没有增加新的 Category 维度/,
);
assert.strictEqual(
  model.treeNodeInitiallyOpen({key: "Product/_products"}, 0),
  false,
);
assert.strictEqual(
  model.treeNodeInitiallyOpen({key: "Product/Futures"}, 0),
  true,
);
assert.strictEqual(
  model.treeNodeInitiallyOpen({key: "Product/Futures/CNFutures"}, 1),
  false,
);
console.log("ok");
