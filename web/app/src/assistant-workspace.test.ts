import assert from "node:assert/strict";
import test from "node:test";
import { AssistantWorkspaceSession, createAssistantWorkspace } from "./assistant-workspace.ts";

test("assistant workspace must be issued for the current Profile", async () => {
  const calls:Array<{url:string;options?:RequestInit}> = [];
  const request = async (url:string,options?:RequestInit) => {calls.push({url,options});return {workspace_id:"issued-workspace"};};
  assert.equal(await createAssistantWorkspace(request,"self"),"issued-workspace");
  assert.equal(calls[0].url,"/api/client/profile-agent/assistance/workspaces");
  assert.deepEqual(JSON.parse(String(calls[0].options?.body)),{profile_id:"self"});
  await assert.rejects(() => createAssistantWorkspace(async () => ({}),"self"));
});

test("Agent turns wait for an authorized context and release only their own workspace", async () => {
  const calls:Array<{url:string;body:any}> = [];
  const session = await AssistantWorkspaceSession.open(async (url,options) => {
    const body = options?.body ? JSON.parse(String(options.body)) : null;
    calls.push({url,body});
    if (url.endsWith("/workspaces")) return {workspace_id:"workspace-a"};
    if (url.endsWith("/publish")) {const tab=body.workspace.tabs[0];return {page:{tab_id:tab.tab_id,assistance:tab.assistance}};}
    return {success:true};
  },"self");
  session.set({pageId:"panel-a",researchId:"research-a",title:"A",section:"details"});
  await session.request("/api/client/profile-agent/rpc",{method:"POST",body:JSON.stringify({method:"turn/start",params:{text:"hello"}})});
  const rpc = calls.findIndex(call => call.url.endsWith("/rpc"));
  assert.ok(rpc > calls.findIndex(call => call.url.endsWith("/publish")));
  assert.equal(calls[rpc].body.workspace_id,"workspace-a");
  assert.deepEqual(calls[rpc].body.params,{text:"hello"});
  await session.close();
  assert.ok(calls.some(call => call.url.includes("/assistance/page?") && call.url.includes("workspace_id=workspace-a")));
  assert.ok(calls.some(call => call.url.includes("/assistance/workspaces?") && call.url.includes("workspace_id=workspace-a")));
});

test("expired workspaces are reissued before retrying a rejected turn", async () => {
  let issued=0, dispatches=0;
  const calls:Array<{url:string;body:any}> = [];
  const expired = Object.assign(new Error("expired"),{code:"assistance_workspace_expired"});
  const session = await AssistantWorkspaceSession.open(async (url,options) => {
    const body=options?.body ? JSON.parse(String(options.body)) : null;
    calls.push({url,body});
    if (url.endsWith("/workspaces")) return {workspace_id:`workspace-${++issued}`};
    if (url.endsWith("/publish")) {
      if (body.workspace_id === "workspace-1") throw expired;
      const tab=body.workspace.tabs[0];return {page:{tab_id:tab.tab_id,assistance:tab.assistance}};
    }
    if (url.includes("workspace_id=workspace-1")) throw expired;
    if (url.endsWith("/rpc")) {dispatches++;return {success:true};}
    return {success:true};
  },"self");
  session.set({pageId:"panel-a",researchId:"research-a",title:"A",section:"details"});
  await session.request("/api/client/profile-agent/rpc",{method:"POST",body:JSON.stringify({method:"turn/start"})});
  assert.equal(issued,2);
  assert.equal(dispatches,1);
  assert.equal(calls.find(call => call.url.endsWith("/rpc"))?.body.workspace_id,"workspace-2");
  await session.close();
});

test("a context-free expired RPC is retried once, but authorization denial is not", async () => {
  let issued=0, attempts=0, denied=false;
  const session = await AssistantWorkspaceSession.open(async (url,options) => {
    if (url.endsWith("/workspaces")) return {workspace_id:`workspace-${++issued}`};
    if (url.endsWith("/rpc")) {
      attempts++;
      if (denied) throw Object.assign(new Error("denied"),{code:"permission_denied"});
      if (JSON.parse(String(options?.body)).workspace_id === "workspace-1") throw Object.assign(new Error("expired"),{code:"assistance_workspace_expired"});
    }
    return {success:true};
  },"self");
  const turn={method:"POST",body:JSON.stringify({method:"turn/start"})};
  await session.request("/api/client/profile-agent/rpc",turn);
  assert.equal(issued,2);assert.equal(attempts,2);
  denied=true;
  await assert.rejects(() => session.request("/api/client/profile-agent/rpc",turn),/denied/);
  assert.equal(issued,2);assert.equal(attempts,3);
  await session.close();
});
