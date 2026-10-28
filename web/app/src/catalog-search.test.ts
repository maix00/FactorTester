import test from "node:test";
import assert from "node:assert/strict";
import { catalogSearchMatches } from "./catalog-search.ts";

test("product directory searches both identifier and displayed description", () => {
  const displayed = ["AG.SHF", "—", "—"];
  const product = ["白银", "SHFE"];
  assert.equal(catalogSearchMatches("白银", displayed, product), true);
  assert.equal(catalogSearchMatches("ag.shf", displayed, product), true);
  assert.equal(catalogSearchMatches("shfe", displayed, product), true);
  assert.equal(catalogSearchMatches("黄金", displayed, product), false);
  assert.equal(catalogSearchMatches("  ", displayed, product), true);
});
