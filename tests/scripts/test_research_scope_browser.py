"""Research scope and references must remain usable on both layouts."""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import subprocess
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "web/app"


def test_research_scope_ignores_stale_results_and_navigates_references(tmp_path):
    harness = tmp_path / "harness.tsx"
    bundle = tmp_path / "harness.js"
    harness.write_text(f"""
import React from {json.dumps(str(APP / 'node_modules/react/index.js'))};
import {{createRoot}} from {json.dumps(str(APP / 'node_modules/react-dom/client.js'))};
import {{ResearchPage}} from {json.dumps(str(APP / 'src/pages/research.tsx'))};
import {{ObjectReferenceContext}} from {json.dumps(str(APP / 'src/components/object-reference.tsx'))};
import {{assistantResearchContexts}} from {json.dumps(str(APP / 'src/assistant-research-context.ts'))};
import {{AuthGate}} from {json.dumps(str(APP / 'src/auth.tsx'))};
import i18n from {json.dumps(str(APP / 'src/i18n.ts'))};
import {json.dumps(str(APP / 'src/shell.css'))};
window.fixture.setLanguage = language => i18n.changeLanguage(language);
window.fixture.context = () => assistantResearchContexts.snapshot();
createRoot(document.getElementById('root')!).render(
  <AuthGate><ObjectReferenceContext.Provider value={{value => window.fixture.opened.push(value)}}>
    <ResearchPage />
  </ObjectReferenceContext.Provider></AuthGate>
);
""", encoding="utf-8")
    subprocess.run([str(APP / "node_modules/.bin/esbuild"), str(harness), "--bundle",
                    "--format=iife", "--target=es2020", f"--outfile={bundle}"],
                   cwd=APP, check=True, capture_output=True, text=True)
    (tmp_path / "index.html").write_text('<link rel="stylesheet" href="/harness.css"><div id="root"></div>', encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                for viewport in ({"width": 1440, "height": 900}, {"width": 765, "height": 900}, {"width": 390, "height": 844}):
                    page = browser.new_page(viewport=viewport, locale="zh-CN")
                    page.set_default_timeout(5000)
                    page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                    page.evaluate("""() => {
                      const fixture = window.fixture = {requests:[],opened:[],releaseMine:null,allowResearch:true,authority:'legacy'};
                      window.fetch = (input, options = {}) => {
                        const url = new URL(String(input), location.origin);
                        fixture.requests.push(url.pathname + url.search);
                        const response = body => new Response(JSON.stringify(body),
                          {status:200,headers:{'Content-Type':'application/json'}});
                        if (url.pathname === '/api/session') return Promise.resolve(response({session:{username:'alice'}}));
                        if (url.pathname === '/api/public/entry') return Promise.resolve(response({}));
                        if (url.pathname === '/api/research/capabilities/keycloak-sharing') return Promise.resolve(response({capabilities:{schema:'tr-research-keycloak-sharing-v1',authority:fixture.authority}}));
                        if (url.pathname === '/api/research/r1') return Promise.resolve(response({research:{
                          research_id:'r1',title:'研究甲',owner_ref:'alice',access:{can_view:fixture.allowResearch,can_manage:false}
                        }}));
                        if (url.pathname === '/api/research/r1/members') return Promise.resolve(response({members:[]}));
                        if (url.pathname === '/api/research/r1/workspaces') return Promise.resolve(response({workspaces:[]}));
                        if (url.pathname === '/api/research/r1/reports') return Promise.resolve(response({reports:[]}));
                        if (url.pathname === '/api/research-evidence/catalog/research/r1') return Promise.resolve(response({catalog:{items:[],total:0}}));
                        const report = url.pathname === '/api/research/reports';
                        if (url.pathname !== '/api/research' && !report) throw Error('unexpected path: ' + url.pathname);
                        const scope = url.searchParams.get('scope');
                        const row = report
                          ? {report_id:'report-1',title:'报告甲：较长的研究标题在移动端应该完整地换行显示以避免内容被裁切',research_id:'r1',research_title:'研究甲',profile_ref:'self',profile_key:'local::alice::self',owner_ref:'alice',visibility:'private',updated_at:1700000000,
                             branches:[{publication_id:'branch-1',source_kind:'workspace',title:'高频时间维度因子复现与筛选报告（国债期货 T/TL）及多阶段研究成果',profile_ref:'researcher-with-long-name'}]}
                          : {research_id:scope === 'shared' ? 'shared-r' : 'r1',title:scope === 'shared' ? '共享研究' : '研究甲',owner_ref:'alice'};
                        const payload = report ? {reports:[row]} : {researches:[row]};
                        if (scope === 'mine') return new Promise(resolve => { fixture.releaseMine = () => resolve(response(payload)); });
                        return Promise.resolve(response(payload));
                      };
                    }""")
                    page.add_script_tag(path=str(bundle))
                    page.get_by_role("button", name="研究甲", exact=True).wait_for()
                    assert page.get_by_role("combobox", name="研究范围").count() == 0
                    assert "/api/research?scope=all" in page.evaluate("window.fixture.requests")
                    page.get_by_role("tab", name="研究报告").click()
                    page.get_by_role("button", name="报告甲：较长的研究标题在移动端应该完整地换行显示以避免内容被裁切", exact=True).wait_for()
                    headers = page.locator(".tr-research-table thead tr:not(.ant-table-measure-row) th")
                    assert headers.filter(has_text="研究身份").count() == 1
                    assert headers.filter(has_text="所有者").count() == 1
                    assert headers.filter(has_text="更新时间").count() == 1
                    assert page.locator(".tr-research-mobile-meta").count() == 0
                    assert "/api/research/reports?scope=all" in page.evaluate("window.fixture.requests")
                    page.get_by_role("button", name="查看 self 的信息").first.click()
                    page.get_by_role("button", name="查看 alice 的信息").click()
                    opened = page.evaluate("window.fixture.opened")
                    assert opened[0]["kind"] == "profile" and opened[0]["ref"] == "self"
                    assert opened[0]["profileKey"] == "local::alice::self" and opened[0]["owner"] == "alice"
                    assert opened[1]["kind"] == "user" and opened[1]["ref"] == "alice"
                    page.get_by_role("button", name="报告甲：较长的研究标题在移动端应该完整地换行显示以避免内容被裁切", exact=True).click()
                    dialog = page.get_by_role("dialog")
                    dialog.get_by_role("combobox", name="报告版本").wait_for()
                    assert dialog.locator('.tr-report-source-picker').evaluate(
                        'node => node.scrollWidth <= node.clientWidth + 1')
                    assert dialog.locator('.ant-modal-body').evaluate(
                        'node => node.scrollWidth <= node.clientWidth + 1')
                    if viewport["width"] <= 760:
                        dialog.get_by_role("button",name="返回").click()
                    else:
                        page.locator(".ant-modal-close").click()
                    page.evaluate("window.fixture.authority='keycloak'; window.fixture.setLanguage('en')")
                    assert page.get_by_role("tab", name="Reports").is_visible()
                    page.wait_for_function("!document.body.innerText.includes('Only me')")
                    page.evaluate("window.fixture.authority='legacy'; window.fixture.setLanguage('zh')")
                    page.get_by_role("button", name="研究甲", exact=True).click()
                    page.get_by_role("dialog").wait_for()
                    assert "/api/research/r1" in page.evaluate("window.fixture.requests")
                    dialog = page.get_by_role("dialog")
                    for label in ("详情", "研究报告", "证据", "研究身份", "研究工作区"):
                        assert dialog.get_by_role("tab", name=label, exact=True).is_visible()
                    assert dialog.get_by_role("button", name="打开编辑器").count() == 0
                    assert dialog.locator('iframe[src*="/researches/"]').count() == 0
                    page.wait_for_function("window.fixture.context()?.researchId === 'r1'")
                    assert page.evaluate("window.fixture.context().section") == "details"
                    page.screenshot(path=str(tmp_path / f"research-{viewport['width']}.png"), animations="disabled")
                    for label, endpoint in (("研究报告", "/api/research/r1/reports"),
                                            ("证据", "/api/research-evidence/catalog/research/r1"),
                                            ("研究工作区", "/api/research/r1/workspaces")):
                        dialog.get_by_role("tab", name=label, exact=True).click()
                        try:
                            page.wait_for_function("url => window.fixture.requests.some(r => r.startsWith(url))", arg=endpoint)
                        except Exception as exc:
                            raise AssertionError(f"viewport={viewport} tab={label} requests={page.evaluate('window.fixture.requests')}") from exc
                    page.get_by_role("dialog").get_by_role("tab",name="研究身份").click()
                    page.wait_for_function("window.fixture.context()?.section === 'members'")
                    if viewport["width"] <= 760:
                        page.get_by_role("dialog").get_by_role("button",name="返回").click()
                    else:
                        page.locator(".ant-modal-close").click()
                    page.wait_for_function("window.fixture.context() === null")
                    page.get_by_role("button", name="研究甲", exact=True).first.click()
                    page.wait_for_function("window.fixture.context()?.section === 'details'")
                    if viewport["width"] <= 760:
                        page.get_by_role("dialog").get_by_role("button",name="返回").click()
                    else:
                        page.locator(".ant-modal-close").click()
                    page.wait_for_function("window.fixture.context() === null")
                    page.evaluate("window.fixture.allowResearch = false")
                    page.get_by_role("button", name="研究甲", exact=True).first.click()
                    page.get_by_role("dialog").wait_for()
                    page.wait_for_timeout(100)
                    assert page.evaluate("window.fixture.context()") is None
                    page.close()
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)
