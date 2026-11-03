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


def test_research_directory_navigates_independent_details_and_references(tmp_path):
    harness = tmp_path / "harness.tsx"
    bundle = tmp_path / "harness.js"
    harness.write_text(f"""
import React from {json.dumps(str(APP / 'node_modules/react/index.js'))};
import {{createRoot}} from {json.dumps(str(APP / 'node_modules/react-dom/client.js'))};
import {{ResearchDetailPage}} from {json.dumps(str(APP / 'src/pages/research-detail.tsx'))};
import {{PageInstanceProvider}} from {json.dumps(str(APP / 'src/page-instance.ts'))};
import {{ResearchPage}} from {json.dumps(str(APP / 'src/pages/research.tsx'))};
import {{ObjectReferenceContext}} from {json.dumps(str(APP / 'src/components/object-reference.tsx'))};
import {{assistantResearchContexts}} from {json.dumps(str(APP / 'src/assistant-research-context.ts'))};
import {{AuthGate}} from {json.dumps(str(APP / 'src/auth.tsx'))};
import i18n from {json.dumps(str(APP / 'src/i18n.ts'))};
import {json.dumps(str(APP / 'src/shell.css'))};
window.fixture.setLanguage = language => i18n.changeLanguage(language);
window.fixture.context = () => assistantResearchContexts.snapshot();
function Harness() {{
 const [current,setCurrent]=React.useState(null);
 return <AuthGate><ObjectReferenceContext.Provider value={{value => window.fixture.opened.push(value)}}>
  <PageInstanceProvider value={{{{id:'directory',pageId:'research',mobile:innerWidth<760,args:{{}},active:!current,
    open:(pageId,args)=>setCurrent({{pageId,args}})}}}}>
    <div hidden={{!!current}}><ResearchPage/></div>
  </PageInstanceProvider>
  {{current?<PageInstanceProvider value={{{{id:'detail',pageId:current.pageId,mobile:innerWidth<760,args:current.args,active:true,
    open:(pageId,args)=>setCurrent({{pageId,args}}),back:()=>setCurrent(null)}}}}>
    <section data-testid="detail"><button onClick={{()=>setCurrent(null)}}>返回研究列表</button><ResearchDetailPage/></section>
  </PageInstanceProvider>:null}}
 </ObjectReferenceContext.Provider></AuthGate>;
}}
createRoot(document.getElementById('root')!).render(<Harness/>);
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
                      const fixture = window.fixture = {requests:[],opened:[],allowResearch:true,authority:'legacy'};
                      window.fetch = (input, options = {}) => {
                        const url = new URL(String(input), location.origin);
                        fixture.requests.push(url.pathname + url.search);
                        const response = body => new Response(JSON.stringify(body),
                          {status:200,headers:{'Content-Type':'application/json'}});
                        if (url.pathname === '/api/session') return Promise.resolve(response({session:{username:'alice',alias:'当前研究员'}}));
                        if (url.pathname === '/api/public/entry') return Promise.resolve(response({}));
                        if (url.pathname === '/api/research/capabilities/keycloak-sharing') return Promise.resolve(response({capabilities:{schema:'tr-research-keycloak-sharing-v1',authority:fixture.authority}}));
                        if (url.pathname === '/api/research/r1') return Promise.resolve(response({research:{
                          research_id:'r1',title:'研究甲',owner_ref:'alice',access:{can_view:fixture.allowResearch,can_manage:false}
                        }}));
                        if (url.pathname === '/api/research/r1/members') return Promise.resolve(response({members:[]}));
                        if (url.pathname === '/api/research/r1/workspaces') return Promise.resolve(response({workspaces:[]}));
                        if (url.pathname === '/api/research-evidence/catalog/research/r1') return Promise.resolve(response({catalog:{items:[],total:0}}));
                        const report = url.pathname === '/api/research/reports';
                        if (url.pathname !== '/api/research' && url.pathname !== '/api/research/r1/reports' && !report) throw Error('unexpected path: ' + url.pathname);
                        const row = report || url.pathname === '/api/research/r1/reports'
                          ? {report_id:'report-1',title:'报告甲：较长的研究标题在移动端应该完整地换行显示以避免内容被裁切',research_id:'r1',research_title:'研究甲',profile_ref:'self',profile_key:'local::alice::self',owner_ref:'alice',visibility:'private',updated_at:1700000000,
                             branches:[{publication_id:'branch-1',source_kind:'workspace',title:'高频时间维度因子复现与筛选报告（国债期货 T/TL）及多阶段研究成果',profile_ref:'researcher-with-long-name'}]}
                          : {research_id:'r1',title:'研究甲',owner_ref:'alice'};
                        const payload = report || url.pathname === '/api/research/r1/reports' ? {reports:[row]} : {researches:[row]};
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
                    page.get_by_role("button", name="查看 当前研究员 的信息").click()
                    opened = page.evaluate("window.fixture.opened")
                    assert opened[0]["kind"] == "profile" and opened[0]["ref"] == "self"
                    assert opened[0]["profileKey"] == "local::alice::self" and opened[0]["owner"] == "alice"
                    assert opened[1]["kind"] == "user" and opened[1]["ref"] == "alice"
                    page.get_by_role("button", name="报告甲：较长的研究标题在移动端应该完整地换行显示以避免内容被裁切", exact=True).click()
                    detail = page.get_by_test_id("detail")
                    detail.get_by_role("combobox", name="报告版本").wait_for()
                    assert detail.locator('.tr-report-source-picker').evaluate(
                        'node => node.scrollWidth <= node.clientWidth + 1')
                    assert detail.evaluate('node => node.scrollWidth <= node.clientWidth + 1')
                    assert page.get_by_role('dialog').count() == 0
                    detail.get_by_role("button",name="返回研究列表",exact=True).click()
                    page.evaluate("window.fixture.authority='keycloak'; window.fixture.setLanguage('en')")
                    assert page.get_by_role("tab", name="Reports").is_visible()
                    page.wait_for_function("!document.body.innerText.includes('Only me')")
                    page.evaluate("window.fixture.authority='legacy'; window.fixture.setLanguage('zh')")
                    page.get_by_role("button", name="研究甲", exact=True).click()
                    page.get_by_test_id("detail").wait_for()
                    assert "/api/research/r1" in page.evaluate("window.fixture.requests")
                    detail = page.get_by_test_id("detail")
                    for label in ("详情", "研究报告", "证据", "研究身份", "研究工作区"):
                        assert detail.get_by_role("tab", name=label, exact=True).is_visible()
                    assert detail.get_by_role("button", name="打开编辑器").count() == 0
                    assert detail.locator('iframe[src*="/researches/"]').count() == 0
                    page.wait_for_function("window.fixture.context()?.researchId === 'r1'")
                    assert page.evaluate("window.fixture.context().section") == "details"
                    page.screenshot(path=str(tmp_path / f"research-{viewport['width']}.png"), animations="disabled")
                    for label, endpoint in (("研究报告", "/api/research/r1/reports"),
                                            ("证据", "/api/research-evidence/catalog/research/r1"),
                                            ("研究工作区", "/api/research/r1/workspaces")):
                        detail.get_by_role("tab", name=label, exact=True).click()
                        try:
                            page.wait_for_function("url => window.fixture.requests.some(r => r.startsWith(url))", arg=endpoint)
                        except Exception as exc:
                            raise AssertionError(f"viewport={viewport} tab={label} requests={page.evaluate('window.fixture.requests')}") from exc
                    detail.get_by_role("tab",name="研究身份").click()
                    page.wait_for_function("window.fixture.context()?.section === 'members'")
                    detail.get_by_role("button",name="返回研究列表",exact=True).click()
                    page.wait_for_function("window.fixture.context() === null")
                    page.get_by_role("button", name="研究甲", exact=True).first.click()
                    page.wait_for_function("window.fixture.context()?.section === 'details'")
                    detail.get_by_role("button",name="返回研究列表",exact=True).click()
                    page.wait_for_function("window.fixture.context() === null")
                    page.evaluate("window.fixture.allowResearch = false")
                    page.get_by_role("button", name="研究甲", exact=True).first.click()
                    page.get_by_test_id("detail").wait_for()
                    page.wait_for_timeout(100)
                    assert page.evaluate("window.fixture.context()") is None
                    page.close()
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)
