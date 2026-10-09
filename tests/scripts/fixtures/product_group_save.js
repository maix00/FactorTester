const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
global.window = global;
global.location = {search:''};
let form, picker, button;
function element(tag='div') {
  const e = {tag, dataset:{}, children:[], listeners:{}, isConnected:true, classList:{add(){}},
    append(...children){this.children.push(...children);},
    replaceChildren(...children){this.children=children;},
    addEventListener(name, handler){this.listeners[name]=handler;},
    querySelector(){return null;}};
  if(tag==='form') form=e;
  return e;
}
global.document={createElement:element};
global.FTUI={loading:()=>element(),empty:()=>element()};
global.FTMultiSelectFilter={create(_c,o){picker=o;return {element:element()};}};
global.FTObjectModeActions={mount(){button=element('button');return [button];}};
global.FTCatalogDetailUI={header(_c,o){const save=o.editing?element('button'):null;if(save)button=save;return {root:element(),save};}};
global.FTProductGroupPathEditor={render(){return {root:element(),paths:()=>['AP.CZC'],dispose(){}};}};
vm.runInThisContext(fs.readFileSync('server/manager/web/catalog/product-group-detail.js','utf8'));
(async()=>{
  for(const overlay of [false,true]) {
    let saved;
    picker = null;
    const context={t:v=>v,session:{username:'test'},content:element(),
      activeNav(){},setHeading(){},testObjectOverlay:overlay,testObjectTemporary:true,
      onSaved:v=>{saved=v;}};
    await FTProductGroupDetail.render(context,'new',{
      sourceOf:()=> 'server',catalogSwitch(){},sourceSummary:()=>element(),
      loadCategories:async()=>({categories:[{id:'day'}]})});
    while(!picker) await new Promise(resolve=>setTimeout(resolve,0));
    picker.onChange(['day']);
    await form.listeners.submit({preventDefault(){}});
    assert.deepEqual(saved.category_ids,['day']);
    assert.deepEqual(saved.paths,['AP.CZC']);
    assert.equal(button.disabled,true);
  }
  console.log('product group standalone and overlay submission passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
