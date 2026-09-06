const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
global.window = global;
const element = () => ({append(){}, replaceChildren(){}, classList:{add(){}}});
global.document = {createElement: element};
global.FTSettingRules = {storageKey:k=>k, setValue:(_m,v,k,_f,x)=>{v[k]=x;}};
global.FTFactorModel = {frozenFactorIdentity:v=>v?.schema_version===2 && v.identity && v.ref ? v:null};
global.FTTestFactorCandidates = {sourceDescription:()=>'', summaryControl:element};
global.FTTestFieldRow = {create:element};
global.FTTestInputState = {detachFactorSet(){}};
let pickerOptions, saved;
global.FTTestObjectPicker = {lazyLoading:()=>false, create(_c,o){pickerOptions=o;return {element:element(),setItems(){},setValues(){}};}};
global.FTStrategyEditorFactorOverlay = {open(_c,_s,onSaved){saved=onSaved;}};
for (const file of ['factor-selection.js','factor-set-selection.js','test-factor-candidate-sources.js']) {
 vm.runInThisContext(fs.readFileSync(`server/manager/web/workbench/${file}`,'utf8'));
}
const context={session:{username:'test'},t:v=>v};
const state={kind:'ic',values:{},factors:[],manifest:{defaults:{
 factor_source_selections:{serialization:{kind:'factor_source_selection_list'}},
 factor_set_selections:{serialization:{kind:'factor_set_selection_list'}},
}}};
// Nested IC/strategy editors use a shared catalog plus their own draft rows.
state.catalogSourceState = {factors: [], savedFactors: []};
FTTestFactorSets.prepare(state);
const factor=(ref)=>({schema_version:2,ref,alias:ref,identity:{},temporary:true});
(async()=>{
 FTTestFactorCandidateSources.panel(context,state);
 pickerOptions.onAddCandidateForType('factor',context,{add(){}});
 saved(factor('factor:v2:one'));
 assert.deepEqual(FTTestFactorCandidateSources.selections(state).map(x=>x.ref),['factor:v2:one']);
 assert.equal(state.factors[0].temporary,true);
 // Remounting the picker must recover the owner-held object and selection.
 FTTestFactorCandidateSources.panel(context,state);
 assert.equal(pickerOptions.items[0].value,'factor:v2:one');
 assert.equal(pickerOptions.items[0].onsite,true);
 assert.deepEqual(pickerOptions.selected,['factor:v2:one']);
 const original=pickerOptions.items[0];
 pickerOptions.onTemporaryCandidateUpdated(original,{},factor('factor:v2:two'));
 assert.deepEqual(FTTestFactorCandidateSources.selections(state).map(x=>x.ref),['factor:v2:two']);
 FTTestFactorCandidateSources.panel(context,state);
 const updated=pickerOptions.items.find(x=>x.value==='factor:v2:two');
 pickerOptions.onTemporaryCandidateRemoved(updated);
 await pickerOptions.onChange([]);
 assert.equal(FTTestFactorCandidateSources.selections(state).length,0);
 assert.equal(state.factors.some(x=>x.ref==='factor:v2:two'),false);
 console.log('temporary candidate owner create/remount/edit/delete passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
