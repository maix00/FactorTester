"""Exercise the actual React sync scheduler with deterministic native replies."""
from __future__ import annotations

import json
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'web/app'


def test_multipage_failure_notifies_once_until_complete_recovery(tmp_path):
    harness, bundle = tmp_path / 'sync.tsx', tmp_path / 'sync.js'
    harness.write_text(f'''
import React from {json.dumps(str(APP / 'node_modules/react/index.js'))};
import {{createRoot}} from {json.dumps(str(APP / 'node_modules/react-dom/client.js'))};
import {{useLocalReportSync}} from {json.dumps(str(APP / 'src/use-local-report-sync.ts'))};
import {{bindNotificationSink}} from {json.dumps(str(APP / 'src/notifications/core.ts'))};
import {json.dumps(str(APP / 'src/i18n.ts'))};
const state = (window as any).fixture = {{timers:[],notices:[],fail:true,calls:[]}};
const original = window.setTimeout.bind(window);
window.setTimeout = ((fn:any,delay?:number,...args:any[]) => {{
  if (delay===250 || delay===60000) {{state.timers.push(() => fn(...args)); return 1;}}
  return original(fn,delay,...args);
}}) as typeof setTimeout;
window.clearTimeout = (() => {{}}) as typeof clearTimeout;
let now=100000; Date.now=()=>now;
bindNotificationSink((notice,done)=>{{state.notices.push(notice.code);done();}});
const client={{snapshot:()=>1,isCurrent:()=>true,syncReports:async (_profile:string,cursor:string) => {{
  state.calls.push(cursor);
  if(!cursor)return {{reports:[],researches:[],report_imports:[],report_scans:[],next_report_id:'report-1'}};
  if(state.fail)throw Error('offline');
  return {{reports:[],researches:[],report_imports:[],report_scans:[],next_report_id:null}};
}}}};
const caps={{actions:['sync_reports'],profiles:[{{profile_id:'self',display_name:'Self'}}]}};
function App() {{useLocalReportSync(client as any,caps as any,true,()=>{{}});return <div>sync</div>;}}
createRoot(document.getElementById('root')!).render(<App/>);
(window as any).step = async () => {{now+=4000;const f=state.timers.shift();if(!f)throw Error('missing scheduled sync');f();for(let i=0;i<8;i++)await Promise.resolve();}};
''', encoding='utf-8')
    subprocess.run([str(APP / 'node_modules/.bin/esbuild'), str(harness), '--bundle', '--format=iife',
                    '--target=es2020', f'--outfile={bundle}'], cwd=APP, check=True, capture_output=True)
    (tmp_path / 'index.html').write_text('<div id="root"></div><script src="/sync.js"></script>', encoding='utf-8')
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page()
                page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                page.wait_for_function('window.fixture?.timers.length > 0')
                for _ in range(4): page.evaluate('window.step()')
                assert page.evaluate('window.fixture.calls') == ['', 'report-1', '', 'report-1']
                assert page.evaluate('window.fixture.notices') == ['research.discovery.unavailable', 'research.report.sync.unavailable']
                page.evaluate('window.fixture.fail=false')
                for _ in range(2): page.evaluate('window.step()')
                page.evaluate('window.fixture.fail=true')
                for _ in range(2): page.evaluate('window.step()')
                assert page.evaluate('window.fixture.notices') == ['research.discovery.unavailable', 'research.report.sync.unavailable', 'research.report.sync.unavailable']
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=3)


def test_background_research_discovery_paginates_without_reopening_a_page(tmp_path):
    harness, bundle = tmp_path / 'discovery.tsx', tmp_path / 'discovery.js'
    harness.write_text(f'''
import React from {json.dumps(str(APP / 'node_modules/react/index.js'))};
import {{createRoot}} from {json.dumps(str(APP / 'node_modules/react-dom/client.js'))};
import {{useLocalReportSync}} from {json.dumps(str(APP / 'src/use-local-report-sync.ts'))};
import {json.dumps(str(APP / 'src/i18n.ts'))};
const state=(window as any).fixture={{timers:[],discover:[],sync:0,changed:0}};
window.setTimeout=((fn:any,delay?:number)=>{{state.timers.push({{fn,delay}});return 1;}}) as typeof setTimeout;
window.clearTimeout=(()=>{{}}) as typeof clearTimeout;
const client={{snapshot:()=>1,isCurrent:()=>true,
  discoverResearches:async (_profile:string,cursor:string)=>{{state.discover.push(cursor);return {{queued:cursor?1:0,next_cursor:cursor?null:'next'}};}},
  syncReports:async()=>{{state.sync++;return {{reports:[],researches:state.sync===2?[{{research_id:'r',status:'imported'}}]:[],report_imports:[],report_scans:[],researches_pending_more:false,next_report_id:null}};}}
}};
const caps={{actions:['sync_reports','discover_researches'],profiles:[{{profile_id:'self',display_name:'Self'}}]}};
function App(){{useLocalReportSync(client as any,caps as any,true,()=>{{state.changed++;}});return <div>sync</div>;}}
createRoot(document.getElementById('root')!).render(<App/>);
(window as any).step=async()=>{{const item=state.timers.shift();if(!item)throw Error('missing timer');item.fn();for(let i=0;i<16;i++)await Promise.resolve();}};
''', encoding='utf-8')
    subprocess.run([str(APP / 'node_modules/.bin/esbuild'), str(harness), '--bundle', '--format=iife',
                    '--target=es2020', f'--outfile={bundle}'], cwd=APP, check=True, capture_output=True)
    (tmp_path / 'index.html').write_text('<div id="root"></div><script src="/discovery.js"></script>', encoding='utf-8')
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page()
                page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                page.wait_for_function('window.fixture?.timers.length > 0')
                page.evaluate('window.step()')
                assert page.evaluate('window.fixture.discover') == ['']
                assert page.evaluate('window.fixture.timers[0].delay') == 250
                page.evaluate('window.step()')
                assert page.evaluate('window.fixture.discover') == ['', 'next']
                assert page.evaluate('window.fixture.changed') == 1
                assert page.evaluate('window.fixture.timers[0].delay') == 60000
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=3)


def test_wake_restarts_discovery_and_coalesces_an_inflight_scan(tmp_path):
    harness, bundle = tmp_path / 'wake.tsx', tmp_path / 'wake.js'
    harness.write_text(f'''
import React from {json.dumps(str(APP / 'node_modules/react/index.js'))};
import {{createRoot}} from {json.dumps(str(APP / 'node_modules/react-dom/client.js'))};
import {{useLocalReportSync}} from {json.dumps(str(APP / 'src/use-local-report-sync.ts'))};
import {json.dumps(str(APP / 'src/i18n.ts'))};
const state=(window as any).fixture={{timers:new Map(),next:0,discover:[],sync:[],hold:false,resolve:null}};
window.setTimeout=((fn:any,delay?:number)=>{{const id=++state.next;state.timers.set(id,{{fn,delay}});return id;}}) as typeof setTimeout;
window.clearTimeout=((id:number)=>state.timers.delete(id)) as typeof clearTimeout;
const client={{snapshot:()=>1,isCurrent:()=>true,
  discoverResearches:async (profile:string,cursor:string)=>{{state.discover.push([profile,cursor]);return {{queued:0,next_cursor:null}};}},
  syncReports:async (profile:string,cursor:string)=>{{state.sync.push([profile,cursor]);
    if(state.hold){{state.hold=false;await new Promise(resolve=>{{state.resolve=resolve;}});}}
    return {{reports:[],researches:[],report_imports:[],report_scans:[],researches_pending_more:false,next_report_id:cursor?null:'next'}};
  }}
}};
const caps={{actions:['sync_reports','discover_researches'],profiles:[{{profile_id:'one'}},{{profile_id:'two'}}]}};
function App(){{const wake=useLocalReportSync(client as any,caps as any,true,()=>{{}});return <button onClick={{wake}}>Wake</button>;}}
createRoot(document.getElementById('root')!).render(<App/>);
(window as any).step=async()=>{{const [id,item]=state.timers.entries().next().value;state.timers.delete(id);item.fn();for(let i=0;i<16;i++)await Promise.resolve();}};
''', encoding='utf-8')
    subprocess.run([str(APP / 'node_modules/.bin/esbuild'), str(harness), '--bundle', '--format=iife',
                    '--target=es2020', f'--outfile={bundle}'], cwd=APP, check=True, capture_output=True)
    (tmp_path / 'index.html').write_text('<div id="root"></div><script src="/wake.js"></script>', encoding='utf-8')
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page()
                page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                page.wait_for_function('window.fixture?.timers.size > 0')
                page.evaluate('window.step()')
                page.get_by_role('button', name='Wake').click()
                page.evaluate('window.step()')
                assert page.evaluate('window.fixture.discover') == [['one', ''], ['one', '']]
                assert page.evaluate('window.fixture.sync') == [['one', ''], ['one', '']]
                page.evaluate('window.fixture.hold=true')
                page.evaluate('window.step()')
                page.wait_for_function('window.fixture.resolve !== null')
                page.get_by_role('button', name='Wake').click()
                page.get_by_role('button', name='Wake').click()
                page.evaluate('window.fixture.resolve()')
                page.wait_for_function('window.fixture.timers.size === 1')
                page.evaluate('window.step()')
                assert page.evaluate('window.fixture.discover') == [['one', ''], ['one', ''], ['one', '']]
                assert page.evaluate('window.fixture.sync.slice(-1)[0]') == ['one', '']
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=3)
