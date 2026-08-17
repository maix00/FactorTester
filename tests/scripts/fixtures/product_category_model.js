const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.window = {};
vm.runInThisContext(
  fs.readFileSync(
    "server/manager/web/catalog/product-category-model.js",
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
  {id: "cnfutures_day_night", title_zh: "中国期货日夜盘", composable: true,
    product_paths: ["Product/Futures/CNFutures"]},
  {id: "cnfutures_sector", title_zh: "中国期货行业", composable: true,
    product_paths: ["Product/Futures/CNFutures"]},
  {id: "exchange", title_zh: "交易所", composable: true},
];
const dayNightSector = model.multiply(definitions, [
  "cnfutures_sector", "cnfutures_day_night",
]);
assert.deepEqual(dayNightSector, {
  alias: "中国期货日夜盘×中国期货行业",
  title_zh: "中国期货日夜盘×中国期货行业",
  dimensions: ["cnfutures_day_night", "cnfutures_sector"],
  parent_category_ids: ["cnfutures_sector", "cnfutures_day_night"],
  composable: false,
  is_composite: true,
});
assert.throws(
  () => model.multiply(definitions, ["cnfutures_day_night"]),
  /选择两个/,
);
assert.throws(
  () => model.multiply([...definitions, {
    id: "alice:category_saved",
    ...dayNightSector,
  }], [
    "alice:category_saved", "cnfutures_sector",
  ]),
  /没有增加新的分类维度/,
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
assert.deepEqual(
  model.sourceIDsForPaths(["Product/Futures"], definitions),
  [],
);
assert.deepEqual(
  model.sourceIDsForPaths(["Product/Futures/CNFutures/_products/SI.GFE"], definitions),
  ["cnfutures_day_night", "cnfutures_sector"],
);
console.log("ok");
