import assert from "node:assert/strict";
import test from "node:test";
import { reportJobReference, reportTree, validReportComponents } from "./report-tree.ts";

test("report tree restores hierarchy from breadth-first chapter data", () => {
  const roots = reportTree([{component_id:"c"},{component_id:"a",parent_id:"c"},{component_id:"b",parent_id:"c"},{component_id:"a1",parent_id:"a"}]);
  assert.deepEqual(roots.map(node => node.component.component_id),["c"]);
  assert.deepEqual(roots[0].children.map(node => node.component.component_id),["a","b"]);
  assert.equal(roots[0].children[0].children[0].component.component_id,"a1");
  assert.equal(reportTree([{component_id:"x",parent_id:"y"},{component_id:"y",parent_id:"x"}]).length,1);
  assert.equal(validReportComponents([{component_id:"x"},{component_id:"x"}]),false);
  assert.equal(validReportComponents([{kind:"paragraph"}]),false);
});

test("deep report trees are assembled without recursive stack growth", () => {
  const count = 10_000;
  const components = Array.from({length:count},(_,index) => ({component_id:String(index),parent_id:index ? String(index - 1) : null}));
  let node = reportTree(components)[0], seen = 0;
  while (node) {seen++;node = node.children[0];}
  assert.equal(seen,count);
});

test("report Job keeps its recorded server and never guesses federated routing", () => {
  const id = "a".repeat(32), component = {kind:"special",display_kind:"test_result",component_id:`job-${id}-result`};
  const binding = {kind:"evidence",data:{server_id:"manager-b",port:"8001",execution_node_id:"node-b"}};
  assert.deepEqual(reportJobReference(component,[binding]),{job_id:id,server_id:"manager-b",service_port:8001,execution_node_id:"node-b"});
  assert.equal(reportJobReference(component,[]),null);
  assert.equal(reportJobReference(component,[{...binding,data:{server_id:"manager-b"}}]),null);
  assert.equal(reportJobReference(component,[{...binding,data:{server_id:"manager-b",port:"99999"}}]),null);
  assert.equal(reportJobReference(component,[binding,{...binding,data:{server_id:"manager-c",port:"8001"}}]),null);
  assert.equal(reportJobReference({...component,component_id:`job-${"b".repeat(64)}-result`},[binding])?.job_id,"b".repeat(64));
  assert.equal(reportJobReference({...component,component_id:"not-a-job"},[binding]),null);
});
