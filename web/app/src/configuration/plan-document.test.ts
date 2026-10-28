import test from "node:test";
import assert from "node:assert/strict";
import {createDraft} from "./draft.ts";
import {configurationDraft,replaceConfiguration,planFromConfiguration} from "./plan-document.ts";
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
