"""Rendered stale-layout handling; fixture APIs, not live Manager acceptance.

Browser plugin not available. Use GTHT Playwright and installed Chrome.
"""
import json
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from itertools import product
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'web/app'


def test_retired_page_and_restored_settings_never_load_legacy_frames(tmp_path):
    imports = {
        'REACT': APP/'node_modules/react/index.js',
        'DOM': APP/'node_modules/react-dom/client.js',
        'AUTH': APP/'src/auth.tsx',
        'SURFACE': APP/'src/surface.tsx',
        'I18N': APP/'src/i18n.ts',
        'CSS': APP/'src/shell.css',
    }
    source = '''
import React from REACT; import {createRoot} from DOM;
import {AuthGate} from AUTH; import {PageSurface} from SURFACE;
import I18N; import CSS;
window.fetch=async input=>{
 const path=new URL(String(input),location.origin).pathname;
 const value=path==='/api/session'?{session:{username:'Example@Alice@123',role:'user'}}:{};
 return new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});
};
function Harness(){const [page,setPage]=React.useState('retired-module');return <>
 <button onClick={()=>setPage('settings')}>Restore settings</button>
 <AuthGate><PageSurface pageId={page}/></AuthGate></>}
createRoot(document.getElementById('root')).render(<Harness/>);
'''
    for key, value in imports.items():
        source = source.replace(key, json.dumps(str(value)))
    harness = tmp_path/'harness.tsx'; harness.write_text(source)
    bundle = tmp_path/'harness.js'
    subprocess.run([str(APP/'node_modules/.bin/esbuild'),str(harness),'--bundle','--format=iife',f'--outfile={bundle}'],
                   cwd=APP,check=True,capture_output=True)
    (tmp_path/'index.html').write_text('<meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/harness.css"><div id="root"></div>')
    (tmp_path/'favicon.ico').write_bytes(b'')
    server = ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            try:
                for width,locale in product((1440,390),('zh-CN','en-US')):
                    page=browser.new_page(viewport={'width':width,'height':900},locale=locale)
                    page.set_default_timeout(8000)
                    errors=[]; navigations=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.on('framenavigated',lambda frame:navigations.append(frame.url))
                    page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                    page.evaluate("history.replaceState(null,'','/app')")
                    page.add_script_tag(path=str(bundle))
                    text='此页面已移除，请从导航重新打开。' if locale=='zh-CN' else 'This page is no longer available. Reopen it from navigation.'
                    page.get_by_text(text,exact=True).wait_for()
                    assert page.locator('iframe').count()==0
                    page.get_by_role('button',name='Restore settings',exact=True).click()
                    page.locator('.tr-function-page .tr-property-groups .tr-object-reference').filter(has_text='Alice').wait_for()
                    assert page.locator('.tr-function-header').count()==1
                    assert page.locator('.tr-property-list dt').count()==3
                    assert page.locator('iframe').count()==0
                    assert page.url.endswith('/app')
                    assert all('/settings/' not in url and '/retired-module' not in url for url in navigations)
                    assert not errors,errors
                    page.screenshot(path=str(tmp_path/f'settings-{width}-{locale}.png'))
                    page.close()
            finally:
                browser.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
