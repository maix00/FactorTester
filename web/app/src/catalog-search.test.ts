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

test("factor tabs select their resource even if category metadata is present", async () => {
  const {catalogRows} = await import("./catalog-search.ts");
  const categories = ["public"];
  const families = [{family_ref:"family:v2:example"}];
  assert.deepEqual(catalogRows({factors:[], categories}, "factors", "factors"), []);
  assert.deepEqual(catalogRows({families, categories}, "factors", "families"), families);
  assert.deepEqual(catalogRows({items:[]}, "factors", "sets"), []);
  assert.throws(() => catalogRows({categories}, "factors", "factors"), /factors/);
});

import {catalogIdentity,catalogTitle,familyConfigurationKey} from "./catalog-search.ts";
test("sets use canonical target refs and server titles",()=>{
 assert.equal(catalogIdentity({target_ref:"factor-set:v1:a",alias:"display"}),"factor-set:v1:a");
 assert.equal(catalogTitle({target_ref:"factor-set:v1:a",title_zh:"Set A"}),"Set A");
});
test("same-named families keep source ownership in the configuration request",()=>{
 assert.equal(familyConfigurationKey({factor_family_alias:"Momentum",source:"public",owner_username:"alice"}),"public:Momentum");
 assert.equal(familyConfigurationKey({factor_family_alias:"Momentum",source:"custom",owner_username:"alice"}),"alice:Momentum");
 assert.equal(familyConfigurationKey({factor_family_alias:"other:Momentum",source:"custom",owner_username:"alice"}),"other:Momentum");
});
