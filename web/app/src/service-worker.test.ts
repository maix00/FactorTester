import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

test("shell cache bounds concurrent asset versions and preserves unrelated caches and private APIs",async()=>{
 const handlers:Record<string,(event:any)=>void>={};
 const stores=new Map<string,Map<string,Response>>([["tr-shell-v2",new Map()],["unrelated-data",new Map()]]);
 const caches={keys:async()=>[...stores.keys()],delete:async(key:string)=>stores.delete(key),open:async(key:string)=>{
  if(!stores.has(key))stores.set(key,new Map());const data=stores.get(key)!;
  return {put:async(request:Request,response:Response)=>{await new Promise(resolve=>setTimeout(resolve,1));data.set(request.url,response);},keys:async()=>[...data.keys()].map(url=>new Request(url)),delete:async(request:Request)=>data.delete(request.url)};
 }};
 runInNewContext(readFileSync(new URL("../../../server/manager/web/sw.js",import.meta.url),"utf8"),{
  self:{location:new URL('https://test.invalid/sw.js'),addEventListener:(name:string,handler:any)=>handlers[name]=handler,clients:{claim:()=>undefined},skipWaiting:()=>undefined},
  caches,URL,Request,Promise,fetch:async()=>new Response('asset'),
 });
 const pending:Promise<unknown>[]=[];handlers.activate({waitUntil:(promise:Promise<unknown>)=>pending.push(promise)});await Promise.all(pending);
 assert.equal(stores.has('unrelated-data'),true);assert.equal(stores.has('tr-shell-v2'),false);
 const responses:Promise<unknown>[]=[];
 for(const v of ['1','2','3','4'])handlers.fetch({request:new Request('https://test.invalid/research-static/vendor/web-app/desktop.js?v='+v),respondWith:(promise:Promise<unknown>)=>responses.push(promise),waitUntil:(promise:Promise<unknown>)=>pending.push(promise)});
 await Promise.all(responses);await Promise.all(pending);
 const current=[...stores.entries()].find(([key])=>key.startsWith('tr-shell-'))![1];
 assert.deepEqual([...current.keys()].map(url=>new URL(url).searchParams.get('v')),['3','4']);
 for(const path of ['/api/session','/auth/login'])handlers.fetch({request:new Request('https://test.invalid'+path),respondWith:()=>assert.fail('private data must not enter the shell cache')});
});
