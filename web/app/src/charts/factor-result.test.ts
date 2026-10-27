import { test } from "node:test";
import assert from "node:assert/strict";
import { factorIndicators, seriesArtifact, observationBounds } from "./factor-result.ts";
test("factor results keep nulls and exact timestamps and distinguish nested layers", () => {
  const source = [{product:"T",layer:"outer",dates:[100,200,300],values:[0,null,NaN]}, {product:"T",layer:"inner",dates:[150],values:[2]}];
  assert.deepEqual(factorIndicators(source, Number), [{id:"0",label:"F1",points:[{timestamp:100,value:0},{timestamp:200,value:null},{timestamp:300,value:null}]},{id:"1",label:"F2",points:[{timestamp:150,value:2}]}]);
  assert.equal(seriesArtifact([{state:"deleted",name:"factor_series_data"},{state:"active",name:"unrelated"}]), undefined);
  assert.equal(seriesArtifact([{state:"active",name:"factor_series_data"}]), "factor_series_data");
  assert.equal(seriesArtifact([{state:"active",name:"result"}]), undefined);
  assert.equal(seriesArtifact([{state:"active",name:"result"}], true), "result");
});

test("observation bounds use all nested timelines without rounding to days", () => {
  assert.deepEqual(observationBounds([{dates:[2000,1000],values:[]},{dates:[3000],values:[]}], Number), {start_date:"1970-01-01T00:00:01.000Z",end_date:"1970-01-01T00:00:03.000Z"});
  assert.deepEqual(observationBounds([], Number), {});
});
