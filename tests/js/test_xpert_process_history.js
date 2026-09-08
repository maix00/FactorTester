const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
global.window = global; global.location = {origin:'http://localhost'};
vm.runInThisContext(fs.readFileSync('server/manager/web/profile/xpert-transport.js','utf8'));
(async()=>{
 const calls=[]; let output;
 const items=[{id:'u',type:'user_message',content:[{text:'question'}]},
  ...['p1','p2'].map(id=>({id,thread_id:'c',turn_id:'t1',type:'workflow',details_deferred:true,workflow:{tasks:[{title:'command'}]}})),
  {id:'steer',type:'user_message',turn_id:'t1',content:[{text:'again'}]},
  {id:'a1',type:'assistant_message',turn_id:'t1',content:[{text:'ok'}]},
  {id:'a2',type:'assistant_message',turn_id:'t2',content:[{text:'ok'}]}];
 const bridge=FTXpertTransport.create({endpoint:'/api',fetch:async(_,init)=>{
  const q=JSON.parse(init.body);calls.push(q);
  if(q.type==='threads.add_user_message')return new Response(new ReadableStream({start(c){output=c;}}));
  return Response.json({id:'c',items:{data:items},data:[]});
 }},{upload:async f=>({name:f.name,path:'uploads/2026-09-09/'+ 'a'.repeat(32)+'/'+f.name,size_bytes:f.size}),capabilities:async()=>({skills:[{id:'one'}]})});
 const req=(path,body)=>FTXpertTransport.fetch(bridge.key,location.origin+'/ft-profile-bridge/'+path,{method:'POST',body:typeof body?.get==='function'?body:JSON.stringify(body||{})});
 const history=await (await req('conversations/c/messages')).json();
 assert.equal(history.items.length,5);
 assert.equal(history.items[2].role,"human");
 assert.equal(history.items[2].content,"again");
 assert.equal(history.items[3].role,"ai");
 assert.equal(history.items[1].content[0].data.items.length,2);
 assert.equal(history.items.filter(i=>i.content==='ok').length,2,'identical replies in different turns survive');
 assert(!calls.some(q=>q.type==='items.detail'));
 await req('conversations/c/process-details',{after:'cursor'});
 assert.equal(calls.at(-1).params.after,'cursor');
 const form=new FormData();form.append('file',new Blob([new Uint8Array([0,255,12])]),'a.png');
 const file=await(await req('contexts/file',form)).json();assert.equal(file.workspacePath,'uploads/2026-09-09/'+ 'a'.repeat(32)+'/a.png');
 const response=await req('threads/c/runs/stream',{input:{input:'inspect',files:[file]}});
 assert.match(calls.at(-1).params.input.content[0].text,/uploads\/2026-09-09\/[a-f0-9]+\/a.png/);
 const reader=response.body.getReader();
 const emit=e=>output.enqueue(new TextEncoder().encode('data: '+JSON.stringify(e)+'\n\n'));
 emit({type:'thread.item.replaced',item:{id:'temp',type:'assistant_message',content:[{text:'latest'}]}});
 await reader.read();
 emit({type:'thread.item.removed',item_id:'temp'});await reader.read();
 emit({type:'thread.item.done',item:{id:'stable',type:'assistant_message',content:[{text:'latest'}]}});
 const frame=new TextDecoder().decode((await reader.read()).value);
 const value=JSON.parse(frame.split('data: ')[1]);
 assert.equal(value.ft_authoritative,true);
 assert(!value.messages.some(i=>i.id==='temp'));
 assert.equal(value.messages.filter(i=>i.content==='latest').length,1);
 output.close();await reader.read();bridge.dispose();
 console.log('PASS: grouped history, on-demand detail, binary attachment and authoritative final identity');
})().catch(e=>{console.error(e);process.exitCode=1});
// HTTP origins lack randomUUID, but cryptographic getRandomValues is available.
const cryptoDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'crypto');
Object.defineProperty(globalThis, 'crypto', {configurable:true, value:{getRandomValues:require('node:crypto').webcrypto.getRandomValues.bind(require('node:crypto').webcrypto)}});
const insecureBridge = FTXpertTransport.create({});
assert.match(insecureBridge.key,/^[0-9a-f]{32}$/);insecureBridge.dispose();
Object.defineProperty(globalThis, 'crypto', cryptoDescriptor);
