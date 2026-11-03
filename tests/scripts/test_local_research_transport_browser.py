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
import {{DesktopShell}} from {json.dumps(str(APP / "src/desktop-shell.tsx"))};
import {{AuthGate}} from {json.dumps(str(APP / "src/auth.tsx"))};
import {{bindNotificationSink}} from {json.dumps(str(APP / "src/notifications/core.ts"))};
import {json.dumps(str(APP / "src/i18n.ts"))};
import {json.dumps(str(APP / "src/shell.css"))};
import {json.dumps(str(APP / "node_modules/dockview-react/dist/styles/dockview.css"))};
(window as any).reportNotices=[];
(window as any).bindTestNotifications=()=>bindNotificationSink((notice,done)=>{{(window as any).reportNotices.push(notice);done();}});
createRoot(document.getElementById('root')!).render(<AuthGate><DesktopShell /></AuthGate>);
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
            published, pulled, synced = [], [], []
            def native(request):
                if request.get('action') == 'sync_reports':
                    synced.append(request['after_report_id'])
                    return {'success': True, 'schema': 'tr-local-research-bridge:v1', 'reports': [], 'next_report_id': None}
                if request.get('action') == 'publish_report':
                    published.append(request['report_id'])
                    return {'success': True, 'schema': 'tr-local-research-bridge:v1', 'publication': {
                        'publication_id': 'p-' + 'a' * 64, 'revision': '1-test', 'generation': 2,
                        'report_id': request['report_id']}}
                if request.get('action') == 'pull_report':
                    pulled.append(request['report_id'])
                    return {'success': True, 'schema': 'tr-local-research-bridge:v1', 'status': 'up_to_date', 'local_modified': True}
                envelope = {"binding": {"issuer": "https://identity.test/realm", "identity_id": "stable-1"},
                            "profile": {"profile_id": "self", "display_name": "Alice"}, "request": request,
                            "manager": {"endpoint":"http://127.0.0.1:7998", "subject":"subject", "token":"", "certificate_pem":"", "cookies":[]}}
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
                    if(path==='/api/research/reports')return reply({reports:[]});
                    if(path==='/api/research/capabilities/keycloak-sharing')return reply({capabilities:{schema:'tr-research-keycloak-sharing-v1',authority:'keycloak',create_research:true}});
                    if(path.startsWith('/api/test-authoring')||path.startsWith('/api/jobs'))return reply({workspaces:[],jobs:[],templates:[]});
                    throw Error('unexpected request '+path);};
                }''')
                page.add_script_tag(path=str(bundle))
                page.locator(".tr-module-nav").get_by_role("button",name="研究台",exact=True).click()
                page.get_by_role("button", name="新建研究").wait_for()
                page.evaluate("window.bindTestNotifications()")
            open_page()
            page.get_by_role("button", name="新建研究").click()
            page.locator(".ant-dropdown:visible").get_by_role("menuitem", name="本机", exact=True).click()
            assert not page.locator(".ant-modal:visible").get_by_role("combobox", name="研究身份").is_visible()
            page.get_by_label("名称", exact=True).fill("本机真实存储验收")
            page.locator(".ant-modal").get_by_role("button", name="新建研究").click()
            def surface():
                return page.locator('.tr-tab-layer[aria-hidden="false"]')
            def create_report(title):
                surface().get_by_role("button", name="新建研究报告", exact=True).click()
                form=surface().locator("form")
                form.get_by_label("名称",exact=True).fill(title)
                form.get_by_role("button",name="新建研究报告",exact=True).click()
                surface().get_by_role("button",name=title,exact=True).wait_for()
            # Creation opens a real independent Research page through Dockview.
            create_report("本机报告验收")
            create_report("本机第二报告")
            open_page()
            surface().get_by_role("tab", name="研究报告",exact=True).click()
            report_row=surface().get_by_role("row").filter(has_text="本机报告验收")
            report_row.get_by_text("本机",exact=True).wait_for()
            assert report_row.get_by_role("button",name="查看 alice 的信息").is_visible()
            surface().get_by_role("row").filter(has_text="本机第二报告").wait_for()
            report_row.get_by_role("button",name="本机报告验收",exact=True).click()
            surface().get_by_role("button",name="编辑报告内容").click()
            assert not page.get_by_role("dialog").count()
            prior_syncs=len(synced)
            surface().get_by_label("新章节标题").fill("研究方法")
            surface().get_by_role("button",name="新增章节").click()
            surface().get_by_label("段落正文").fill("真实存储的段落内容")
            surface().get_by_role("button",name="添加段落").click()
            surface().get_by_text("真实存储的段落内容").wait_for()
            for _ in range(30):
                if len(synced)>prior_syncs:break
                page.wait_for_timeout(100)
            assert len(synced)>prior_syncs
            open_page()
            surface().get_by_role("tab",name="研究报告",exact=True).click()
            surface().get_by_role("row").filter(has_text="本机报告验收").get_by_role("button",name="本机报告验收",exact=True).click()
            surface().get_by_role("button",name="编辑报告内容").click()
            surface().get_by_text("真实存储的段落内容").wait_for()
            assert not published
            surface().get_by_role("button",name="发布到服务器").click()
            page.locator(".ant-popconfirm:visible").get_by_role("button",name="发布到服务器").click()
            for _ in range(30):
                if published:break
                page.wait_for_timeout(100)
            assert len(published)==1
            surface().get_by_role("button",name="获取服务器版本").click()
            page.locator(".ant-popconfirm:visible").get_by_role("button",name="获取服务器版本").click()
            for _ in range(30):
                if pulled:break
                page.wait_for_timeout(100)
            assert pulled==published
            page.wait_for_function("window.reportNotices.some(n => n.code === 'research.local.report.pulled')")
            notice = page.evaluate("window.reportNotices.find(n => n.code === 'research.local.report.pulled')")
            assert notice['type'] == 'warning' and notice['message'] == '服务器版本未变化；本机仍有未发布的修改。'
            if os.environ.get("TR_UI_SCREENSHOT"):
                page.screenshot(path=os.environ["TR_UI_SCREENSHOT"])
            assert not errors
            browser.close()
    finally:
        http.shutdown(); http.server_close(); thread.join(timeout=2)
