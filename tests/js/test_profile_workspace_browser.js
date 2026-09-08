const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = [], timers = new Map(), adapters = new Map();
class Node {
  constructor(tag) { this.tagName = tag; this.children = []; this.events = {}; this.isConnected = true; this.classList = {add(){}}; nodes.push(this); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(k,v) { this[k] = v; }
  addEventListener(k,v) { this.events[k] = v; }
  click() { this.events.click?.({stopPropagation(){}}); this.onclick?.(); }
  insertRow() { const n = new Node('tr'); this.append(n); return n; }
  insertCell() { const n = new Node('td'); this.append(n); return n; }
}
global.document = {createElement: tag => new Node(tag), hidden: false};
global.window = {FTIcons: {node: symbol => Object.assign(new Node('svg'), {symbol})}, confirm: () => true};
global.FTUI = {loading: t => t, empty: (...t) => t.join(' '), table: () => { const n = new Node('table'); return {body:n,shell:n}; }};
FTUI.iconButton = (context,symbol,label,action) => {
 const b = new Node('button'); b.title=label; b.append(window.FTIcons.node(symbol));
 b.addEventListener('click',action); return b;
};
global.setInterval = fn => { const id = timers.size + 1; timers.set(id, fn); return id; };
global.clearInterval = id => timers.delete(id);
vm.runInThisContext(fs.readFileSync('server/manager/web/profile/workspace-browser.js', 'utf8'));
const tick = () => new Promise(resolve => setImmediate(resolve));
(async () => {
 const calls = [], notices = []; let current = true;
 const entries = [{name:'uploads', path:'uploads', kind:'directory'}];
 const context = {t:x=>x, isRouteCurrent:()=>current, showNotice:(...x)=>notices.push(x),
  pageState:{register:(k,v)=>adapters.set(k,v)}, api:async (url,options={})=>{
   calls.push([url,options]); const q=new URL(url,'https://test').searchParams;
   if(options.method==='POST') return {saved:true,path:`uploads/${q.get('filename')}`};
   return {path:q.get('path')||'',entries:structuredClone(entries)};
  }};
 const root=window.FTProfileWorkspace.render(context,{profile_id:'self',runtime:{runtime_kind:'server'}});
 await tick();
 const buttons=()=>nodes.filter(n=>n.tagName==='button');
 const upload=buttons().find(n=>n.title==='上传到 uploads');
 upload.click(); await tick();
 const input=nodes.find(n=>n.tagName==='input');
 assert(root.children.includes(input),'file picker remains mounted while native dialog is open');
 assert.equal(input.hidden,true);
 assert.equal(input.multiple,true);
 // A second browser using the same context must not steal the upload refresh.
 const other=window.FTProfileWorkspace.render(context,{profile_id:'other',runtime:{runtime_kind:'server'}});
 await tick();
 input.files=[{name:'截图.png',size:100}]; await input.events.change(); await tick();
 assert(calls.at(-1)[0].includes('profile_id=self&path=uploads'));
 assert.equal(calls.find(([,o])=>o.method==='POST')[1].body,input.files[0]);
 assert(notices.some(n=>n[0].includes('uploads/')));
 assert.equal(input.value,'','reset permits reselecting the same file');
 assert.equal(input.disabled,false);
 const beforeCancel=calls.filter(([,o])=>o.method==='POST').length;
 input.files=[]; await input.events.change();
 assert.equal(calls.filter(([,o])=>o.method==='POST').length,beforeCancel);
 assert(buttons().some(n=>n.title==='返回上级'&&n.children[0].symbol==='chevron.left'));
 assert(buttons().some(n=>n.title==='打开'&&n.children[0].symbol==='folder'));
 const count=nodes.filter(n=>n.tagName==='table').length;
 await timers.get(1)(); await tick();
 assert.equal(nodes.filter(n=>n.tagName==='table').length,count,'unchanged directory does not redraw');
 entries.push({name:'new.png',path:'uploads/new.png',kind:'file',size_bytes:100});
 await timers.get(1)(); await tick();
 assert(nodes.some(n=>n.textContent==='new.png'),'external writes appear on next refresh');
 current=false; const requests=calls.length; await timers.get(1)(); assert.equal(calls.length,requests);
 current=true; root.isConnected=false; await timers.get(1)(); assert.equal(calls.length,requests);
 root.isConnected=true; await timers.get(1)(); await tick(); assert(calls.length>requests);
 adapters.get('profile-workspace:self').dispose(); assert(!timers.has(1));
 adapters.get('profile-workspace:other').dispose(); assert.equal(timers.size,0);
 console.log('PASS workspace binary upload, instance refresh, directory navigation, unchanged listing and disposal');
})().catch(e=>{console.error(e);process.exitCode=1});
