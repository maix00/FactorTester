import test from "node:test";
import assert from "node:assert/strict";
import {createDraft} from "./draft.ts";
import {configurationDraft,replaceConfiguration,planFromConfiguration,executionChoiceFromDocument,resolutionInputKey,applyResolution} from "./plan-document.ts";
test("form edits are a lens over the one ExecutionPlan JSON draft",()=>{
 const root=planFromConfiguration({schema_version:3,shared:{factors:[]},analyses:{backtest:{}},ui:{}});
 const draft=createDraft(root,2),view=configurationDraft(draft)!;
 const next=replaceConfiguration(draft,{...view,text:JSON.stringify({shared:{factors:[]},analyses:{backtest:{groups:[{id:"a"}]}}})});
 assert.equal(JSON.parse(next.text).run_spec.configuration.analyses.backtest.groups[0].id,"a");
 assert.deepEqual(JSON.parse(next.text).execution,root.execution);assert.equal(next.savedText,draft.savedText);
});
test("editing configuration invalidates the old automatic target",()=>{
 const root=planFromConfiguration({shared:{},analyses:{backtest:{}},ui:{}});(root.execution as any).resolved={target:{node_id:"old"}};
 (root.execution as any).resolved_ref="old";
 const draft=createDraft(root,1),view=configurationDraft(draft)!;
 const next=replaceConfiguration(draft,{...view,text:JSON.stringify({shared:{},analyses:{backtest:{n:2}},ui:{}})});
 assert.equal(JSON.parse(next.text).execution.resolved,undefined);assert.equal(JSON.parse(next.text).execution.resolved_ref,undefined);
});

test("partial ExecutionPlan JSON edits keep the execution form renderable",()=>{
 for(const value of [{},{execution:{}},{execution:{bundles:null}},{execution:{bundles:'invalid'}},{execution:[]}]){
  const choice=executionChoiceFromDocument(value);
  assert.deepEqual(choice.bundles,[]); assert.equal(choice.resolved,undefined);
 }
});

test("resolution invalidates both displayed document fields and rejects an old response",()=>{
 const plan=planFromConfiguration({shared:{},analyses:{backtest:{}},ui:{}});
 (plan.execution as any).resolved={target:{node_id:'old'},inputs:[]};(plan.execution as any).resolved_ref='old';
 const draft=createDraft(plan,1),key=resolutionInputKey(plan);
 const pending=applyResolution(draft,key)!;
 assert.equal(JSON.parse(pending.text).execution.resolved,undefined);
 const changed={...pending,text:pending.text.replace('"manager_id": ""','"manager_id": "other"')};
 assert.equal(applyResolution(changed,key,{binding:{target:{node_id:'stale'}},binding_ref:'stale'}),changed);
 const resolved=applyResolution(pending,key,{binding:{target:{node_id:'current'}},binding_ref:'current'})!;
 assert.equal(JSON.parse(resolved.text).execution.resolved.target.node_id,'current');
 assert.equal(JSON.parse(resolved.text).execution.resolved_ref,'current');
});

test("re-resolving the saved binding with a different key order stays saved",()=>{
 const plan=planFromConfiguration({shared:{},analyses:{backtest:{}},ui:{}});
 (plan.execution as any).resolved={inputs:[],target:{service_id:'s',node_id:'n'}};
 (plan.execution as any).resolved_ref='same';
 const draft=createDraft(plan,1),key=resolutionInputKey(plan);
 const pending=applyResolution(draft,key)!;
 const resolved=applyResolution(pending,key,{binding:{target:{node_id:'n',service_id:'s'},inputs:[]},binding_ref:'same'})!;
 assert.equal(resolved.text,draft.savedText);
});
