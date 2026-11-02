"""Real Dockview overflow rendering, using its production tab and shared CSS."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import subprocess
import threading
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'web/app'


def test_native_overflow_rows_fit_content(tmp_path):
    harness = tmp_path / 'harness.tsx'
    harness.write_text('''
import React from REACT;
import {createRoot} from DOM;
import {DockviewReact} from DOCK;
import {WorkspaceTab} from TAB;
import I18N;
import VENDORCSS;
import CSS;
createRoot(document.getElementById('root')!).render(<div className="tr-workspace" style={{height:300,width:350}}>
 <DockviewReact className="dockview-theme-light" components={{page:()=> <div>Page</div>}} tabComponents={{page:WorkspaceTab}}
  onReady={({api})=>{for(const pageId of ['research','test-bench','trading','products','factors','strategies','technical-docs','settings'])
   api.addPanel({id:pageId,component:'page',tabComponent:'page',params:{pageId},title:pageId});}}/>
</div>);
'''.replace('REACT',json.dumps(str(APP/'node_modules/react/index.js')))
        .replace('DOM',json.dumps(str(APP/'node_modules/react-dom/client.js')))
        .replace('DOCK',json.dumps(str(APP/'node_modules/dockview-react'/'./dist/package/main.cjs.js')))
        .replace('TAB',json.dumps(str(APP/'src/desktop-shell.tsx')))
        .replace('I18N',json.dumps(str(APP/'src/i18n.ts')))
        .replace('VENDORCSS',json.dumps(str(APP/'node_modules/dockview/dist/styles/dockview.css')))
        .replace('CSS',json.dumps(str(APP/'src/shell.css'))))
    subprocess.run([str(APP/'node_modules/.bin/esbuild'),str(harness),'--bundle','--format=iife',f'--outfile={tmp_path / "harness.js"}'],cwd=APP,check=True,capture_output=True)
    (tmp_path/'index.html').write_text('<link rel="stylesheet" href="harness.css"><div id="root"></div><script src="harness.js"></script>')
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(tmp_path)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page(viewport={'width':900,'height':600})
                errors=[];page.on('pageerror',lambda error:errors.append(type(error).__name__))
                page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                page.locator('.dv-tabs-overflow-dropdown-default').click()
                menu=page.locator('.dv-tabs-overflow-container:visible')
                menu.wait_for()
                metrics=menu.evaluate('''e=>({width:e.getBoundingClientRect().width,rows:[...e.querySelectorAll('.dv-tab')].map(row=>({height:row.getBoundingClientRect().height,text:row.textContent?.trim(),label:row.querySelector('.tr-dock-tab-title')?.getBoundingClientRect().width}))})''')
                assert metrics['rows'] and all(row['text'] and row['label'] > 0 for row in metrics['rows'])
                assert metrics['width'] <= 280, metrics
                assert all(28 <= row['height'] <= 38 for row in metrics['rows']),metrics
                page.screenshot(path='/tmp/tr-dock-overflow.png')
                menu.locator('.dv-tab').first.click()
                assert menu.count()==0 or not menu.is_visible()
                assert not errors
            finally:browser.close()
    finally:server.shutdown();server.server_close();thread.join(timeout=5)
