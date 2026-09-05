const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
global.window = global;
for (const file of ['factor-selection.js', 'factor-set-selection.js']) {
  vm.runInThisContext(fs.readFileSync(`server/manager/web/workbench/${file}`, 'utf8'));
}
global.FTSettingRules = {
  storageKey: key => key,
  setValue: (_manifest, values, key, _field, value) => { values[key] = value; },
};
global.FTFactorModel = {frozenFactorIdentity: value => value?.schema_version === 2 && value.identity && value.ref ? value : null};
const state = {kind:'ic', values:{}, manifest:{defaults:{factor_set_selections:{serialization:{
  kind:'factor_set_selection_list', detail_endpoint:'/sets/detail',
}}}}};
FTTestFactorSets.prepare(state);
const item = {target_ref:'factor-set:v2:test', visibility:'server', member_count:8};
const factors = Array.from({length:8}, (_,i)=>({schema_version:2, ref:`factor:v2:${i}`, alias:`F${i}`, identity:{}}));
(async () => {
  const context = {t:v=>v, api:async()=>({success:false,error:'not found'})};
  await assert.rejects(FTTestFactorSets.selectSet(context,state,item), /not found/);
  assert.equal(FTTestFactorSelection.candidates(state).length,0);
  context.api=async()=>({factor_set:{related_references:[],has_more:false}});
  await assert.rejects(FTTestFactorSets.selectSet(context,state,item), /冻结成员/);
  context.api=async()=>({factor_set:{related_references:[...factors.slice(0,7).map(data=>({data})),{data:{bad:true}}],has_more:false}});
  await assert.rejects(FTTestFactorSets.selectSet(context,state,item), /无法解析/);
  assert.equal(FTTestFactorSelection.candidates(state).length,0);
  context.api=async()=>({factor_set:{related_references:factors.map(data=>({data})),has_more:false}});
  await FTTestFactorSets.selectSet(context,state,item);
  assert.equal(FTTestFactorSelection.candidates(state).length,8);
  assert.equal(state.values.factor_set_selections.length,1);
  assert.deepEqual(state.values.factor_candidates[0].factor_set_refs,[item.target_ref]);
  console.log('ok');
})().catch(error=>{console.error(error);process.exitCode=1;});
