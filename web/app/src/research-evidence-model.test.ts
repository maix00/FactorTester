import assert from "node:assert/strict";
import test from "node:test";
import { applicabilityDraft, applicabilityValue } from "./research-evidence-model.ts";

test("editing exposed scope preserves frozen hidden identity fields", () => {
  const fields = [{name:"factor_refs",type:"string_array"},{name:"product_scope_ref",type:"reference"},{name:"time_window",type:"time_window"},{name:"contract_hash",type:"sha256",exposed:false}];
  const initial = {factor_refs:["factor:old"],product_scope_ref:"product-group:old",time_window:{start:"2020",end:"2021"},contract_hash:"a".repeat(64),factor_subjects:[{ref:"factor:old"}]};
  const draft = applicabilityDraft(initial, fields); draft.factor_refs="factor:old\nfactor:new\n"; draft.product_scope_ref=""; draft["time_window.end"]="";
  assert.deepEqual(applicabilityValue(initial, fields, draft), {factor_refs:["factor:old","factor:new"],time_window:{start:"2020"},contract_hash:"a".repeat(64),factor_subjects:[{ref:"factor:old"}]});
  assert.equal(initial.product_scope_ref,"product-group:old");
});

test("unknown exposed field types remain unchanged rather than being erased", () => {
  const fields = [{name:"future_type",type:"future_type"}];
  assert.deepEqual(applicabilityValue({future_type:{nested:true}},fields,applicabilityDraft({},fields)),{future_type:{nested:true}});
});
