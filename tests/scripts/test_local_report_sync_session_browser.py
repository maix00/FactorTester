"""The native sync owner follows the authenticated app, not research tabs."""
import json
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "web/app"


def test_one_sync_loop_survives_pages_and_stops_on_logout(tmp_path):
    harness, bundle = tmp_path / "harness.tsx", tmp_path / "harness.js"
    harness.write_text(f'''
import React, {{useState}} from {json.dumps(str(APP / "node_modules/react/index.js"))};
import {{createRoot}} from {json.dumps(str(APP / "node_modules/react-dom/client.js"))};
import {{AuthGate, useAuth}} from {json.dumps(str(APP / "src/auth.tsx"))};
import {{useLocalResearchContext}} from {json.dumps(str(APP / "src/local-research-context.tsx"))};
import {{pendingNoticeCount}} from {json.dumps(str(APP / "src/notifications/core.ts"))};
import {json.dumps(str(APP / "src/i18n.ts"))};
(window as any).pendingNoticeCount=pendingNoticeCount;
function Probe() {{const local=useLocalResearchContext();return <><button onClick={{local.requestSync}}>sync</button><span data-testid="revision">{{local.syncRevision}}</span></>;}}
function Screen() {{const [open,setOpen]=useState(false);const auth=useAuth();return <>
  <button onClick={{()=>setOpen(!open)}}>tabs</button><button onClick={{()=>void auth.logout()}}>logout</button>
  {{open && <><Probe/><Probe/></>}}
</>;}}
createRoot(document.getElementById('root')!).render(<AuthGate><Screen/></AuthGate>);
''', encoding="utf-8")
    subprocess.run([str(APP / "node_modules/.bin/esbuild"), str(harness), "--bundle", "--format=iife",
                    "--target=es2020", f"--outfile={bundle}"], cwd=APP, check=True, capture_output=True)
    (tmp_path / "index.html").write_text('<div id="root"></div>', encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
            page.evaluate('''() => {
              window.calls=[];
              window.webkit={messageHandlers:{tradeResearchLocalResearch:{postMessage(m){
                window.calls.push(m.action);
                if(m.action==='capabilities')return Promise.resolve({success:true,schema:'tr-local-research-bridge:v1',
                  binding:{issuer:'https://identity.test/realm',identity_id:'stable-1'},actions:['list','sync_reports'],
                  profiles:[{profile_id:'self',display_name:'Self'}]});
                if(window.importFixture){
                  window.importFixture=false;
                  return Promise.resolve({success:true,schema:'tr-local-research-bridge:v1',reports:[],next_report_id:null,
                    report_imports:[{research_id:'research-1',report_id:'report-1',status:'imported'}]});
                }
                if(window.conflictFixture){
                  const second=!!m.after_report_id;
                  const reports=(second?['b1','b2','b3','b4']:['a1','a2','a3','a4']).map(report_id=>({report_id,research_id:'r',status:'conflict'}));
                  return Promise.resolve({success:true,schema:'tr-local-research-bridge:v1',reports,next_report_id:second?null:'a4'});
                }
                return Promise.resolve({success:true,schema:'tr-local-research-bridge:v1',reports:[],next_report_id:null});
              }},tradeResearchAuthentication:{postMessage(){}}}};
              window.fetch=(input)=>{const path=new URL(String(input),location.origin).pathname;
                const reply=value=>Promise.resolve(new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}}));
                if(path==='/api/session')return reply({username:'alice',keycloak_issuer:'https://identity.test/realm',tr_identity_id:'stable-1',keycloak_subject:'subject'});
                return reply({});};
            }''')
            page.add_script_tag(path=str(bundle))
            page.wait_for_function("calls.includes('sync_reports')")
            page.get_by_role("button", name="tabs").click()
            assert page.get_by_role("button", name="sync").count() == 2
            page.get_by_role("button", name="sync").first.click()
            page.wait_for_function("calls.filter(x=>x==='sync_reports').length >= 2")
            before_revision = int(page.get_by_test_id("revision").first.inner_text())
            page.evaluate("window.importFixture=true; window.dispatchEvent(new Event('online'))")
            page.wait_for_function("value => Number(document.querySelector('[data-testid=revision]').textContent) > value", arg=before_revision)
            page.get_by_role("button", name="tabs").click()
            page.evaluate("window.dispatchEvent(new Event('online'))")
            page.wait_for_function("calls.filter(x=>x==='sync_reports').length >= 3")
            assert page.evaluate("calls.filter(x=>x==='capabilities').length") == 1
            notices_before = page.evaluate("pendingNoticeCount()")
            before = page.evaluate("calls.filter(x=>x==='sync_reports').length")
            page.evaluate("window.conflictFixture=true; window.dispatchEvent(new Event('online'))")
            page.wait_for_function("count => calls.filter(x=>x==='sync_reports').length >= count + 2", arg=before)
            assert page.evaluate("pendingNoticeCount()") == notices_before + 1
            page.get_by_role("button", name="logout").click()
            page.get_by_role("button", name="logout").wait_for(state="detached")
            count = page.evaluate("calls.length")
            page.evaluate("window.dispatchEvent(new Event('online'))")
            page.wait_for_timeout(400)
            assert page.evaluate("calls.length") == count
            browser.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)
