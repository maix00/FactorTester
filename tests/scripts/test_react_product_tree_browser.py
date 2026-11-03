"""Virtualized React tree reads bounded server pages only when expanded."""
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import json,subprocess,threading
import pytest
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[2];APP=ROOT/'web/app'

@pytest.mark.parametrize('width',[900,390])
def test_product_tree_lazy_pages_and_selection(tmp_path,width):
    paths={name:json.dumps(str(APP/path)) for name,path in {
     'REACT':'node_modules/react/index.js','DOM':'node_modules/react-dom/client.js','TREE':'src/components/product-tree.tsx',
     'INSTANCE':'src/page-instance.ts','I18N':'src/i18n.ts','CSS':'src/shell.css',
    }.items()}
    source='''
import React from REACT;import {createRoot} from DOM;import {ProductTree} from TREE;import {PageInstanceProvider} from INSTANCE;import I18N;import CSS;
window.calls=[];window.opened=[];
window.fetch=async(url)=>{const u=new URL(url,location.origin);window.calls.push(u.pathname+u.search);
 const body=u.pathname.endsWith('/tree')?{tree:[{key:'Product/Test',title:'Test products',folder:true,lazy:true}]}:
 {nodes:Array.from({length:50},(_,i)=>{const id=(Number(u.searchParams.get('page'))-1)*50+i;return {key:'Product/Test/P'+id,title:'P'+id,product_name:'P'+id,lazy:false,folder:false};}),has_more:true,total:5000};
 return new Response(JSON.stringify(body),{headers:{'Content-Type':'application/json'}});};
createRoot(document.getElementById('root')).render(<PageInstanceProvider value={{id:'test',pageId:'products',mobile:false,args:{},open:(page,args)=>window.opened.push({page,args})}}><ProductTree/></PageInstanceProvider>);
'''
    for name,path in paths.items():source=source.replace(name,path)
    harness=tmp_path/'harness.tsx';harness.write_text(source)
    subprocess.run([str(APP/'node_modules/.bin/esbuild'),str(harness),'--bundle','--format=iife',f'--outfile={tmp_path/"harness.js"}'],cwd=APP,check=True,capture_output=True)
    (tmp_path/'index.html').write_text('<title>Product tree QA</title><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="harness.css"><div id="root"></div><script src="harness.js"></script>')
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(tmp_path)));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page(viewport={'width':width,'height':700});page.set_default_timeout(8000)
                errors=[];page.on('pageerror',lambda e:errors.append(type(e).__name__))
                page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                assert page.title()=='Product tree QA'
                page.get_by_text('Test products',exact=True).wait_for()
                assert page.evaluate('window.calls.length')==1
                page.locator('.ant-tree-switcher').first.click()
                page.get_by_text('P0',exact=True).wait_for()
                assert page.evaluate('window.calls.length')==2
                assert 'limit=50' in page.evaluate('window.calls[1]')
                assert page.locator('.ant-tree-treenode').count()<40
                page.locator('.ant-tree-list-holder').evaluate('e=>e.scrollTop=e.scrollHeight')
                page.get_by_role('button',name='Load more products',exact=True).click()
                page.wait_for_function('window.calls.length===3')
                assert 'page=2' in page.evaluate('window.calls[2]')
                page.locator('.ant-tree-list-holder').evaluate('e=>e.scrollTop=0')
                page.get_by_text('P0',exact=True).click()
                assert page.evaluate('window.opened')==[{'page':'product-detail','args':{'productName':'P0','productTitle':'P0'}}]
                assert page.locator('.ant-tree-treenode').count()<40
                page.get_by_role('button',name='Refresh product catalog',exact=True).click()
                page.wait_for_function('window.calls.length===4')
                assert page.evaluate('window.calls[3]') == '/api/product-library/tree?refresh=1'
                page.locator('.ant-tree-switcher').first.click()
                page.get_by_text('P0',exact=True).wait_for()
                assert page.evaluate('window.calls.length')==5
                page.screenshot(path=str(tmp_path/'product-tree-refresh.png'))
                assert not errors
            finally:browser.close()
    finally:server.shutdown();server.server_close();thread.join(timeout=5)
