import assert from "node:assert/strict";
import test from "node:test";
import { AssistantContextPublisher } from "./assistant-context-publisher.ts";

const context = (pageId:string,researchId:string,section = "details") => ({pageId,researchId,section,title:"Private title"});

test("a delayed old publish cannot win over a new page or escape its workspace", async () => {
  const requests:Array<{url:string;body:any}> = [], statuses:string[] = [];
  let release:(() => void) | undefined;
  const publisher = new AssistantContextPublisher(async (url,options) => {
    const body = options?.body ? JSON.parse(String(options.body)) : null;
    requests.push({url,body});
    if (body?.workspace?.client_revision === 1) await new Promise<void>(resolve => {release = resolve;});
    const tab = body?.workspace?.tabs?.[0];
    return {page:tab ? {tab_id:tab.tab_id,assistance:tab.assistance} : null};
  },"self","workspace-a",value => statuses.push(value));
  publisher.set(context("panel-a","research-a"));
  publisher.set(context("panel-b","research-b","evidence"));
  release?.();
  await publisher.ready();
  const published = requests.filter(item => item.body?.workspace);
  assert.equal(published.at(-1)?.body.workspace.tabs[0].research_id,"research-b");
  assert.ok(published.every(item => item.body.workspace_id === "workspace-a"));
  assert.deepEqual(published.map(item => item.body.workspace.client_revision),[1,2]);
  assert.equal(statuses.at(-1),"ready");
  await publisher.close();
  const removal = new URL(requests.at(-1)!.url,"https://local.invalid");
  assert.equal(removal.searchParams.get("workspace_id"),"workspace-a");
  assert.equal(removal.searchParams.get("tab_id"),"panel-b");
  assert.equal(removal.searchParams.get("client_revision"),"3");
});

test("an unauthorized page is not marked ready and blocks the next turn", async () => {
  const statuses:string[] = [];
  const publisher = new AssistantContextPublisher(async (url) => url.includes("publish") ? {page:null} : {success:true},
    "self","workspace-a",value => statuses.push(value));
  publisher.set(context("panel-a","research-a"));
  await assert.rejects(() => publisher.ready(),/not authorized/);
  assert.equal(statuses.at(-1),"unavailable");
  await publisher.close();
});

test("a lost publish response must be removed before a context-free turn", async () => {
  let removals = 0, unavailable:() => void = () => undefined;
  const failed = new Promise<void>(resolve => {unavailable = resolve;});
  const publisher = new AssistantContextPublisher(async url => {
    if (url.includes("publish")) throw new Error("response lost");
    if (++removals === 1) throw new Error("cleanup unavailable");
    return {success:true};
  },"self","workspace-a",status => {if (status === "unavailable") unavailable();});
  publisher.set(context("panel-a","research-a"));
  await failed;
  publisher.set(null);
  await publisher.ready();
  assert.equal(removals,2);
  await publisher.close();
});
