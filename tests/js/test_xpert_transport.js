const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
global.window = global;global.location = {origin:'http://localhost'};
vm.runInThisContext(fs.readFileSync('server/manager/web/profile/xpert-transport.js','utf8'));
(async()=>{
 const ops=[];
 const adapter={endpoint:'/manager',fetch:async(_url,init)=>{
  const q=JSON.parse(init.body);ops.push(q);
  if(q.type==='threads.resume') return new Response('data: '+JSON.stringify({type:'thread.item.replaced',item:{id:'live',type:'assistant_message',content:[{text:'续接消息'}]}})+'\n\n');
  if(q.type==='threads.list') return new Response(JSON.stringify({data:[{id:'a',title:'A'},{id:'b',title:'B'}]}));
  return new Response(JSON.stringify({id:q.params.thread_id||'a',title:'A',items:{data:[],has_more:false}}));
 }};
 const bridge=FTXpertTransport.create(adapter,{runtimeStatus:async()=>({processing_conversation_id:'a',processing_turn_id:'run1'})});
 const request=(path,body,method=body?'POST':'GET')=>FTXpertTransport.fetch(bridge.key,'http://localhost/ft-profile-bridge/'+path,{method,body:body?JSON.stringify(body):undefined});
 assert.equal((await (await request('conversations/search',{where:{threadId:'a'}})).json()).items.length,1);
 await request('conversations/a',{updatedAt:'now'},'PATCH');
 assert.equal(ops.at(-1).type,'threads.get_by_id','SDK metadata refresh must not clear the title');
 await request('conversations/a',{title:'renamed'},'PATCH');
 assert.equal(ops.at(-1).params.title,'renamed');
 assert.equal((await (await request('threads/a/runs')).json())[0].run_id,'run1');
 const live=await request('threads/a/runs/run1/stream');
 assert.match(await live.text(),/续接消息/);
 assert.equal(ops.at(-1).type,'threads.resume');
 assert(!ops.some(q=>q.type==='threads.add_user_message'),'reconnection cannot submit another turn');
 assert.equal((await request('unsupported')).status,400);
 bridge.dispose();await assert.rejects(request('threads/a'),/已关闭/);
 console.log('PASS: scoped Xpert transport lists, renames, resumes and disposes without resubmitting');
})().catch(e=>{console.error(e);process.exitCode=1});
