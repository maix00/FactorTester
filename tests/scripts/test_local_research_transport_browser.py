"""React -> simulated native transport -> actual client CLI and local SQLite.

This exercises real local persistence; WebKit origin and native session checks
are covered separately and still require a packaged macOS acceptance run.
"""
import json
import os
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "web/app"


def test_research_create_survives_page_reload_through_real_cli(tmp_path):
    harness, bundle = tmp_path / "harness.tsx", tmp_path / "harness.js"
    harness.write_text(f'''
import React from {json.dumps(str(APP / "node_modules/react/index.js"))};
import {{createRoot}} from {json.dumps(str(APP / "node_modules/react-dom/client.js"))};
import {{ResearchPage}} from {json.dumps(str(APP / "src/pages/research.tsx"))};
import {{PageInstanceProvider}} from {json.dumps(str(APP / "src/page-instance.ts"))};
import {{AuthGate}} from {json.dumps(str(APP / "src/auth.tsx"))};
import {json.dumps(str(APP / "src/i18n.ts"))};
import {json.dumps(str(APP / "src/shell.css"))};
createRoot(document.getElementById('root')!).render(<AuthGate><PageInstanceProvider value={{{{
 id:'fixture',pageId:'research',mobile:false,args:{{}},active:true,open:()=>{{}}
}}}}><ResearchPage /></PageInstanceProvider></AuthGate>);
''', encoding="utf-8")
    subprocess.run([str(APP / "node_modules/.bin/esbuild"), str(harness), "--bundle", "--format=iife",
                    "--target=es2020", f"--outfile={bundle}"], cwd=APP, check=True, capture_output=True)
    (tmp_path / "index.html").write_text('<link rel="stylesheet" href="/harness.css"><div id="root"></div>', encoding="utf-8")
    http = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page.set_default_timeout(10000)
            def native(request):
                envelope = {"binding": {"issuer": "https://identity.test/realm", "identity_id": "stable-1"},
                            "profile": {"profile_id": "self", "display_name": "Alice"}, "request": request}
                process = subprocess.run([sys.executable, "-m", "tools.cli.app", "client", "local-research-request"],
                                         input=json.dumps(envelope), cwd=ROOT, text=True, capture_output=True,
                                         env={**os.environ, "TRADERESEARCH_CLIENT_ROOT": str(tmp_path / "client")}, timeout=15)
                assert process.returncode == 0, process.stderr
                return json.loads(process.stdout)
            page.expose_function("localResearchRequest", native)
            errors = []; page.on("pageerror", lambda error: errors.append(str(error)))
            def open_page():
                page.goto(f"http://127.0.0.1:{http.server_port}/index.html")
                page.evaluate('''() => {
                  window.webkit={messageHandlers:{tradeResearchLocalResearch:{postMessage:m=>window.localResearchRequest(m)},tradeResearchAuthentication:{postMessage(){}}}};
                  window.fetch=input=>{const path=new URL(String(input),location.origin).pathname;
                    const reply=x=>Promise.resolve(new Response(JSON.stringify(x),{status:200,headers:{'Content-Type':'application/json'}}));
                    if(path==='/api/session')return reply({username:'alice',keycloak_issuer:'https://identity.test/realm',tr_identity_id:'stable-1',keycloak_subject:'subject'});
                    if(path==='/api/public/entry')return reply({});
                    if(path==='/api/research')return reply({researches:[]});
                    if(path==='/api/research/capabilities/keycloak-sharing')return reply({capabilities:{schema:'tr-research-keycloak-sharing-v1',authority:'keycloak',create_research:true}});
                    throw Error('unexpected request '+path);};
                }''')
                page.add_script_tag(path=str(bundle))
                page.get_by_role("button", name="新建研究").wait_for()
            open_page()
            page.get_by_role("button", name="新建研究").click()
            page.locator(".ant-dropdown:visible").get_by_role("menuitem", name="本机", exact=True).click()
            page.get_by_label("名称", exact=True).fill("本机真实存储验收")
            page.locator(".ant-modal").get_by_role("button", name="新建研究").click()
            page.get_by_role("button", name="本机真实存储验收").wait_for()
            open_page()
            page.get_by_role("button", name="本机真实存储验收").wait_for()
            assert not errors
            browser.close()
    finally:
        http.shutdown(); http.server_close(); thread.join(timeout=2)
