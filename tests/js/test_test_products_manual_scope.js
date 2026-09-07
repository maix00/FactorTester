const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
global.window = globalThis;
global.document = {createElement: () => ({append() {}, replaceChildren() {}})};
const controls = [];
global.FTTestObjectPicker = {
  lazyLoading: () => false,
  create: (_context, options) => {
    controls.push(options);
    return {element: {}, setItems() {}, setValues() {}, setStatus() {}};
  },
};
global.FTTestFieldRow = {create: () => ({})};
const outer = [{group_ref:'product-group:one'}, {id:'inline:products:two', paths:['Product/_products/B']}];
global.FTStrategyEditorScope = {
  mounted: () => false,
  outerCategoryIDs: () => ['category-one'],
  scope: () => ({source:'outer', items:outer, ready:true}),
};
vm.runInThisContext(fs.readFileSync('server/manager/web/workbench/test-products.js','utf8'));
(async () => {
  const requests = [];
  const state = {kind:'ic', groups:[], groupRefs:[], values:{}};
  FTTestProducts.selectionPanel({t:x=>x, api:async url => {
    const params = new URL(url,'https://example.test').searchParams;
    requests.push(params);
    return {products:[{name:params.get('page'),product_path:'Product/_products/'+params.get('page')}], has_more:params.get('page')==='1'};
  }}, state, () => {}, {groups:()=>[], sourceState:{productSourceMode:'products'}, multi:false});
  const direct = controls.find(item=>item.loadItems);
  assert.equal(direct.multi,true);
  const items = await direct.loadItems('search');
  assert.equal(items.length,2);
  for (const params of requests) {
    assert.deepEqual(params.getAll('group_ref'),['product-group:one']);
    assert.deepEqual(params.getAll('product_path'),['Product/_products/B']);
    assert.deepEqual(params.getAll('category_id'),['category-one']);
  }
  assert.deepEqual(FTTestProducts.projection({group_ref:'product-group:one',paths:['mutable']}),{
    product_path_selection_id:'product-group:one',product_group_template_id:'product-group:one',label:'product-group:one',source_type:'user_product_group_template',
  });
  assert.deepEqual(FTTestProducts.projection({id:'inline:products:two',paths:['Product/_products/B']}).paths,['Product/_products/B']);
  console.log('PASS: manual picker follows outer union/category scope and retrieves every page; group projection retains identity only');
})().catch(error=>{console.error(error);process.exitCode=1;});
