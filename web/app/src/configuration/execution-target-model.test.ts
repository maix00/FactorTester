import test from "node:test";
import assert from "node:assert/strict";
import { executionRequest, type ExecutionTarget } from "./execution-target-model.ts";
const offer={ source_ref:"source-b",product_ref:"T",bar_spec:"1-MINUTE-LAST-EXTERNAL",price_basis:"raw",time_semantics:"bar-end",fields:["close"],coverage_start_ns:0,coverage_end_ns:2e18,available:true,installation:{bundle_id:"cn",bundle_version:"1",node_id:"b"} };
const target:ExecutionTarget={route_id:"route",service_port:8000,online:true,target:{manager_id:"a",node_id:"b",service_id:"backtest",deployment_ref:"v1",test_types:["backtest"]},offers:[offer]};
test("RunSpec requirements exclude node identity while execution selection binds it",()=>{const result=executionRequest(target,[offer],"2024-01-01T00:00","2025-01-01T00:00","backtest");assert.equal(("target" in result.execution_selection ? result.execution_selection.target.node_id : ""),"b");assert.equal(result.data_requirements[0].product_ref,"T");assert.equal("source_ref" in result.data_requirements[0],false);});
test("invalid target, duplicate product and incomplete dates never produce a run request",()=>{assert.throws(()=>executionRequest({...target,online:false},[offer],"2024-01-01","2025-01-01","backtest"));assert.throws(()=>executionRequest(target,[offer,offer],"2024-01-01","2025-01-01","backtest"));assert.throws(()=>executionRequest(target,[offer],"","","backtest"));});

test("automatic selection freezes requirements without selecting a physical source",async()=>{const {automaticExecutionRequest,selectionManager}=await import("./execution-target-model.ts");const request=automaticExecutionRequest([offer],"2024-01-01","2025-01-01","backtest","a");assert.equal(selectionManager(request),"a");assert.equal("sources" in request.execution_selection,false);assert.equal("target" in request.execution_selection,false);});

test("ordinary research users discover Manager IDs without administrative peer access",async()=>{
 const {executionManagerIDs}=await import('./execution-target-model.ts');
 assert.deepEqual(executionManagerIDs({server_id:'local',internal_server_targets:[{server_id:'local',online:true}],public_server_targets:[{server_id:'public',online:true},{server_id:'offline',online:false},{server_id:''},null]}),['local','public']);
 assert.deepEqual(executionManagerIDs({server_id:'local',public_server_targets:'invalid'}),['local']);
 assert.deepEqual(executionManagerIDs({}),[]);
});
