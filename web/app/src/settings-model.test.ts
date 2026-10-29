import test from "node:test";
import assert from "node:assert/strict";
import { SETTINGS_SECTIONS, visibleSettingsSections } from "./settings-model.ts";
test("ordinary settings exclude protected administration without hiding personal controls", () => {
  const ids=visibleSettingsSections({manager:false,superAdmin:false}).map(item=>item.id);
  for(const id of ["federation","controlDatabase","manager","mihomo"]) assert.equal(ids.includes(id as never),false);
  for(const id of ["account","devices","quota","profiles","language"]) assert.equal(ids.includes(id as never),true);
});
test("Manager capability does not imply super administrator operations", () => {
  const ids=visibleSettingsSections({manager:true,superAdmin:false}).map(item=>item.id);
  assert.equal(ids.includes("manager"),true);assert.equal(ids.includes("controlDatabase"),false);
  assert.deepEqual(visibleSettingsSections({manager:true,superAdmin:true}),SETTINGS_SECTIONS);
});
test("permission administration is not duplicated in personal settings", () => {
  const ids=visibleSettingsSections({manager:true,superAdmin:true}).map(item=>item.id);
  assert.equal(ids.includes("permissions" as never),false);
});
