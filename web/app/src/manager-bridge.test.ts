import test from "node:test";
import assert from "node:assert/strict";
import {MANAGER_BRIDGE_SCHEMA,ManagerBridgeError,ManagerClient,managerBridge,managerURL} from "./manager-bridge.ts";

const schema=MANAGER_BRIDGE_SCHEMA;
const response=(extra:Record<string,unknown>={})=>({success:true,schema,...extra});
const deferred=()=>{let resolve!:(value:unknown)=>void;const promise=new Promise<unknown>(done=>{resolve=done;});return {promise,resolve};};
const reason=(code:string)=>(error:unknown)=>error instanceof ManagerBridgeError && error.code===code;

test("only a complete handler is recognized; no web request is sent",()=>{
  assert.equal(managerBridge({}),null);
  assert.equal(managerBridge({webkit:{messageHandlers:{tradeResearchManager:{}}}}),null);
  assert.ok(managerBridge({webkit:{messageHandlers:{tradeResearchManager:{postMessage(){return response();}}}}}));
});
test("url validation rejects credentials, queries, fragments and invalid protocols",()=>{
  assert.equal(managerURL("https://example.test:443/"),"https://example.test");
  assert.equal(managerURL("http://127.0.0.1:7998/"),"http://127.0.0.1:7998");
  for(const bad of [" https://example.test","ftp://example.test","https://u:p@example.test","https://example.test/?secret=x","https://example.test/#x","not-a-url"])assert.throws(()=>managerURL(bad),reason("manager_invalid_url"));
});
test("capabilities and a validated current response precede changes",async()=>{
  const calls:Record<string,unknown>[]=[];
  const client=new ManagerClient({postMessage(message){calls.push(message);return response(message.action==="capabilities"?{actions:["current","switch"]}:{url:"http://127.0.0.1:7998",auth_state:"authorized"});}});
  await assert.rejects(client.current(),reason("manager_capability_unavailable"));
  await client.capabilities();
  assert.deepEqual(await client.current(),{url:"http://127.0.0.1:7998",auth_state:"authorized"});
  assert.deepEqual(calls,[{action:"capabilities"},{action:"current"}]);
});
test("switch requests contain only URL and result is never guessed",async()=>{
  const calls:Record<string,unknown>[]=[];
  const client=new ManagerClient({postMessage(message){calls.push(message);return response(message.action==="capabilities"?{actions:["current","switch"]}:{url:message.url,auth_state:"unauthorized"});}});
  await client.capabilities();
  assert.deepEqual(await client.switchTo("https://manager.test/"),{url:"https://manager.test",auth_state:"unauthorized"});
  assert.deepEqual(calls[1],{action:"switch",url:"https://manager.test"});
  await assert.rejects(client.switchTo("https://user:secret@manager.test"),reason("manager_invalid_url"));
  assert.equal(calls.length,2);
});
test("reject incomplete capability, invalid schema, unknown state and different destination",async()=>{
  const incomplete=new ManagerClient({postMessage(){return response({actions:["current"]});}});
  await assert.rejects(incomplete.capabilities(),reason("manager_capability_unavailable"));
  const badSchema=new ManagerClient({postMessage(){return {success:true,schema:"old",actions:["current","switch"]};}});
  await assert.rejects(badSchema.capabilities(),reason("manager_invalid_response"));
  for(const reply of [{url:"https://target.test",auth_state:"maybe"},{url:"https://other.test",auth_state:"authorized"}]){
    const client=new ManagerClient({postMessage(message){return response(message.action==="capabilities"?{actions:["current","switch"]}:reply);}});
    await client.capabilities();await assert.rejects(client.switchTo("https://target.test"),reason("manager_invalid_response"));
  }
});
test("old current results cannot override a later switch",async()=>{
  const wait=deferred();
  const client=new ManagerClient({postMessage(message){return message.action==="capabilities"?response({actions:["current","switch"]}):message.action==="current"?wait.promise:response({url:message.url,auth_state:"unavailable"});}});
  await client.capabilities();const current=client.current();
  assert.equal((await client.switchTo("https://target.test")).auth_state,"unavailable");
  wait.resolve(response({url:"https://old.test",auth_state:"authorized"}));
  await assert.rejects(current,reason("manager_session_changed"));
});
test("late replies after closure, duplicate switches and transport errors fail closed",async()=>{
  const wait=deferred();
  const client=new ManagerClient({postMessage(message){return message.action==="capabilities"?response({actions:["current","switch"]}):wait.promise;}});
  await client.capabilities();const first=client.switchTo("https://target.test");
  await assert.rejects(client.switchTo("https://target.test"),reason("manager_switch_pending"));
  client.close();wait.resolve(response({url:"https://target.test",auth_state:"authorized"}));
  await assert.rejects(first,reason("manager_session_changed"));
  const failed=new ManagerClient({postMessage(){throw Error("sensitive native detail");}});
  await assert.rejects(failed.capabilities(),reason("manager_bridge_failed"));
});
