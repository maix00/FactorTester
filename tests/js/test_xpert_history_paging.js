const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
global.window = global; global.location = {origin:'http://localhost'};
vm.runInThisContext(fs.readFileSync('server/manager/web/profile/xpert-transport.js','utf8'));
(async()=>{
 const calls=[];
 const item=id=>({id,type:'assistant_message',content:[{text:id}]});
 const bridge=FTXpertTransport.create({endpoint:'/api',fetch:async(_,init)=>{
  const q=JSON.parse(init.body); calls.push(q.type);
  return Response.json(q.type==='threads.get_by_id'?{id:'c',items:{data:[item('recent')],after:'cursor1',has_more:true}}:{data:[item('older')],after:'cursor2',has_more:true});
 }});
 const request=offset=>FTXpertTransport.fetch(bridge.key,location.origin+'/ft-profile-bridge/conversations/c/messages',{method:'POST',body:JSON.stringify({offset,limit:50})}).then(r=>r.json());
 const recent=await request(0);assert.equal(recent.items.length,1);assert.deepEqual(calls,['threads.get_by_id']);assert(recent.total>1);
 const older=await request(1);assert.equal(older.items.length,1);assert.equal(older.items[0].content,'older');assert.deepEqual(calls,['threads.get_by_id','items.list']);
 console.log('PASS: initial history and explicit older-page loading are bounded');
})().catch(e=>{console.error(e);process.exitCode=1});
