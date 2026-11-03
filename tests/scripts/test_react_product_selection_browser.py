"""Shared selection flows in an isolated browser fixture, never a live Manager.

Browser plugin not available. Uses repository GTHT Playwright + installed Chrome.
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import subprocess
import threading

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'web/app'


@pytest.fixture
def selection_browser(tmp_path):
    imports = {name: json.dumps(str(APP / path)) for name, path in {
        'REACT': 'node_modules/react/index.js', 'DOM': 'node_modules/react-dom/client.js',
        'GROUP': 'src/components/product-group-editor.tsx', 'CATEGORY': 'src/components/category-editor.tsx',
        'INPUTS': 'src/configuration/test-inputs.tsx', 'EXECUTION': 'src/configuration/execution-target.tsx',
        'INSTANCE': 'src/page-instance.ts',
        'I18N': 'src/i18n.ts', 'CSS': 'src/shell.css',
    }.items()}
    source = '''
import React,{useState} from REACT;import {createRoot} from DOM;import {ConfigProvider,theme} from 'antd';
import {ProductGroupEditor} from GROUP;import {CategoryEditor} from CATEGORY;import {TestInputs} from INPUTS;import {ExecutionTargetPicker} from EXECUTION;
import {PageInstanceProvider} from INSTANCE;import I18N;import CSS;
window.calls=[];window.saved=[];window.draft='';window.errors=[];
const mode=new URLSearchParams(location.search).get('mode')||'group';
const dark=new URLSearchParams(location.search).get('theme')==='dark';if(dark){document.body.style.background='#141414';document.body.style.color='#eee';}
const install=(node,id)=>({authority:'manager-a',owner:'platform',node_id:node,installation_id:id,bundle_id:'Local',bundle_version:'1',bundle_fingerprint:'sha256:'+id.repeat(64).slice(0,64)});
const origins=[{manager_id:'manager-a',installation:install('node-a','A'),member_id:'minute',source_product_ref:'external-A'},
 {manager_id:'manager-a',installation:install('node-b','B'),member_id:'minute',source_product_ref:'external-B'}];
window.fetch=async(url,options={})=>{const u=new URL(url,location.origin),method=options.method||'GET';window.calls.push({path:u.pathname,query:u.search,method});
 let body={};
 if(method==='POST'||method==='PUT'){const value=JSON.parse(options.body);window.saved.push({path:u.pathname,body:value});body={group:{...value,group_ref:'product-group:new'},category:value};}
 else if(u.pathname.endsWith('/product-groups'))body={groups:[{group_ref:'product-group:seed',name:'Existing group'}]};
 else if(u.pathname.endsWith('/categories'))body={categories:[{id:'cat',alias:'Category'}]};
 else if(u.pathname.endsWith('/tree'))body={server_id:'manager-a',tree:[{key:'Product/Test',title:'Test products',folder:true,lazy:true,checkbox:true},{key:'Product/Other',title:'Other products',folder:true,lazy:true,checkbox:true},
 {key:'Product/Test/ProductCategory/cat/Renamed',selection_path:'Product/Test/ProductCategory/cat/cat_1',title:'Renamed category label',folder:true,lazy:true,checkbox:true},
 {key:'Product/Broad',title:'Broad products',folder:true,checkbox:true,children:[{key:'Product/Broad/Sub',title:'Broad subset',folder:true,lazy:true,checkbox:true}]}]};
 else if(u.pathname.endsWith('/contract-tree')){const page=Number(u.searchParams.get('page'))||1,query=u.searchParams.get('query');
  if(query==='slow')await new Promise(resolve=>setTimeout(resolve,700));
  const ids=query?[query==='slow'?666:777]:Array.from({length:50},(_,i)=>(page-1)*50+i);
  body={server_id:'manager-a',nodes:ids.map(id=>({key:'Product/Test/_products/P'+id,product_path:'Product/Test/_products/P'+id,title:'P'+id,product_name:'P'+id,source_ids:['bundle-a/minute','bundle-b/day'],source_bindings:origins})),page,total:query?1:100000,has_more:!query};}
 else if(u.pathname.endsWith('/network-info'))body={server_id:'manager-a'};
 else if(u.pathname.endsWith('/execution-targets'))body={targets:['node-a','node-b'].map(node=>({route_id:node,online:true,target:{manager_id:'manager-a',node_id:node,service_id:'service',deployment_ref:'image',test_types:['backtest']},offers:[{product_ref:'product:T',source_ref:node+'-minute',installation:install(node,node==='node-a'?'A':'B')}]}))};
 return new Response(JSON.stringify(body),{headers:{'Content-Type':'application/json'}});
};
function Demo(){const [text,setText]=useState(JSON.stringify({shared:{factors:[]},analyses:{ic:{configuration_groups:[{config_group_id:'ic-1',product_scope_ref:'product-group:seed',factor_ref:'factor:old'}]}}}));
 const [choice,setChoice]=useState({mode:'auto',manager_id:'manager-a',bundles:[],resolved:{target:{manager_id:'manager-a',node_id:'node-a'},inputs:[{offer:{source_ref:'node-a-minute',installation:install('node-a','A')}},{offer:{source_ref:'node-a-day',installation:install('node-a','C')}}]}});
 window.draft=text;
 return <ConfigProvider theme={{algorithm:dark?theme.darkAlgorithm:theme.defaultAlgorithm}}><PageInstanceProvider value={{id:'demo',pageId:'products',mobile:false,args:{},open:()=>{}}}>
 <main style={{maxWidth:900,margin:'20px auto',padding:16}}>{mode==='category'?<CategoryEditor category={{id:'cat',name:'Category',items:Array.from({length:7},(_,i)=>({label:'Entry '+(i+1),label_id:'cat_'+(i+1),paths:['Historical/Entry'+i]}))}} onSaved={()=>{}} onDeleted={()=>{}} onCancel={()=>{}}/>:
 mode==='config'?<TestInputs analysis='ic' text={text} onChange={setText}/>:mode==='execution'?<ExecutionTargetPicker value={choice} onChange={setChoice} onCapabilities={()=>{}} onRefresh={()=>{}} resolving={false} error='' disabled={false} initialize={false}/>:<ProductGroupEditor group={{group_ref:'product-group:old',name:'Group',category_ids:['cat'],paths:['Historical/Unavailable']}} onSaved={()=>{}} onDeleted={()=>{}} onCancel={()=>{}}/>}</main>
 </PageInstanceProvider></ConfigProvider>;
}createRoot(document.getElementById('root')).render(<Demo/>);
'''
    for name, path in imports.items():
        source = source.replace(name, path)
    # Keep temporary source outside the repository; resolve bare antd explicitly.
    harness = tmp_path / 'harness.tsx'
    source = source.replace("from 'antd'", 'from ' + json.dumps(str(APP / 'node_modules/antd/es/index.js')))
    harness.write_text(source)
    subprocess.run([str(APP / 'node_modules/.bin/esbuild'), str(harness), '--bundle', '--format=iife',
                    f'--outfile={tmp_path / "harness.js"}'], cwd=APP, check=True, capture_output=True)
    (tmp_path / 'index.html').write_text('<title>Product selection QA</title><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="harness.css"><div id="root"></div><script src="harness.js"></script>')
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        try:
            yield browser, f'http://127.0.0.1:{server.server_port}/index.html', tmp_path
        finally:
            browser.close(); server.shutdown(); server.server_close(); thread.join(timeout=5)
            for name in ('harness.tsx', 'harness.js', 'harness.css', 'index.html'):
                (tmp_path / name).unlink(missing_ok=True)


def checkbox(page, title):
    return page.get_by_text(title, exact=True).locator('xpath=ancestor::div[contains(@class,"ant-tree-treenode")][1]').locator('.ant-tree-checkbox')


def rules(page):
    summary = page.get_by_text('Advanced path editor', exact=True)
    summary.click()
    value = set(page.locator('textarea[aria-label="Product paths"]').input_value().splitlines())
    summary.click()
    return value


@pytest.mark.parametrize('width,theme_name', [(1100,'light'), (390,'light'), (1100,'dark')])
def test_group_multi_path_paging_search_refresh_and_save(selection_browser, width, theme_name):
    browser, url, tmp_path = selection_browser
    page = browser.new_page(viewport={'width': width, 'height': 900}); page.set_default_timeout(10000)
    errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(url + '?theme=' + theme_name)
    checkbox(page, 'Test products').click()
    assert rules(page) == {'Historical/Unavailable', 'Product/Test'}
    assert not page.evaluate("window.calls.some(x=>x.path.endsWith('/contract-tree'))")
    page.get_by_text('Test products', exact=True).locator('xpath=ancestor::div[contains(@class,"ant-tree-treenode")][1]').locator('.ant-tree-switcher').click()
    page.get_by_text('P0', exact=True).wait_for()
    assert 'ant-tree-checkbox-checked' in checkbox(page, 'P0').get_attribute('class')
    checkbox(page, 'P0').click()
    assert '-Product/Test/_products/P0' in rules(page)
    page.locator('.ant-tree-list-holder').evaluate('node=>node.scrollTop=node.scrollHeight')
    page.locator('.tr-product-tree-pager .ant-pagination-next').click()
    page.wait_for_function("window.calls.some(x=>x.query.includes('page=2'))")
    page.locator('.ant-tree-list-holder').evaluate('node=>node.scrollTop=0')
    page.get_by_text('P50', exact=True).wait_for()
    assert page.get_by_text('P0', exact=True).count() == 0
    assert '-Product/Test/_products/P0' in rules(page)
    page.get_by_text('Test products', exact=True).locator('xpath=ancestor::div[contains(@class,"ant-tree-treenode")][1]').locator('.ant-tree-switcher').click()
    checkbox(page, 'Other products').click()
    assert 'Product/Other' in rules(page)
    page.get_by_label('Search the entire product catalog', exact=True).fill('needle')
    page.get_by_text('P777', exact=True).wait_for()
    checkbox(page, 'P777').click()
    assert '-Product/Test/_products/P777' in rules(page)
    page.get_by_label('View sources').first.hover()
    page.get_by_role('tooltip').get_by_text('node-b', exact=False).wait_for()
    assert 'node-a' in page.get_by_role('tooltip').inner_text()
    # An ignored AbortSignal in the fixture must still not let an old response win.
    search = page.get_by_label('Search the entire product catalog', exact=True)
    search.fill('slow'); page.wait_for_function("window.calls.some(x=>x.query.includes('query=slow'))")
    search.fill('new'); page.get_by_text('P777', exact=True).wait_for()
    page.wait_for_timeout(750)
    assert page.get_by_text('P666', exact=True).count() == 0
    search.fill(''); page.get_by_text('Test products', exact=True).wait_for()
    checkbox(page, 'Renamed category label').click()
    assert 'Product/Test/ProductCategory/cat/cat_1' in rules(page) or 'Product/Test' in rules(page)
    before = rules(page)
    page.get_by_role('button', name='Refresh product catalog', exact=True).click()
    page.wait_for_function("window.calls.some(x=>x.query.includes('refresh=1'))")
    page.get_by_text('Test products', exact=True).wait_for()
    assert rules(page) == before
    assert page.locator('.ant-tree-treenode').count() < 80
    page.get_by_role('button', name='Save', exact=True).click()
    page.wait_for_function('window.saved.length===1')
    saved = page.evaluate('window.saved[0].body')
    assert set(saved['paths']) == before
    assert saved['category_ids'] == ['cat']
    assert not {'node_id','source_ref','installation_id'} & saved.keys()
    page.screenshot(path=str(tmp_path / f'shared-selection-{width}-{theme_name}.png'), full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    assert not errors
    page.close()


def test_category_uses_one_lazy_selector_and_preserves_other_entries(selection_browser):
    browser, url, _ = selection_browser
    page = browser.new_page(); page.set_default_timeout(10000); page.goto(url + '?mode=category')
    page.get_by_role('button', name='Choose products or paths', exact=True).first.wait_for()
    assert not page.evaluate("window.calls.some(x=>x.path.endsWith('/tree'))")
    page.get_by_role('button', name='Choose products or paths', exact=True).first.click()
    checkbox(page, 'Test products').click()
    assert not page.evaluate("window.calls.some(x=>x.path.endsWith('/contract-tree'))")
    page.get_by_text('Test products', exact=True).locator('xpath=ancestor::div[contains(@class,"ant-tree-treenode")][1]').locator('.ant-tree-switcher').click()
    page.get_by_text('P0', exact=True).wait_for()
    assert 'ant-tree-checkbox-disabled' in checkbox(page, 'P0').get_attribute('class')
    page.get_by_role('button', name='Save', exact=True).click()
    page.wait_for_function('window.saved.length===1')
    entries = page.evaluate('window.saved[0].body.items')
    assert len(entries) == 7 and 'Product/Test' in entries[0]['paths']
    assert entries[6]['paths'] == ['Historical/Entry6']
    assert sum(call['path'].endswith('/tree') for call in page.evaluate('window.calls')) == 1
    page.close()


@pytest.mark.parametrize('width', [1100, 390])
def test_configuration_creates_group_through_shared_selector_without_changing_contract(selection_browser, width):
    browser, url, _ = selection_browser
    page = browser.new_page(viewport={'width':width,'height':900}); page.set_default_timeout(10000); page.goto(url + '?mode=config')
    page.get_by_role('button', name='New product group', exact=True).click()
    drawer = page.locator('.ant-drawer-body')
    drawer.get_by_role('textbox', name='Product group name', exact=True).fill('Inline group')
    checkbox(page, 'Test products').click()
    drawer.get_by_role('button', name='Save', exact=True).click()
    page.wait_for_function("JSON.parse(window.draft).analyses.ic.configuration_groups[0].product_scope_ref==='product-group:new'")
    value = json.loads(page.evaluate('window.draft'))
    group = value['analyses']['ic']['configuration_groups'][0]
    assert group['factor_ref'] == 'factor:old' and group['config_group_id'] == 'ic-1'
    assert value['shared']['factors'] == []
    assert page.evaluate('window.saved[0].body.paths') == ['Product/Test']
    page.close()


def test_execution_installations_keep_nodes_and_install_ids_distinct(selection_browser):
    browser, url, _ = selection_browser
    page = browser.new_page(); page.set_default_timeout(10000); page.goto(url + '?mode=execution')
    page.get_by_text('Matched Bundle installations', exact=True).wait_for()
    texts = page.locator('.tr-execution-resolved .ant-select-selection-item').all_text_contents()
    assert any('node-a' in text and ' · A · ' in text for text in texts)
    assert any('node-a' in text and ' · C · ' in text for text in texts)
    page.get_by_text('Bundle', exact=True).locator('xpath=..').locator('.ant-select').click()
    page.get_by_text('Local · platform · Matching nodes: node-a, node-b', exact=True).wait_for()
    page.close()


def test_container_path_selection_does_not_enumerate_descendants(selection_browser):
    browser, url, _ = selection_browser
    page = browser.new_page(); page.set_default_timeout(10000); page.goto(url)
    checkbox(page, 'Broad products').click()
    assert 'Product/Broad' in rules(page)
    assert not page.evaluate("window.calls.some(x=>x.path.endsWith('/contract-tree'))")
    page.get_by_text('Broad products', exact=True).locator('xpath=ancestor::div[contains(@class,"ant-tree-treenode")][1]').locator('.ant-tree-switcher').click()
    assert 'ant-tree-checkbox-checked' in checkbox(page, 'Broad subset').get_attribute('class')
    checkbox(page, 'Broad subset').click()
    assert '-Product/Broad/Sub' in rules(page)
    assert not page.evaluate("window.calls.some(x=>x.path.endsWith('/contract-tree'))")
    page.close()
