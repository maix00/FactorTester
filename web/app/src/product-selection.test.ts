import assert from "node:assert/strict";
import test from "node:test";
import { ProductPathRules, readProductPaths, sourceInstallationKey } from "./product-selection.ts";
test("path selections do not enumerate unloaded products and respect segment boundaries", () => {
  const rules = new ProductPathRules(["Product/Future/A", "Historical/Unavailable"]);
  assert.deepEqual(rules.toggle("Product/Future", true), ["Historical/Unavailable", "Product/Future"]);
  assert.equal(new ProductPathRules(["Product/Future"]).state("Product/Futures/B").checked, false);
});
test("unchecking inherited product creates an exception; checking folder removes its exceptions", () => {
  const rules = new ProductPathRules(["Product/Future"]);
  const next = rules.toggle("Product/Future/A", false);
  assert.deepEqual(next, ["Product/Future", "-Product/Future/A"]);
  const exceptions = new ProductPathRules(next);
  assert.equal(exceptions.state("Product/Future").partial, true);
  assert.equal(exceptions.state("Product/Future/A").checked, false);
  assert.deepEqual(exceptions.toggle("Product/Future", true), ["Product/Future"]);
  assert.equal(exceptions.state("Product/Future/A/Child").blocked, true);
});
test("category occurrence inherits its stable rule while leaf identity remains canonical", () => {
  const rules = new ProductPathRules(["Product/C/Category/id/label-id"]);
  assert.equal(rules.state("Product/C/_products/A", ["Product/C/Category/id/label-id"]).checked, true);
  assert.deepEqual(rules.toggle("Product/C/_products/A", false, ["Product/C/Category/id/label-id"]),
    ["Product/C/Category/id/label-id", "-Product/C/_products/A"]);
});
test("single mode changes selection only on explicit action and advanced rules survive parsing", () => {
  assert.deepEqual(readProductPaths("Old/Unknown\n-Product/A\nOld/Unknown\n"), ["Old/Unknown", "-Product/A"]);
  assert.deepEqual(new ProductPathRules(["Old/Unknown"]).toggle("Product/A", true, [], false), ["Product/A"]);
});
test("same Bundle on different Managers, nodes or installations remains distinct", () => {
  const a = {owner:"platform",node_id:"a",installation_id:"first",bundle_id:"Local",bundle_version:"1",bundle_fingerprint:"sha256:x"};
  assert.notEqual(sourceInstallationKey("m", a), sourceInstallationKey("m", {...a,node_id:"b"}));
  assert.notEqual(sourceInstallationKey("m", a), sourceInstallationKey("m", {...a,installation_id:"second"}));
  assert.notEqual(sourceInstallationKey("m", a), sourceInstallationKey("other", a));
});
