const assert = require("node:assert/strict");
const fs = require("node:fs"); const vm = require("node:vm");
class E { constructor(tag){this.tagName=tag;this.children=[];this.value="";this.className="";} append(...x){this.children.push(...x)} addEventListener(){} }
global.window={}; global.document={createElement:t=>new E(t)}; global.structuredClone=x=>JSON.parse(JSON.stringify(x));
global.FTICConfigurationGroupModel={find:()=>null}; window.FTICConfigurationGroupModel=global.FTICConfigurationGroupModel;
global.FTStrategyEditorScope={
  scope:()=>({items:[],required:true,ready:false,source:"outer"}),
  validate:()=>[{message:"outer selection is empty"}],
}; window.FTStrategyEditorScope=global.FTStrategyEditorScope;
global.FTTestFactorCandidateSources={candidatePicker:()=>new E("picker"),innerPanel:()=>new E("factor")};
global.FTTestObjectPicker={lazyLoading:()=>false};
global.FTTestFieldRow={create:(label,control,help)=>{const row=new E("field");row.label=label;row.help=help;row.append(control);return row;}};
let productOptions;
global.FTTestProducts={groupID:x=>x.id,selectionPanel:(_c,_s,_r,o)=>{productOptions=o;return new E("products")}}; window.FTTestProducts=global.FTTestProducts;
let tabOptions; global.FTStrategyEditorTabs={create:o=>{tabOptions=o;return Object.assign(new E("tabs"),{refreshChips(){},value:()=>({mountedTabs:[]})});}}; window.FTStrategyEditorTabs=global.FTStrategyEditorTabs;
vm.runInThisContext(fs.readFileSync(process.argv[2],"utf8"));
const manifest={defaults:{return_price_basis:{value:"next_open_to_open_adjusted",value_descriptor:{options:[{value:"next_open_to_open_adjusted",label:"Open"},{value:"next_close_to_close_adjusted",label:"Close"}]}}}};
const state={
  manifest,values:{ic_lags:[2]},
  factors:[{factor_ref:"factor:v1:roc"}],
  groups:[{id:"product-group:day",name:"CNFuturesDay"}],
};
const form=window.FTICConfigurationGroupForm.render({t:x=>x,button:()=>new E("button")},state,{mode:"create"},()=>{});
const structure=tabOptions.renderStructure();
const selects=[]; const walk=x=>{if(x?.tagName==="select")selects.push(x);for(const c of x?.children||[])walk(c)}; walk(structure);
assert.equal(selects.length>=2,true);
const basis=selects.at(-1); assert.deepEqual(basis.children.map(x=>x.value),["next_open_to_open_adjusted","next_close_to_close_adjusted"]);
const delay=tabOptions.renderOverrides({tab:{key:"delay",field:"ic_lags",label:"Delay"}}); assert.ok(delay,"registered Delay renders independently");
const unrelated=tabOptions.renderOverrides({tab:{key:"category",field:"productMask"}}); assert.equal(unrelated.children.length,0,"backtest-only blank tab has no IC form field");
tabOptions.renderProduct();
assert.deepEqual(productOptions.groups,state.groups,"group-owned product picker must not be emptied by the legacy outer product tab");
assert.equal(productOptions.constrain,false,"group-owned picker must bypass legacy outer candidate constraints");
assert.equal(form.tagName,"form"); console.log("ok");
