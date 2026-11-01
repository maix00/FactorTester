import assert from "node:assert/strict";
import test from "node:test";
import { LOCAL_RESEARCH_BRIDGE_SCHEMA, LocalResearchBridgeError, localResearchBridge, sameLocalResearchBinding } from "./local-research-bridge.ts";

const record = {research_id:"research:v1:local",profile_id:"self",title:"本地研究",description:"第一行\n第二行",created_at:100,updated_at:101};
const currentBinding = {issuer:"https://identity.example/realms/research",identity_id:"identity:alice"};
const ok = (value:Record<string,unknown>) => ({success:true,schema:LOCAL_RESEARCH_BRIDGE_SCHEMA,binding:currentBinding,next_offset:null,...value});
const host = (postMessage:(value:Record<string,unknown>)=>unknown) => ({webkit:{messageHandlers:{tradeResearchLocalResearch:{postMessage}}}});
const code = (name:string) => (error:unknown) => error instanceof LocalResearchBridgeError && error.code===name;
const ready = async (postMessage:(value:Record<string,unknown>)=>unknown) => {
  const client=localResearchBridge(host(value=>value.action==="capabilities" ? ok({actions:["list","get","create"],profiles:[{profile_id:"self",display_name:"Self"}]}) : postMessage(value)))!;
  await client.capabilities(currentBinding);return client;
};

test("research directory validates revision and profile across pages", async () => {
  let response=ok({researches:[record],revision:2,next_offset:1});
  const client=localResearchBridge(host(message=>message.action==="capabilities" ?
    ok({actions:["list_researches"],profiles:[{profile_id:"self",display_name:"Self"}]}) : response))!;
  await client.capabilities(currentBinding);
  const first=await client.listResearches("self",{limit:1});
  assert.equal(first.revision,2);
  response=ok({researches:[record],revision:3});
  await assert.rejects(client.listResearches("self",{offset:1,expectedRevision:2}),code("local_research_invalid_response"));
  response=ok({researches:[{...record,profile_id:"other"}],revision:2});
  await assert.rejects(client.listResearches("self"),code("local_research_invalid_response"));
  await assert.rejects(client.listResearches("self",{offset:1}),code("local_research_invalid_input"));
});

test("server research import validates the returned owner scope and identity", async () => {
  let response=ok({research:record,status:"imported"});
  let sent:Record<string,unknown>|undefined;
  const client=localResearchBridge(host(message=>{
    if(message.action==="capabilities")return ok({actions:["import_research"],profiles:[{profile_id:"self",display_name:"Self"}]});
    sent=message;return response;
  }))!;
  await client.capabilities(currentBinding);
  assert.equal((await client.importResearch("self",record.research_id)).status,"imported");
  assert.deepEqual(sent,{action:"import_research",profile_id:"self",research_id:record.research_id});
  response=ok({research:{...record,profile_id:"other"},status:"imported"});
  await assert.rejects(client.importResearch("self",record.research_id),code("local_research_invalid_response"));
  response=ok({research:record,status:"unexpected"});
  await assert.rejects(client.importResearch("self",record.research_id),code("local_research_invalid_response"));
});

test("server discovery queues only bounded unique opaque references", async () => {
  const ref="research:v1:"+"R".repeat(24);
  let response=ok({queued:1});
  const client=localResearchBridge(host(message=>message.action==="capabilities" ?
    ok({actions:["queue_researches"],profiles:[{profile_id:"self",display_name:"Self"}]}) : response))!;
  await client.capabilities(currentBinding);
  assert.equal(await client.queueResearches("self",[ref]),1);
  await assert.rejects(client.queueResearches("self",[ref,ref]),code("local_research_invalid_input"));
  await assert.rejects(client.queueResearches("self",["bad"]),code("local_research_invalid_input"));
  response=ok({queued:2});
  await assert.rejects(client.queueResearches("self",[ref]),code("local_research_invalid_response"));
});

test("background discovery validates cursor and bounded queue count", async () => {
  let response=ok({queued:1,next_cursor:"opaque-token"});
  const client=localResearchBridge(host(message=>message.action==="capabilities" ?
    ok({actions:["discover_researches"],profiles:[{profile_id:"self",display_name:"Self"}]}) : response))!;
  await client.capabilities(currentBinding);
  assert.deepEqual(await client.discoverResearches("self","",2),{queued:1,next_cursor:"opaque-token"});
  response=ok({queued:1,next_cursor:"opaque-token"});
  await assert.rejects(client.discoverResearches("self","opaque-token",2),code("local_research_invalid_response"));
  response=ok({queued:3,next_cursor:null});
  await assert.rejects(client.discoverResearches("self","",2),code("local_research_invalid_response"));
});

test("profile report directory validates its profile and linked research", async () => {
  const {description:_description,...summary}=record;
  const row={report_id:"report:one",research_id:record.research_id,profile_id:"self",title:"Report",created_at:100,research:summary};
  let received:Record<string,unknown>|undefined;
  let response=ok({reports:[row],revision:2});
  const client=localResearchBridge(host(message=>{
    if(message.action==="capabilities")return ok({actions:["list_profile_reports"],profiles:[{profile_id:"self",display_name:"Self"}]});
    received=message;return response;
  }))!;
  await client.capabilities(currentBinding);
  assert.deepEqual((await client.listProfileReports("self",{limit:1})).reports,[row]);
  assert.deepEqual(received,{action:"list_profile_reports",profile_id:"self",offset:0,limit:1,expected_revision:null});
  response=ok({reports:[{...row,research:{...record,research_id:"other"}}],revision:2});
  await assert.rejects(client.listProfileReports("self"),code("local_research_invalid_response"));
  response=ok({reports:[{...row,profile_id:"other"}],revision:2});
  await assert.rejects(client.listProfileReports("self"),code("local_research_invalid_response"));
  response=ok({reports:[row],revision:3});
  await assert.rejects(client.listProfileReports("self",{offset:1,expectedRevision:2}),code("local_research_invalid_response"));
});

test("capability detection never invokes an absent or incomplete host", () => {
  assert.equal(localResearchBridge(undefined),null);
  assert.equal(localResearchBridge({webkit:{messageHandlers:{}}}),null);
  assert.equal(localResearchBridge({webkit:{messageHandlers:{tradeResearchLocalResearch:{postMessage:"not-a-function"}}}}),null);
  assert.equal(localResearchBridge({webkit:{messageHandlers:{factorTesterLocalCatalog:{postMessage(){throw Error("must not call")}}}}}),null);
});

test("page and native identity must match by issuer and stable ID", async () => {
  let calls=0;
  const client=localResearchBridge(host(()=>{calls++;return ok({actions:["list"],profiles:[{profile_id:"self",display_name:"Self"}]});}))!;
  await assert.rejects(client.capabilities({issuer:"",identity_id:"identity:alice"}),code("local_research_session_unverified"));
  assert.equal(calls,0);
  await assert.rejects(client.capabilities({issuer:"https://other.example/realms/research",identity_id:"identity:alice"}),code("local_research_session_mismatch"));
  await assert.rejects(client.list("self"),code("local_research_capability_unavailable"));
  assert.equal(sameLocalResearchBinding(currentBinding,{...currentBinding,issuer:currentBinding.issuer+"/"}),true);
  assert.equal(sameLocalResearchBinding(currentBinding,{...currentBinding,identity_id:"identity:bob"}),false);
  assert.equal(sameLocalResearchBinding(currentBinding,{...currentBinding,issuer:"https://identity.example/realms/research?other=1"}),false);
  await client.capabilities({...currentBinding,issuer:currentBinding.issuer+"/"});
});

test("the expected session is frozen before an asynchronous capability probe", async () => {
  let resolve!:(value:unknown)=>void;
  const client=localResearchBridge(host(()=>new Promise(done=>{resolve=done;})))!;
  const expected={...currentBinding};
  const pending=client.capabilities(expected);
  expected.identity_id="identity:bob";
  resolve(ok({binding:{...currentBinding,identity_id:"identity:bob"},actions:["list"],profiles:[]}));
  await assert.rejects(pending,code("local_research_session_mismatch"));
});

test("requests contain only local business fields and responses discard extra data", async () => {
  const sent:Record<string,unknown>[]=[];
  const client=localResearchBridge(host(message=>{
    sent.push(message);
    if(message.action==="capabilities")return ok({actions:["list","create","get"],profiles:[{profile_id:"self",display_name:"Self",private_path:"/secret"}]});
    if(message.action==="list")return ok({researches:[{...record,owner_ref:"not-trusted",path:"/secret"}]});
    return ok({research:{...record,owner_ref:"not-trusted",path:"/secret"}});
  }))!;
  assert.deepEqual(await client.capabilities(currentBinding),{binding:currentBinding,actions:["list","create","get"],profiles:[{profile_id:"self",display_name:"Self"}]});
  assert.deepEqual(await client.list("self"),{researches:[record],next_offset:null});
  assert.deepEqual(await client.get("self",record.research_id),record);
  assert.deepEqual(await client.create({...record,operation_id:"op-1",owner:"other",path:"/secret",token:"secret"} as never),record);
  assert.deepEqual(sent,[
    {action:"capabilities"},{action:"list",profile_id:"self",offset:0,limit:100},{action:"get",profile_id:"self",research_id:record.research_id},
    {action:"create",profile_id:"self",title:record.title,description:record.description,operation_id:"op-1"},
  ]);
});

test("wrong schema, duplicate identities, mismatched objects and invalid values fail closed", async () => {
  const client=await ready(()=>ok({researches:[record,record]}));
  await assert.rejects(client.list("self"),code("local_research_invalid_response"));
  await assert.rejects((await ready(()=>({success:true,schema:"future",researches:[]}))).list("self"),code("local_research_invalid_response"));
  await assert.rejects(localResearchBridge(host(()=>ok({actions:["list","list"],profiles:[]})))!.capabilities(currentBinding),code("local_research_invalid_response"));
  await assert.rejects((await ready(()=>ok({research:{...record,profile_id:"other"}}))).get("self",record.research_id),code("local_research_invalid_response"));
  await assert.rejects((await ready(()=>ok({research:{...record,created_at:NaN}}))).create({...record,operation_id:"op-1"}),code("local_research_invalid_response"));
  await assert.rejects(client.create({...record,title:"\u0000",operation_id:"op-1"}),code("local_research_invalid_input"));
});

test("local listing is bounded, profile-scoped and validates continuation", async () => {
  const sent:Record<string,unknown>[]=[];
  const client=await ready(message=>{sent.push(message);return ok({researches:[record],next_offset:11});});
  assert.deepEqual(await client.list("self",{offset:10,limit:1}),{researches:[record],next_offset:11});
  assert.deepEqual(sent,[{action:"list",profile_id:"self",offset:10,limit:1}]);
  await assert.rejects(client.list("other"),code("local_research_profile_unavailable"));
  await assert.rejects(client.list("self",{limit:201}),code("local_research_invalid_input"));
  await assert.rejects(client.list("self",{offset:-1}),code("local_research_invalid_input"));
  assert.equal(sent.length,1);
  await assert.rejects((await ready(()=>ok({researches:[{...record,profile_id:"other"}]}))).list("self"),code("local_research_invalid_response"));
  await assert.rejects((await ready(()=>ok({researches:[],next_offset:1}))).list("self"),code("local_research_invalid_response"));
  await assert.rejects((await ready(()=>ok({researches:[record],next_offset:undefined}))).list("self"),code("local_research_invalid_response"));
});

test("native errors and transport failures do not expose arbitrary messages", async () => {
  await assert.rejects((await ready(()=>({success:false,code:"identity_unavailable",error:"secret"}))).list("self"),code("identity_unavailable"));
  await assert.rejects((await ready(()=>({success:false,code:"secret / path"}))).list("self"),code("local_research_bridge_failed"));
  await assert.rejects((await ready(()=>{throw Error("secret / path");})).list("self"),code("local_research_bridge_failed"));
});

test("late replies after account changes or closure are rejected without retry", async () => {
  let resolve!:(value:unknown)=>void, calls=0;
  const client=await ready(()=>{calls++;return new Promise(done=>{resolve=done;});});
  const snapshot=client.snapshot();
  const pending=client.list("self");client.invalidate();resolve(ok({researches:[record]}));
  await assert.rejects(pending,code("local_research_session_changed"));
  assert.equal(client.isCurrent(snapshot),false);
  await assert.rejects(client.list("self"),code("local_research_capability_unavailable"));
  await client.capabilities(currentBinding);
  const pendingCreate=client.create({...record,operation_id:"op-1"});client.close();resolve(ok({research:record}));
  await assert.rejects(pendingCreate,code("local_research_session_changed"));
  await assert.rejects(client.list("self"),code("local_research_client_closed"));
  assert.equal(calls,2);
});

test("write retries remain explicit and retain the operation identity", async () => {
  const sent:Record<string,unknown>[]=[];
  const client=await ready(message=>{sent.push(message);if(sent.length===1)throw Error("reply lost");return ok({research:record});});
  const input={...record,operation_id:"stable-op"};
  await assert.rejects(client.create(input),code("local_research_bridge_failed"));
  assert.equal(sent.length,1);
  assert.deepEqual(await client.create(input),record);
  assert.deepEqual(sent[0],sent[1]);
});

test("unsupported actions never reach the native host", async () => {
  const sent:Record<string,unknown>[]=[];
  const client=localResearchBridge(host(value=>{sent.push(value);return ok({actions:["list"],profiles:[]});}))!;
  await assert.rejects(client.list("self"),code("local_research_capability_unavailable"));
  await client.capabilities(currentBinding);
  await assert.rejects(client.create({...record,operation_id:"op-1"}),code("local_research_capability_unavailable"));
  assert.deepEqual(sent,[{action:"capabilities"}]);
});

test("failed capability refresh clears old permissions", async () => {
  let probes=0, operations=0;
  const client=localResearchBridge(host(value=>{
    if(value.action!=="capabilities"){operations++;return ok({researches:[]});}
    return ++probes===1 ? ok({actions:["list"],profiles:[]}) : {success:false,code:"identity_unavailable"};
  }))!;
  await client.capabilities(currentBinding);
  await assert.rejects(client.capabilities(currentBinding),code("identity_unavailable"));
  await assert.rejects(client.list("self"),code("local_research_capability_unavailable"));
  assert.equal(operations,0);
});

test("a slower old capability response cannot override a newer one", async () => {
  const resolve:((value:unknown)=>void)[]=[];
  const client=localResearchBridge(host(()=>new Promise(done=>{resolve.push(done);})))!;
  const old=client.capabilities(currentBinding), newest=client.capabilities(currentBinding);
  resolve[1](ok({actions:["list"],profiles:[]}));
  await newest;
  resolve[0](ok({actions:["create"],profiles:[]}));
  await assert.rejects(old,code("local_research_capabilities_superseded"));
  await assert.rejects(client.create({...record,operation_id:"op-1"}),code("local_research_capability_unavailable"));
});

test("a session change between native resolution and result parsing is discarded", async () => {
  let resolve!:(value:unknown)=>void;
  const client=await ready(()=>new Promise(done=>{resolve=done;}));
  const pending=client.list("self");
  resolve(ok({researches:[record]}));
  queueMicrotask(()=>client.invalidate());
  await assert.rejects(pending,code("local_research_session_changed"));
});

test("refreshing capabilities invalidates an in-flight list", async () => {
  let resolveList!:(value:unknown)=>void;
  const client=await ready(()=>new Promise(done=>{resolveList=done;}));
  const pending=client.list("self");
  await client.capabilities(currentBinding);
  resolveList(ok({researches:[record]}));
  await assert.rejects(pending,code("local_research_capabilities_superseded"));
});

test("catalog report import checks returned identity and session scope", async () => {
  const item={report_id:"report:v1:"+"R".repeat(24),research_id:record.research_id,profile_id:"self",title:"Report",created_at:1};
  let response=ok({report:item,status:"imported"});
  const client=localResearchBridge(host(message=>message.action==="capabilities" ?
    ok({actions:["import_catalog_report"],profiles:[{profile_id:"self",display_name:"Self"}]}) : response))!;
  await client.capabilities(currentBinding);
  assert.equal((await client.importCatalogReport("self",record.research_id,item.report_id)).status,"imported");
  response=ok({report:{...item,report_id:"other"},status:"imported"});
  await assert.rejects(client.importCatalogReport("self",record.research_id,item.report_id),code("local_research_invalid_response"));
  response=ok({report:item,status:"unexpected"});
  await assert.rejects(client.importCatalogReport("self",record.research_id,item.report_id),code("local_research_invalid_response"));
});

test("background report discovery validates import and scan outcomes", async () => {
  const item={report_id:"report-1",research_id:record.research_id,status:"imported"};
  let response=ok({reports:[],researches:[],next_report_id:null,report_imports:[item],report_scans:[],report_imports_pending_more:true});
  const client=localResearchBridge(host(message=>message.action==="capabilities" ?
    ok({actions:["sync_reports"],profiles:[{profile_id:"self",display_name:"Self"}]}) : response))!;
  await client.capabilities(currentBinding);
  const result=await client.syncReports("self","",4);
  assert.deepEqual(result.report_imports,[item]);
  assert.equal(result.report_imports_pending_more,true);
  response=ok({reports:[],researches:[],next_report_id:null,report_scans:[
    {research_id:"",status:"unavailable"},{research_id:record.research_id,status:"conflict"}]});
  assert.deepEqual((await client.syncReports("self","",4)).report_scans,[
    {research_id:"",status:"unavailable"},{research_id:record.research_id,status:"conflict"}]);
  response=ok({reports:[],researches:[],next_report_id:null,report_imports:[{...item,status:"unknown"}]});
  await assert.rejects(client.syncReports("self","",4),code("local_research_invalid_response"));
  response=ok({reports:[],researches:[],next_report_id:null,report_scans:[{research_id:record.research_id,status:"unknown"}]});
  await assert.rejects(client.syncReports("self","",4),code("local_research_invalid_response"));
});
