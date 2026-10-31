"""Presentation-only desktop detection must not call an unimplemented local bridge."""
from __future__ import annotations

import json
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "web/app"


def test_local_research_status_distinguishes_client_web_and_mobile(tmp_path):
    harness, bundle = tmp_path / "harness.tsx", tmp_path / "harness.js"
    harness.write_text(f"""
import React from {json.dumps(str(APP / 'node_modules/react/index.js'))};
import {{createRoot}} from {json.dumps(str(APP / 'node_modules/react-dom/client.js'))};
import {{ResearchPage}} from {json.dumps(str(APP / 'src/pages/research.tsx'))};
import {{PageInstanceProvider}} from {json.dumps(str(APP / 'src/page-instance.ts'))};
import {{AuthGate}} from {json.dumps(str(APP / 'src/auth.tsx'))};
import {json.dumps(str(APP / 'src/i18n.ts'))};
import {json.dumps(str(APP / 'src/shell.css'))};
createRoot(document.getElementById('root')!).render(<AuthGate><PageInstanceProvider value={{{{
  id:'fixture',pageId:'research',mobile:window.fixture.mobile,args:{{}},active:true,open:()=>{{}}
}}}}><ResearchPage /></PageInstanceProvider></AuthGate>);
""", encoding="utf-8")
    subprocess.run([str(APP / "node_modules/.bin/esbuild"), str(harness), "--bundle",
                    "--format=iife", "--target=es2020", f"--outfile={bundle}"],
                   cwd=APP, check=True, capture_output=True, text=True)
    (tmp_path / "index.html").write_text('<link rel="stylesheet" href="/harness.css"><div id="root"></div>', encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    cases = [
        ("browser", {"width": 1440, "height": 900}, False, False),
        ("partial", {"width": 1440, "height": 900}, False, False),
        ("desktop", {"width": 1440, "height": 900}, False, True),
        ("desktop", {"width": 390, "height": 844}, False, True),
        ("mobile", {"width": 390, "height": 844}, True, False),
    ]
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                for mode, viewport, mobile, desktop in cases:
                    page = browser.new_page(viewport=viewport, locale="zh-CN")
                    page.set_default_timeout(5000)
                    page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                    page.evaluate("""([mode,mobile]) => {
                      const f=window.fixture={mobile,calls:[],nativeCalls:[]};
                      const handler={postMessage(value){f.nativeCalls.push(value);return Promise.resolve({});}};
                      if(mode==='partial')window.webkit={messageHandlers:{factorTesterLocalRun:handler,tradeResearchLocalResearch:handler}};
                      if(mode==='desktop'||mode==='mobile')window.webkit={messageHandlers:{factorTesterLocalRun:handler,factorTesterLocalCatalog:handler,tradeResearchLocalResearch:handler}};
                      window.fetch=(input,options={})=>{const u=new URL(String(input),location.origin);f.calls.push({path:u.pathname,method:options.method||'GET'});
                        const res=value=>Promise.resolve(new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}}));
                        if(u.pathname==='/api/session')return res({session:{username:'alice'}});
                        if(u.pathname==='/api/public/entry')return res({});
                        if(u.pathname==='/api/client/profiles')return res({profiles:[]});
                        if(u.pathname==='/api/research/capabilities/keycloak-sharing')return res({capabilities:{schema:'tr-research-keycloak-sharing-v1',authority:'keycloak',create_research:true}});
                        if(u.pathname==='/api/research')return res({researches:[]});
                        throw Error('unexpected request '+u.pathname);};
                    }""", [mode, mobile])
                    page.add_script_tag(path=str(bundle))
                    origin = "当前显示服务器研究；电脑客户端本地研究尚未接通。" if desktop else "当前显示服务器研究。"
                    page.get_by_text(origin, exact=True).wait_for()
                    assert page.get_by_text("当前显示服务器研究；电脑客户端本地研究尚未接通。", exact=True).count() == int(desktop)
                    page.get_by_role("button", name="新建服务器研究").click()
                    hint = "当前入口在服务器创建研究；电脑客户端本地创建尚未接通。" if desktop else "此入口在服务器创建研究。"
                    page.get_by_text(hint, exact=True).wait_for()
                    assert page.evaluate("window.fixture.nativeCalls.length") == 0
                    assert not page.evaluate("window.fixture.calls.some(c => c.method !== 'GET')")
                    assert page.locator(".ant-modal-content").evaluate("element => element.scrollWidth <= element.clientWidth + 2")
                    if mode == "desktop":
                        screenshot_dir = Path("/tmp/tr-object-ui-qa"); screenshot_dir.mkdir(exist_ok=True)
                        page.wait_for_timeout(300)  # Wait for the Modal's entrance animation before visual inspection.
                        page.screenshot(path=str(screenshot_dir / f"research-origin-{viewport['width']}.png"))
                    page.close()
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)
