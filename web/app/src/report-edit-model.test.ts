import assert from "node:assert/strict";
import test from "node:test";
import { insertParagraph, moveReportComponent, removeReportComponents } from "./report-edit-model.ts";

const chapter = {chapter_id:"c",components:[
  {component_id:"c",kind:"chapter",parent_id:null},
  {component_id:"a",kind:"section",parent_id:"c"},
  {component_id:"a1",kind:"paragraph",parent_id:"a"},
  {component_id:"b",kind:"paragraph",parent_id:"c"},
  {component_id:"d",kind:"paragraph",parent_id:"c"},
]};

test("paragraph insertion uses the chapter root and last sibling", () => {
  assert.deepEqual(insertParagraph(chapter,"new","Title","Body"), {op:"insert_component",chapter_id:"c",parent_id:"c",after_component_id:"d",component:{component_id:"new",kind:"paragraph",title:"Title",body:"Body"}});
  assert.equal(insertParagraph({chapter_id:"c",components:[]},"new","","Body"),null);
  assert.equal(insertParagraph(chapter,"new",""," "),null);
});
test("movement respects sibling order even when a sibling has children", () => {
  assert.equal(moveReportComponent(chapter,"a","up"),null);
  assert.deepEqual(moveReportComponent(chapter,"b","up"), {op:"move_component",chapter_id:"c",component_id:"b",parent_id:"c",after_component_id:"c"});
  assert.deepEqual(moveReportComponent(chapter,"a","down"), {op:"move_component",chapter_id:"c",component_id:"a",parent_id:"c",after_component_id:"b"});
  assert.equal(moveReportComponent(chapter,"a1","down"),null);
});
test("batch deletion emits one operation per selected subtree", () => {
  assert.deepEqual(removeReportComponents(chapter,["a","a1","d"]),[
    {op:"remove_component",chapter_id:"c",component_id:"a",include_children:true},
    {op:"remove_component",chapter_id:"c",component_id:"d",include_children:true},
  ]);
});
