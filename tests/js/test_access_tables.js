const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag) {this.tag=tag;this.children=[];this.dataset={};this.listeners={};this.attributes={};this.classList={add:()=>{}};}
  append(...children) {this._textContent='';this.children.push(...children);}
  replaceChildren(...children) {this._textContent='';this.children=children;}
  get textContent() {return this.children.length ? this.children.map(c=>typeof c==='string'?c:(c?.textContent||'')).join('') : (this._textContent||'');}
  set textContent(value) {this.children=[];this._textContent=String(value??'');}
  setAttribute(k,v) {this.attributes[k]=v;}
  removeAttribute(k) {delete this.attributes[k];}
  addEventListener(k,f) {this.listeners[k]=f;}
  querySelectorAll(tag) {return this.children.flatMap(c=>[...(c.tag===tag?[c]:[]),...c.querySelectorAll(tag)]);}
  createTHead() {const e=new Element('thead');this.append(e);return e;}
  createTBody() {const e=new Element('tbody');this.append(e);return e;}
  insertRow() {const e=new Element('tr');this.append(e);return e;}
  insertCell() {const e=new Element('td');this.append(e);return e;}
  async click() {if(!this.disabled) await (this.onclick || this.listeners.click)?.();}
}
global.window=global;global.Node=Element;global.document={createElement:tag=>new Element(tag)};
global.FTIcons={node:()=>new Element('svg')};
for(const name of ['core/shared-ui','manager/access-control-table','manager/access-control'])vm.runInThisContext(fs.readFileSync('server/manager/web/'+name+'.js','utf8'));
const find=(root,p)=>[root,...root.children.flatMap(c=>find(c,p))].filter(p);
const button=(root,label)=>find(root,e=>e.tag==='button'&&e.attributes['aria-label']===label)[0];
(async()=>{
 const data={users:Array.from({length:24},(_,i)=>({username:'user'+i,active:true})),visitor_allowlist:[]};
 data.users.push({username:'testB',alias:'testB',active:true});
 const writes=[];const ctx={t:x=>x,session:{role:'super_admin'},showNotice:()=>{},api:async(url,init)=>{
  if(init){const payload=JSON.parse(init.body);writes.push([init.method,payload]);data.visitor_allowlist=init.method==='POST'?[{...payload,enabled:true,account_active:true}]:[];}
  return data;
 }};
 const body=new Element('main');await FTManagerAccessControl.show(ctx,body);
 const candidates=find(body,e=>e.className==='manager-access-table')[0];
 assert.equal(find(candidates,e=>e.tag==='tbody')[0].children.length,10);
 await button(candidates,'下一页').click();
 assert.equal(find(candidates,e=>e.tag==='tbody')[0].children[0].children[0].textContent,'user10');
 const search=find(candidates,e=>e.tag==='input')[0];search.value='testB';search.listeners.input();
 assert.equal(find(candidates,e=>e.tag==='tbody')[0].children.length,1);
 await button(candidates,'添加到白名单').click();
 assert.equal(button(candidates,'添加到白名单'),undefined);
 assert.ok(button(candidates,'从白名单移除'));
 assert.equal(find(body,e=>e.className==='manager-access-table').length,1);
 assert.equal(search.value,'testB');
 await button(body,'从白名单移除').click();
 assert.equal(button(candidates,'添加到白名单').disabled,false);
 assert.deepEqual(writes,[['POST',{username:'testB'}],['DELETE',{username:'testB'}]]);
 const ordinary=new Element('main');let calls=0;
 await FTManagerAccessControl.show({...ctx,session:{role:'user'},api:async()=>{calls++;}},ordinary);
 assert.equal(calls,0);assert.equal(find(ordinary,e=>e.tag==='button').length,0);
 console.log('PASS: shared pagination, searchable user add/remove, retained filter and ordinary-user guard');
})().catch(e=>{console.error(e);process.exitCode=1});
