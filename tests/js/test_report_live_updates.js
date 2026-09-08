const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const listeners = new Map();
let scheduled;
let cleared = false;
global.window = {addEventListener: (name, fn) => listeners.set(name, fn),
 removeEventListener: name => listeners.delete(name)};
global.document = {hidden: false, addEventListener: (name, fn) => listeners.set(name, fn),
 removeEventListener: name => listeners.delete(name)};
global.setTimeout = fn => { scheduled = fn; return 1; };
global.clearTimeout = () => { cleared = true; };
vm.runInThisContext(fs.readFileSync('server/manager/web/report/source.js', 'utf8'));
(async () => {
 let index = {title:'report', generation: 1, chapters: [{id: 'chapter-1'}]};
 let current = true;
 const paths=[]; const changes=[];
 const source=window.FTReportSource.create('server:sample',async path=>{
   paths.push(path);return structuredClone(index);
 });
 await source.load();
 const stop=source.watch({isCurrent:()=>current,onChange:next=>changes.push(next)});
 await scheduled();
 assert.equal(changes.length,0,'unchanged index does not redraw');
 index={...index,generation:2,chapters:[{id:'chapter-1'},{id:'chapter-2'}]};
 current=false; await scheduled(); assert.equal(changes.length,0,'parked reports do not redraw');
 current=true; await listeners.get('focus')();
 assert.equal(changes.length,1);assert.equal(changes[0].chapters.length,2);
 assert(paths.every(path=>path.endsWith('/index')),'refresh never prefetches chapter bodies');
 stop();assert(cleared);assert.equal(listeners.size,0);
 await scheduled();assert.equal(changes.length,1,'disposed watcher cannot update the page');
 const foreignPaths=[];
 const foreign=window.FTReportSource.create('server:self:pkg:main',async path=>{
   foreignPaths.push(path);return {title:'shared',chapters:[],components:[]};
 },{ownerRef:'GTHT@owner@1'});
 await foreign.load(); await foreign.loadChapter('c'); await foreign.loadComponent('c','x');
 for(const path of [...foreignPaths,foreign.reportAssetPath('asset'),foreign.localResourcePath('resource')]) {
   assert.equal(new URL(path,'https://test').searchParams.get('target_ref'),'GTHT@owner@1');
 }
 console.log('PASS: report index updates render only changed active reports and clean up on disposal');
})().catch(error=>{console.error(error);process.exitCode=1});
