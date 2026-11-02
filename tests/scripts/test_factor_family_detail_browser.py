"""Rendered lazy source/version/member navigation; HTTP is an explicit fixture."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json, subprocess, threading
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[2]
APP=ROOT/'web/app'

def test_family_versions_are_lazy_and_preserve_exact_revision(tmp_path):
    source='''import React from REACT;import {createRoot} from DOM;import {FactorFamilyDetail} from DETAIL;import {FactorDetail} from FACTOR;import {ObjectReferenceContext} from REFERENCE;import I18N;import CSS;
window.calls=[];const hash='a'.repeat(64);
window.fetch=async(url)=>{const u=new URL(url,location.origin);window.calls.push(u.pathname);let data;
if(u.pathname.endsWith('/versions'))data={versions:[{family_formula_fingerprint:hash,subject:'Frozen revision'}]};
else if(u.pathname.includes('/versions/'))data={family_formula_fingerprint:u.pathname.endsWith('current')?'c'.repeat(64):hash,source_code:u.pathname.endsWith('current')?'CURRENT SOURCE':'FROZEN SOURCE',params:[]};
else if(u.pathname==='/api/factor-library/factors')data={factors:[{ref:'factor:v2:one',alias:'Member One',factor_family_alias:'Alpha',family_owner_username:'alice',owner_username:'alice'}]};
else throw Error('unexpected request');return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});};
function Harness(){const [view,setView]=React.useState(false);return <><button onClick={()=>setView(true)}>Factor values</button><ObjectReferenceContext.Provider value={value=>window.opened=value}>{view?<FactorDetail detail={{factor:{ref:'factor:v2:parent',identity:{params:{N:0,B:false,Child:'factor:v2:child'}}},family:{params:[{alias:'N'},{alias:'B'},{alias:'Child'}]}}}/>:<FactorFamilyDetail family={{factor_family_alias:'Alpha',owner_username:'alice',description:'Family overview'}}/>}</ObjectReferenceContext.Provider></>}createRoot(document.getElementById('root')).render(<Harness/>);'''
    for key,path in {'REACT':'node_modules/react/index.js','DOM':'node_modules/react-dom/client.js','DETAIL':'src/components/factor-family-detail.tsx','FACTOR':'src/components/factor-detail.tsx','REFERENCE':'src/components/object-reference.tsx','I18N':'src/i18n.ts','CSS':'src/shell.css'}.items():
        source=source.replace(key,json.dumps(str(APP/path)))
    (tmp_path/'harness.tsx').write_text(source)
    subprocess.run([str(APP/'node_modules/.bin/esbuild'),str(tmp_path/'harness.tsx'),'--bundle','--format=iife',f'--outfile={tmp_path/"harness.js"}'],cwd=APP,check=True,capture_output=True)
    (tmp_path/'index.html').write_text('<title>Family detail QA</title><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="harness.css"><div id="root"></div><script src="harness.js"></script>')
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            try:
                for width in (1200,390):
                    page=browser.new_page(viewport={'width':width,'height':850});page.set_default_timeout(8000);errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/index.html');expect(page.get_by_text('Family overview',exact=True)).to_be_visible()
                    assert page.title()=='Family detail QA' and page.evaluate('window.calls.length')==0
                    page.get_by_role('tab',name='Source',exact=True).click();expect(page.locator('pre')).to_have_text('CURRENT SOURCE')
                    assert page.evaluate('window.calls.length')==2
                    page.get_by_role('tab',name='Versions',exact=True).click();page.get_by_role('button',name='a'*12,exact=True).click()
                    expect(page.locator('pre')).to_have_text('FROZEN SOURCE')
                    page.get_by_role('tab',name='Overview',exact=True).click();page.get_by_role('tab',name='Source',exact=True).click()
                    expect(page.locator('.ant-spin-spinning')).to_have_count(0)
                    assert page.evaluate('window.calls.length')==3
                    page.get_by_role('tab',name='Member factors',exact=True).click();expect(page.get_by_text('Member One',exact=True)).to_be_visible()
                    assert page.evaluate('window.calls.length')==4
                    page.screenshot(path=f'/tmp/tr-family-detail-{width}.png')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.get_by_role('button',name='Factor values',exact=True).click()
                    expect(page.get_by_role('columnheader',name='Value',exact=True)).to_be_visible()
                    expect(page.get_by_role('cell',name='0',exact=True)).to_be_visible()
                    expect(page.get_by_role('cell',name='false',exact=True)).to_be_visible()
                    page.get_by_role('button',name='View information for factor:v2:child',exact=True).click()
                    assert page.evaluate('window.opened.ref')=='factor:v2:child'
                    assert not errors
                    page.close()
            finally:browser.close()
    finally:server.shutdown();server.server_close()
