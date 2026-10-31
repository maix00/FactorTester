import assert from "node:assert/strict";
import test from "node:test";
import { LOCAL_RESEARCH_BRIDGE_SCHEMA, LocalResearchBridgeError, localResearchBridge } from "./local-research-bridge.ts";

const record = {research_id:"research:v1:local",profile_id:"self",title:"本地研究",description:"第一行\n第二行",created_at:100,updated_at:101};
const ok = (value:Record<string,unknown>) => ({success:true,schema:LOCAL_RESEARCH_BRIDGE_SCHEMA,...value});
const host = (postMessage:(value:Record<string,unknown>)=>unknown) => ({webkit:{messageHandlers:{tradeResearchLocalResearch:{postMessage}}}});
const code = (name:string) => (error:unknown) => error instanceof LocalResearchBridgeError && error.code===name;
const ready = async (postMessage:(value:Record<string,unknown>)=>unknown) => {
  const client=localResearchBridge(host(value=>value.action==="capabilities" ? ok({actions:["list","get","create"],profiles:[]}) : postMessage(value)))!;
  await client.capabilities();return client;
};

test("capability detection never invokes an absent or incomplete host", () => {
  assert.equal(localResearchBridge(undefined),null);
  assert.equal(localResearchBridge({webkit:{messageHandlers:{}}}),null);
  assert.equal(localResearchBridge({webkit:{messageHandlers:{tradeResearchLocalResearch:{postMessage:"not-a-function"}}}}),null);
  assert.equal(localResearchBridge({webkit:{messageHandlers:{factorTesterLocalCatalog:{postMessage(){throw Error("must not call")}}}}}),null);
});

test("requests contain only local business fields and responses discard extra data", async () => {
  const sent:Record<string,unknown>[]=[];
  const client=localResearchBridge(host(message=>{
    sent.push(message);
    if(message.action==="capabilities")return ok({actions:["list","create","get"],profiles:[{profile_id:"self",display_name:"Self",private_path:"/secret"}]});
    if(message.action==="list")return ok({researches:[{...record,owner_ref:"not-trusted",path:"/secret"}]});
    return ok({research:{...record,owner_ref:"not-trusted",path:"/secret"}});
  }))!;
  assert.deepEqual(await client.capabilities(),{actions:["list","create","get"],profiles:[{profile_id:"self",display_name:"Self"}]});
  assert.deepEqual(await client.list(),[record]);
  assert.deepEqual(await client.get("self",record.research_id),record);
  assert.deepEqual(await client.create({...record,operation_id:"op-1",owner:"other",path:"/secret",token:"secret"} as never),record);
  assert.deepEqual(sent,[
    {action:"capabilities"},{action:"list"},{action:"get",profile_id:"self",research_id:record.research_id},
    {action:"create",profile_id:"self",title:record.title,description:record.description,operation_id:"op-1"},
  ]);
});

test("wrong schema, duplicate identities, mismatched objects and invalid values fail closed", async () => {
  const client=await ready(()=>ok({researches:[record,record]}));
  await assert.rejects(client.list(),code("local_research_invalid_response"));
  await assert.rejects((await ready(()=>({success:true,schema:"future",researches:[]}))).list(),code("local_research_invalid_response"));
  await assert.rejects(localResearchBridge(host(()=>ok({actions:["list","list"],profiles:[]})))!.capabilities(),code("local_research_invalid_response"));
  await assert.rejects((await ready(()=>ok({research:{...record,profile_id:"other"}}))).get("self",record.research_id),code("local_research_invalid_response"));
  await assert.rejects((await ready(()=>ok({research:{...record,created_at:NaN}}))).create({...record,operation_id:"op-1"}),code("local_research_invalid_response"));
  await assert.rejects(client.create({...record,title:"\u0000",operation_id:"op-1"}),code("local_research_invalid_input"));
});

test("native errors and transport failures do not expose arbitrary messages", async () => {
  await assert.rejects((await ready(()=>({success:false,code:"identity_unavailable",error:"secret"}))).list(),code("identity_unavailable"));
  await assert.rejects((await ready(()=>({success:false,code:"secret / path"}))).list(),code("local_research_bridge_failed"));
  await assert.rejects((await ready(()=>{throw Error("secret / path");})).list(),code("local_research_bridge_failed"));
});

test("late replies after account changes or closure are rejected without retry", async () => {
  let resolve!:(value:unknown)=>void, calls=0;
  const client=await ready(()=>{calls++;return new Promise(done=>{resolve=done;});});
  const snapshot=client.snapshot();
  const pending=client.list();client.invalidate();resolve(ok({researches:[record]}));
  await assert.rejects(pending,code("local_research_session_changed"));
  assert.equal(client.isCurrent(snapshot),false);
  await assert.rejects(client.list(),code("local_research_capability_unavailable"));
  await client.capabilities();
  const pendingCreate=client.create({...record,operation_id:"op-1"});client.close();resolve(ok({research:record}));
  await assert.rejects(pendingCreate,code("local_research_session_changed"));
  await assert.rejects(client.list(),code("local_research_client_closed"));
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
  await assert.rejects(client.list(),code("local_research_capability_unavailable"));
  await client.capabilities();
  await assert.rejects(client.create({...record,operation_id:"op-1"}),code("local_research_capability_unavailable"));
  assert.deepEqual(sent,[{action:"capabilities"}]);
});

test("failed capability refresh clears old permissions", async () => {
  let probes=0, operations=0;
  const client=localResearchBridge(host(value=>{
    if(value.action!=="capabilities"){operations++;return ok({researches:[]});}
    return ++probes===1 ? ok({actions:["list"],profiles:[]}) : {success:false,code:"identity_unavailable"};
  }))!;
  await client.capabilities();
  await assert.rejects(client.capabilities(),code("identity_unavailable"));
  await assert.rejects(client.list(),code("local_research_capability_unavailable"));
  assert.equal(operations,0);
});

test("a slower old capability response cannot override a newer one", async () => {
  const resolve:((value:unknown)=>void)[]=[];
  const client=localResearchBridge(host(()=>new Promise(done=>{resolve.push(done);})))!;
  const old=client.capabilities(), newest=client.capabilities();
  resolve[1](ok({actions:["list"],profiles:[]}));
  await newest;
  resolve[0](ok({actions:["create"],profiles:[]}));
  await assert.rejects(old,code("local_research_capabilities_superseded"));
  await assert.rejects(client.create({...record,operation_id:"op-1"}),code("local_research_capability_unavailable"));
});

test("a session change between native resolution and result parsing is discarded", async () => {
  let resolve!:(value:unknown)=>void;
  const client=await ready(()=>new Promise(done=>{resolve=done;}));
  const pending=client.list();
  resolve(ok({researches:[record]}));
  queueMicrotask(()=>client.invalidate());
  await assert.rejects(pending,code("local_research_session_changed"));
});
