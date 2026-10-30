import test from "node:test";
import assert from "node:assert/strict";
import { SETTINGS_SECTIONS, visibleSettingsSections } from "./settings-model.ts";
test("ordinary settings exclude protected administration without hiding personal controls", () => {
  const ids=visibleSettingsSections({manager:false,superAdmin:false}).map(item=>item.id);
  for(const id of ["controlDatabase","manager","mihomo"]) assert.equal(ids.includes(id as never),false);
  for(const id of ["account","devices","quota","profiles","language"]) assert.equal(ids.includes(id as never),true);
  assert.equal(ids.includes("docs" as never), false);
});
test("administrator operations live under the separate admin feature entry", () => {
  const ids=visibleSettingsSections({manager:true,superAdmin:true}).map(item=>item.id);
  for(const id of ["controlDatabase","manager","mihomo"]) assert.equal(ids.includes(id as never),false);
  assert.deepEqual(ids,SETTINGS_SECTIONS.filter(item=>!["controlDatabase","manager","mihomo"].includes(item.id)).map(item=>item.id));
  assert.equal(SETTINGS_SECTIONS.some(item=>(item.id as string) === "federation"), false);
});
test("permission administration is not duplicated in personal settings", () => {
  const ids=visibleSettingsSections({manager:true,superAdmin:true}).map(item=>item.id);
  assert.equal(ids.includes("permissions" as never),false);
});
