// Real DOM regression: run with the repository's Playwright runtime.
const assert = require('node:assert/strict');
const {chromium, webkit} = require('playwright');
const path = require('node:path');
(async () => {
for (const engine of [chromium, webkit]) {
 const browser = await engine.launch(engine === chromium ? {channel:'chrome'} : {});
 const page = await browser.newPage();
 await page.route('http://report.test/**', route=>route.fulfill({contentType:'text/html',body:'<div id="mount" class="report-mount"></div>'}));
 await page.goto('http://report.test/');
 await page.evaluate(() => {
  window.FTRichText={blocks: text=>document.createTextNode(text),inline:text=>document.createTextNode(text)};
  window.FTIcons={node:()=>document.createElement('i'),section:()=>''};
  window.FTUI={empty:text=>document.createTextNode(text),loading:text=>document.createTextNode(text)};
  window.FTReportChapterRail={setup:()=>({refresh(){},cleanup(){}})};
 });
 for (const file of ['tree','chapter-cache','lazy-runtime','component-view','report-renderer']) {
  await page.addScriptTag({path:path.resolve(`server/manager/web/report/${file}.js`)});
 }
 const result = await page.evaluate(async () => {
  const c=(id,parent,body='',kind='entry')=>({component_id:id,parent_id:parent,kind,body,title:kind==='section'?id:''});
  const base={components:[c('chapter',null,'','chapter'),c('a','chapter','unchanged'),c('s','chapter','','section'),c('b','s','before')]};
  const mount=document.querySelector('#mount');
  const renderer=FTReportRenderer.render(base,mount,{t:x=>x,lazyRendering:false,suppressAutoScroll:true});
  const query=id=>mount.querySelector(`[data-report-component-id="${id}"]`);
  const article=mount.firstElementChild, a=query('a'), s=query('s'), b=query('b');
  await renderer.update({components:[...base.components.slice(0,3),c('b','s','after'),c('new','s','added')]});
  const checks=[article===mount.firstElementChild,a===query('a'),s===query('s'),b!==query('b'),query('b').textContent==='after',!!query('new')];
  // Delete and move, preserving unaffected leaf DOM.
  await renderer.update({components:[base.components[0],base.components[2],c('new','chapter','added'),base.components[1]]});
  checks.push(!query('b'),query('new').parentElement===a.parentElement,query('a')===a,
    [...a.parentElement.children].map(n=>n.dataset.reportComponentId).join(',')==='s,new,a');
  // Closed nodes must expand with the latest children, not their initial snapshot.
  query('s').querySelector('details').open=false;
  await renderer.update({components:[base.components[0],base.components[2],c('late','s','latest')]});
  query('s').querySelector('details').open=true;
  await new Promise(r=>setTimeout(r,30));
  checks.push(query('late')?.textContent==='latest');
  // Metadata-only loading: payload revisions distinguish edits.
  let payload='one';
  const index={chapters:[{component_id:'chapter',title:'chapter'}]};
  let snapshot={components:[c('chapter',null,'','chapter'),{...c('leaf','chapter'),content_available:true,content_revision:'1'}],content_lazy:true};
  let delayed;
  const context={t:x=>x,lazyRendering:false,suppressAutoScroll:true,
   loadChapter:async()=>structuredClone(snapshot),loadComponent:async()=>({...c('leaf','chapter',payload)}),componentContentLazy:()=>true};
  const r=FTReportRenderer.render(index,mount,context);
  await new Promise(r=>setTimeout(r,20));
  const stableArticle=mount.firstElementChild;
  payload='two';snapshot.components[1].content_revision='2';
  await r.update(index); await new Promise(r=>setTimeout(r,20));
  checks.push(mount.textContent.includes('two'),mount.firstElementChild===stableArticle);
  // A newer update wins over an older delayed chapter response.
  let calls=0;
  const asyncContext={t:x=>x,lazyRendering:false,suppressAutoScroll:true,loadChapter:()=>{
   if(++calls===2)return new Promise(resolve=>{delayed=resolve});
   return Promise.resolve({components:[c('chapter',null,'','chapter'),c('leaf','chapter',calls===1?'initial':'newest')]});
  }};
  const race=FTReportRenderer.render(index,mount,asyncContext);
  await new Promise(r=>setTimeout(r,20));
  const old=race.update(index);await new Promise(r=>setTimeout(r,0));
  await race.update(index);delayed({components:[c('chapter',null,'','chapter'),c('leaf','chapter','stale')]});await old;
  checks.push(mount.textContent.includes('newest')&&!mount.textContent.includes('stale'));
  return checks;
 });
 await page.addScriptTag({path:path.resolve('server/manager/web/research/report-settings.js')});
 await page.addStyleTag({path:path.resolve('server/manager/web/styles/report.css')});
 const reading = await page.evaluate(async()=>{
  FTUI.iconButton=(context,icon,label,click)=>{const b=document.createElement('button');b.textContent=label;b.onclick=click;return b;};
  const context={t:x=>x,session:{username:'reader'},api:()=>{throw new Error('read-only settings must not request owner permissions');}};
  const article=document.querySelector('article');
  await FTResearchReportSettings.open(context,{access:{can_manage:false}});
  const select=document.querySelector('dialog select');select.value='24';select.dispatchEvent(new Event('change'));
  const resized=getComputedStyle(article).fontSize==='24px' && article===document.querySelector('article');
  document.querySelector('dialog').close();
  FTResearchReportSettings.applyReading({session:{username:'other'}});
  const isolated=getComputedStyle(article).fontSize==='16px';
  FTResearchReportSettings.applyReading(context);
  return resized && isolated && getComputedStyle(article).fontSize==='24px';
 });
 assert(reading,'reader font applies without reload, persists, and is user scoped');
 assert(result.every(Boolean),`${engine.name()} checks: ${JSON.stringify(result)}`);
 console.log(`PASS ${engine.name()}: stable DOM, edits, add/delete/move, closed sections, payload revisions, out-of-order responses`);
 await browser.close();
}
})().catch(error=>{console.error(error);process.exitCode=1});
