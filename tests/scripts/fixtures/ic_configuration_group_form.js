const assert = require("node:assert/strict");
const fs = require("node:fs"); const vm = require("node:vm");
class E { constructor(tag){this.tagName=tag;this.children=[];this.value="";this.className="";} append(...x){this.children.push(...x)} addEventListener(){} }
global.window={}; global.document={createElement:t=>new E(t)}; global.structuredClone=x=>JSON.parse(JSON.stringify(x));
global.FTICConfigurationGroupModel={find:()=>null}; window.FTICConfigurationGroupModel=global.FTICConfigurationGroupModel;
let factorScope={items:[],required:true,ready:false,source:"outer"};
let productScope={items:[],required:true,ready:false,source:"outer"};
global.FTStrategyEditorScope={
  scope:(_state,kind)=>kind==="factor"?factorScope:productScope,
  scopedField:()=>({allow_inline_create_when_outer_unmounted:true}),
  inlineCreateAllowed:(_state,_field,scope)=>scope.source!=="outer",
  validate:()=>[{message:"outer selection is empty"}],
}; window.FTStrategyEditorScope=global.FTStrategyEditorScope;
let factorOptions; global.FTTestFactorCandidateSources={candidatePicker:(_c,_s,o)=>{factorOptions=o;return new E("picker")},innerPanel:()=>new E("factor")};
global.FTTestFactorCandidateSources.scopedSourceState=(_state,_owner,initial)=>({
  values:{factor_candidates:(initial.factor_candidate_refs||[]).map(ref=>({ref}))},
});
global.FTTestFactorCandidateSources.scopedSourceSnapshot=local=>({
  factor_candidate_refs:(local.values.factor_candidates||[]).map(item=>item.ref),
  factor_candidates:local.values.factor_candidates||[],
  factor_source_selections:[],factor_set_selections:[],
});
global.FTTestFactorCandidateSources.scopedSourcePanel=()=>new E("factor-sources");
global.FTTestObjectPicker={lazyLoading:()=>false};
global.FTTestFieldRow={create:(label,control,help)=>{const row=new E("field");row.label=label;row.help=help;row.append(control);return row;}};
let productOptions;
global.FTTestProducts={groupID:x=>x.id,selectionPanel:(_c,_s,_r,o)=>{productOptions=o;return new E("products")}}; window.FTTestProducts=global.FTTestProducts;
let tabOptions; global.FTStrategyEditorTabs={create:o=>{tabOptions=o;return Object.assign(new E("tabs"),{refreshChips(){},value:()=>({mountedTabs:[]})});}}; window.FTStrategyEditorTabs=global.FTStrategyEditorTabs;
let chipSourceItem;
global.FTTestContentAdapters={chipSources:(_state,item)=>{chipSourceItem=item;return {}}};
window.FTTestContentAdapters=global.FTTestContentAdapters;
vm.runInThisContext(fs.readFileSync(process.argv[2],"utf8"));
const manifest={defaults:{return_price_basis:{value:"next_open_to_open_adjusted",value_descriptor:{options:[{value:"next_open_to_open_adjusted",label:"Open"},{value:"next_close_to_close_adjusted",label:"Close"}]}}}};
const state={
  manifest,values:{ic_lags:[2]},
  factors:[{ref:"factor:v2:roc"}],
  groups:[{id:"product-group:day",name:"CNFuturesDay"}],
};
const form=window.FTICConfigurationGroupForm.render({t:x=>x,button:()=>new E("button")},state,{mode:"create"},()=>{});
assert.deepEqual(factorOptions.items,[],"an empty mounted outer factor scope blocks IC candidates");
assert.equal(factorOptions.canCreate,false,"a blocked outer factor scope blocks inline creation");
tabOptions.renderProduct();
assert.deepEqual(productOptions.groups,[],"an empty mounted outer product scope blocks IC candidates");
assert.equal(productOptions.canCreate,false,"a blocked outer product scope blocks inline creation");
productScope={items:[{id:"product-group:loaded",name:"Loaded"}],required:true,ready:true,source:"outer"};
tabOptions.renderProduct();
assert.deepEqual(productOptions.groups,productScope.items,
  "a lazily rendered IC product tab must read the latest product-group scope");
factorScope={items:[{ref:"factor:v2:outer"}],required:true,ready:true,source:"outer"};
productScope={items:[{id:"product-group:outer",name:"Outer"}],required:true,ready:true,source:"outer"};
window.FTICConfigurationGroupForm.render({t:x=>x,button:()=>new E("button")},state,{mode:"create"},()=>{});
assert.deepEqual(factorOptions.items,factorScope.items,"IC must reuse the shared outer factor scope");
tabOptions.renderProduct();
assert.deepEqual(productOptions.groups,productScope.items,"IC must reuse the shared outer product scope");
assert.equal(productOptions.canCreate,false,"outer product pools cannot be widened inline");
factorScope={items:state.factors,required:false,ready:true,source:"visible"};
productScope={items:state.groups,required:false,ready:true,source:"visible"};
window.FTICConfigurationGroupForm.render({t:x=>x,button:()=>new E("button")},state,{mode:"create"},()=>{});
assert.deepEqual(factorOptions.items,state.factors,"without an outer factor tab IC uses the visible catalog");
assert.equal(factorOptions.canCreate,true,"an unmounted outer scope permits local inline creation");
const structure=tabOptions.renderStructure();
const selects=[]; const walk=x=>{if(x?.tagName==="select")selects.push(x);for(const c of x?.children||[])walk(c)}; walk(structure);
assert.equal(selects.length>=2,true);
const basis=selects.at(-1); assert.deepEqual(basis.children.map(x=>x.value),["next_open_to_open_adjusted","next_close_to_close_adjusted"]);
const delay=tabOptions.renderOverrides({tab:{key:"delay",field:"ic_lags",label:"Delay"}}); assert.ok(delay,"registered Delay renders independently");
const unrelated=tabOptions.renderOverrides({tab:{key:"category",field:"productMask"}}); assert.equal(unrelated.children.length,0,"backtest-only blank tab has no IC form field");
tabOptions.renderProduct();
assert.deepEqual(productOptions.groups,state.groups,"without an outer product tab IC uses the visible catalog");
assert.equal(productOptions.constrain,false,"group-owned picker must bypass legacy outer candidate constraints");
assert.equal(productOptions.canCreate,true,"an unmounted product scope permits local inline creation");
const editor={mode:"create"};
window.FTICConfigurationGroupForm.render({t:x=>x,button:()=>new E("button")},state,editor,()=>{});
tabOptions.renderProduct();
productOptions.onChange(["product-group:day"]);
factorOptions.onChange(["factor:v2:roc"]);
assert.equal(editor.draft.product_scope_ref,"product-group:day","group selections survive tab refresh/re-render");
assert.equal(editor.draft.factor_ref,"factor:v2:roc","factor selections survive tab refresh/re-render");
const chipValues=tabOptions.chipValues();
assert.deepEqual(chipValues.ic_lags,[2],"IC delay remains available to the shared chip renderer");
tabOptions.chipSources();
assert.deepEqual(chipSourceItem.factor_candidate_refs,["factor:v2:roc"],"IC chip sources use the selected factor reference");
assert.equal(chipSourceItem.product_path_selection_id,"product-group:day","IC chip sources use the selected product group");
assert.equal(form.tagName,"form"); console.log("ok");
