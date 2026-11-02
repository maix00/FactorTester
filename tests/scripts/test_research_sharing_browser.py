"""Exercise the React research sharing controls without touching real users."""

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


def test_research_sharing_uses_keycloak_only_routes_and_confirms_claim(tmp_path):
    harness, bundle = tmp_path / "harness.tsx", tmp_path / "harness.js"
    harness.write_text(
        f"""
import React, {{useState}} from {json.dumps(str(APP / "node_modules/react/index.js"))};
import {{createRoot}} from {json.dumps(str(APP / "node_modules/react-dom/client.js"))};
import {{ResearchSharing}} from {json.dumps(str(APP / "src/components/research-sharing.tsx"))};
import {{ResearchShareRedeemer}} from {json.dumps(str(APP / "src/components/research-share-redeemer.tsx"))};
import {{captureResearchShare}} from {json.dumps(str(APP / "src/research-share-intent.ts"))};
import {{AuthGate}} from {json.dumps(str(APP / "src/auth.tsx"))};
import {{ObjectReferenceContext}} from {json.dumps(str(APP / "src/components/object-reference.tsx"))};
import {{bindNotificationSink}} from {json.dumps(str(APP / "src/notifications/core.ts"))};
import i18n from {json.dumps(str(APP / "src/i18n.ts"))};
import {json.dumps(str(APP / "src/shell.css"))};
bindNotificationSink((notice, done) => {{window.fixture.notices.push(notice); done();}});
window.fixture.setLanguage = language => i18n.changeLanguage(language);
captureResearchShare();
function App() {{
  const [target,setTarget] = useState('research');
  return <AuthGate><ObjectReferenceContext.Provider value={{value => window.fixture.opened.push(value)}}>
    <button onClick={{() => setTarget('research')}}>Research fixture</button>
    <button onClick={{() => setTarget('report')}}>Report fixture</button>
    <ResearchSharing key={{target}} target={{target === 'report' ? {{researchId:'r1',reportId:'p1'}} : {{researchId:'r1'}}}} />
    <ResearchShareRedeemer />
  </ObjectReferenceContext.Provider></AuthGate>;
}}
createRoot(document.getElementById('root')!).render(<App />);
""",
        encoding="utf-8",
    )
    subprocess.run(
        [
            str(APP / "node_modules/.bin/esbuild"),
            str(harness),
            "--bundle",
            "--format=iife",
            "--target=es2020",
            f"--outfile={bundle}",
        ],
        cwd=APP,
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / "index.html").write_text(
        '<link rel="stylesheet" href="/harness.css"><div id="root"></div>',
        encoding="utf-8",
    )
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                for viewport in (
                    {"width": 1440, "height": 900},
                    {"width": 390, "height": 844},
                ):
                    page = browser.new_page(viewport=viewport, locale="zh-CN")
                    page.set_default_timeout(5000)
                    page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                    page.evaluate("""() => {
                      const f = window.fixture = {requests:[],notices:[],opened:[],mode:'ok',grants:[],links:[]};
                      window.fetch = (input, options={}) => {
                        const url = new URL(String(input), location.origin), method = options.method || 'GET';
                        const body = options.body ? JSON.parse(options.body) : null;
                        f.requests.push({path:url.pathname,query:url.search,method,body});
                        const result = (data, status=200) => Promise.resolve(new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}}));
                        if (url.pathname === '/api/session') return result({session:{username:'alice'}});
                        if (url.pathname === '/api/public/entry') return result({});
                        if (url.pathname === '/api/research/principals') return result({principals:[{principal_ref:'bob',label:'bob'}]});
                        if (url.pathname === '/api/research/r1/keycloak-sharing-capabilities') {
                          if (f.mode === 'legacy') return result({success:false,error:'migration required',code:'keycloak_sharing_unavailable'},409);
                          if (f.mode === 'missing') return result({success:false,error:'not found'},404);
                          if (f.mode === 'denied') return result({success:true,capabilities:{schema:'tr-research-keycloak-target-sharing-v1',authority:'keycloak',research_id:'r1',target_kind:url.searchParams.get('target_kind'),report_id:url.searchParams.get('report_id'),can_manage_grants:false,can_manage_links:false}});
                          return result({success:true,capabilities:{schema:'tr-research-keycloak-target-sharing-v1',authority:'keycloak',research_id:'r1',target_kind:url.searchParams.get('target_kind'),report_id:url.searchParams.get('report_id'),can_manage_grants:true,can_manage_links:true}});
                        }
                        if (url.pathname === '/api/research/r1/keycloak-grants') {
                          if(method==='GET')return result({success:true,grants:f.grants});
                          f.grants=body.scopes.length?[{identity_id:'id-bob',username:body.principal_ref,enabled:true,scopes:body.scopes}]:[];
                          return result({success:true,grant:{}});
                        }
                        if (url.pathname === '/api/research/r1/keycloak-share-links') {
                          if(method==='GET')return result({success:true,share_links:f.links.filter(row=>row.target_kind===url.searchParams.get('target_kind') && row.report_id===url.searchParams.get('report_id'))});
                          const row={link_id:'link-1',target_kind:body.target_kind,report_id:body.report_id,mode:body.mode,expires_at:body.expires_at,revoked_at:0,token:'abcdefghijklmnopqrstuvwxyz_1234567890'};
                          f.links=[row];return result({success:true,share_link:row},201);
                        }
                        if (url.pathname === '/api/research/r1/keycloak-share-links/link-1' && method==='PATCH') {f.links[0].revoked_at=1;return result({success:true});}
                        if (url.pathname === '/api/research/keycloak-share-links/redeem')return result({success:true,grant:{research_id:'r1',target_kind:'research'}});
                        throw new Error('Unexpected request '+url.pathname);
                      };
                    }""")
                    page.add_script_tag(path=str(bundle))
                    page.get_by_text(
                        "这里仅显示对此对象直接授予用户的权限", exact=False
                    ).wait_for()
                    page.get_by_role("combobox", name="用户名").fill("bob")
                    page.get_by_role("checkbox", name="使用").check()
                    page.get_by_role("button", name="授予权限").click()
                    page.get_by_role("button", name="查看 bob 的信息").first.wait_for()
                    post = page.evaluate(
                        "window.fixture.requests.find(r => r.path.endsWith('/keycloak-grants') && r.method==='POST')"
                    )
                    assert post["body"] == {
                        "target_kind": "research",
                        "report_id": "",
                        "principal_ref": "bob",
                        "scopes": ["read", "use"],
                    }
                    page.get_by_role("button", name="查看 bob 的信息").last.click()
                    assert page.evaluate("window.fixture.opened.at(-1).ref") == "bob"
                    page.get_by_role("button", name="撤销", exact=True).first.click()
                    page.get_by_text("撤销该用户的直接授权？").wait_for()
                    page.locator(
                        ".ant-popconfirm-buttons:visible button.ant-btn-primary"
                    ).click()
                    page.wait_for_function("window.fixture.grants.length===0")
                    page.get_by_role("tab", name="分享链接").click()
                    page.get_by_role("button", name="创建链接").click()
                    page.get_by_label("链接仅在创建时显示，请及时复制").wait_for()
                    url = page.get_by_label(
                        "链接仅在创建时显示，请及时复制"
                    ).input_value()
                    assert "#research_share=" in url and "?research_share=" not in url
                    page.get_by_role("button", name="撤销", exact=True).first.click()
                    assert page.get_by_text(
                        "撤销后不能再领取；已领取的权限保留。"
                    ).is_visible()
                    page.locator(
                        ".ant-popconfirm-buttons:visible button.ant-btn-primary"
                    ).click()
                    page.get_by_text("已撤销", exact=True).wait_for()
                    if viewport["width"] < 600:
                        assert page.locator(".tr-research-sharing:visible").evaluate(
                            "el => el.scrollWidth <= el.clientWidth + 2"
                        )
                    screenshot_dir = Path("/tmp/tr-object-ui-qa")
                    screenshot_dir.mkdir(exist_ok=True)
                    page.screenshot(
                        path=str(
                            screenshot_dir / f"research-sharing-{viewport['width']}.png"
                        )
                    )
                    page.get_by_role("button", name="Report fixture").click()
                    page.get_by_role("combobox", name="用户名").fill("bob")
                    page.get_by_role("button", name="授予权限").click()
                    page.wait_for_function(
                        "window.fixture.requests.some(r => r.path.endsWith('/keycloak-grants') && r.method==='POST' && r.body.target_kind==='report' && r.body.report_id==='p1')"
                    )
                    page.get_by_role("tab", name="分享链接").click()
                    page.get_by_role("button", name="创建链接").click()
                    page.wait_for_function(
                        "window.fixture.requests.some(r => r.path.endsWith('/keycloak-share-links') && r.method==='POST' && r.body.target_kind==='report' && r.body.report_id==='p1')"
                    )
                    page.evaluate("window.fixture.setLanguage('en')")
                    page.get_by_role("tab", name="Share links").wait_for()
                    page.evaluate("window.fixture.setLanguage('zh')")
                    page.evaluate("window.fixture.mode='legacy'")
                    page.get_by_role("button", name="Research fixture").click()
                    page.get_by_text("研究权限尚未迁移到 Keycloak").wait_for()
                    assert page.get_by_role("button", name="授予权限").count() == 0
                    assert not page.evaluate(
                        "window.fixture.requests.some(r => /\\/share-links(?:\\/|$)/.test(r.path) && !r.path.includes('keycloak-share-links'))"
                    )
                    page.evaluate("window.fixture.mode='missing'")
                    page.get_by_role("button", name="Report fixture").click()
                    page.get_by_text("研究或报告不可用，或服务器尚不支持 Keycloak 权限设置。").wait_for()
                    # A claim token lives in a fragment, is removed from the address,
                    # survives a reload in this tab, and is not redeemed implicitly.
                    page.evaluate("window.fixture.mode='ok'")
                    page.goto(
                        f"http://127.0.0.1:{server.server_port}/index.html#research_share=abcdefghijklmnopqrstuvwxyz_1234567890"
                    )
                    claim_fixture = """() => {
                      const f=window.fixture={requests:[],notices:[],opened:[]};
                      window.fetch=(input,options={})=>{const url=new URL(String(input),location.origin);const method=options.method||'GET';
                        const body=options.body?JSON.parse(options.body):null;f.requests.push({path:url.pathname,method,body});
                        const result=(data,status=200)=>Promise.resolve(new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}}));
                        if(url.pathname==='/api/session')return result({session:{username:'alice',alias:'Alice Display'}});
                        if(url.pathname==='/api/public/entry')return result({});
                        if(url.pathname.endsWith('/keycloak-sharing-capabilities'))return result({success:false,code:'keycloak_sharing_unavailable'},409);
                        if(url.pathname==='/api/research/keycloak-share-links/redeem')return result({success:true,grant:{research_id:'r1',target_kind:'research'}});
                        throw Error('unexpected '+url.pathname);};
                    }"""
                    page.evaluate(claim_fixture)
                    page.add_script_tag(path=str(bundle))
                    page.get_by_role("dialog", name="领取研究分享").wait_for()
                    assert page.get_by_text("当前账号：Alice Display (alice)").is_visible()
                    assert "research_share" not in page.url
                    assert not page.evaluate(
                        "window.fixture.requests.some(r => r.path.endsWith('/redeem'))"
                    )
                    page.reload()
                    page.evaluate(claim_fixture)
                    page.add_script_tag(path=str(bundle))
                    page.get_by_role("dialog", name="领取研究分享").wait_for()
                    assert not page.evaluate(
                        "window.fixture.requests.some(r => r.path.endsWith('/redeem'))"
                    )
                    page.get_by_role("button", name="确认领取").click()
                    page.get_by_role("dialog", name="领取研究分享").wait_for(
                        state="hidden"
                    )
                    assert (
                        page.evaluate(
                            "window.fixture.requests.find(r => r.path.endsWith('/redeem')).body.token"
                        )
                        == "abcdefghijklmnopqrstuvwxyz_1234567890"
                    )
                    assert (
                        page.evaluate(
                            "sessionStorage.getItem('tr.research.share.pending')"
                        )
                        is None
                    )
                    page.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_research_creation_uses_the_authoritative_mode(tmp_path):
    harness, bundle = tmp_path / "create.tsx", tmp_path / "create.js"
    harness.write_text(
        f"""
import React, {{useState}} from {json.dumps(str(APP / "node_modules/react/index.js"))};
import {{createRoot}} from {json.dumps(str(APP / "node_modules/react-dom/client.js"))};
import {{ResearchCreate}} from {json.dumps(str(APP / "src/components/research-create.tsx"))};
import {{bindNotificationSink}} from {json.dumps(str(APP / "src/notifications/core.ts"))};
import {json.dumps(str(APP / "src/i18n.ts"))};
import {json.dumps(str(APP / "src/shell.css"))};
bindNotificationSink((notice, done) => {{window.fixture.notices.push(notice); done();}});
function App() {{const [version,setVersion]=useState(0);return <><button onClick={{()=>setVersion(v=>v+1)}}>Reset fixture</button><ResearchCreate key={{version}} onClose={{()=>{{}}}} onCreated={{value=>window.fixture.created.push(value)}} /></>;}}
createRoot(document.getElementById('root')!).render(<App />);
""",
        encoding="utf-8",
    )
    subprocess.run(
        [
            str(APP / "node_modules/.bin/esbuild"),
            str(harness),
            "--bundle",
            "--format=iife",
            "--target=es2020",
            f"--outfile={bundle}",
        ],
        cwd=APP,
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / "index.html").write_text(
        '<link rel="stylesheet" href="/create.css"><div id="root"></div>',
        encoding="utf-8",
    )
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                for viewport in (
                    {"width": 1440, "height": 900},
                    {"width": 390, "height": 844},
                ):
                    page = browser.new_page(viewport=viewport, locale="zh-CN")
                    page.set_default_timeout(5000)
                    page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                    page.evaluate("""() => {
                      const f=window.fixture={mode:'keycloak',calls:[],created:[],notices:[],switchBeforePost:false};
                      window.fetch=(input,options={})=>{const u=new URL(String(input),location.origin),method=options.method||'GET',body=options.body?JSON.parse(options.body):null;
                        f.calls.push({path:u.pathname,method,body});const res=(v,s=200)=>Promise.resolve(new Response(JSON.stringify(v),{status:s,headers:{'Content-Type':'application/json'}}));
                        if(u.pathname==='/api/client/profiles')return res({profiles:[]});
                        if(u.pathname==='/api/research/capabilities/keycloak-sharing')return res({capabilities:{schema:'tr-research-keycloak-sharing-v1',authority:f.mode,create_research:f.mode==='keycloak'}});
                        if(u.pathname==='/api/research/keycloak-create')return f.switchBeforePost?res({success:false,error:'not enabled',code:'keycloak_research_creation_unavailable'},409):res({success:true,research:{research_id:'new',title:body.title}},201);
                        if(u.pathname==='/api/research')return res({success:true,research:{research_id:'legacy',title:body.title}},201);
                        throw Error('unexpected '+u.pathname);};
                    }""")
                    page.add_script_tag(path=str(bundle))
                    page.get_by_text("新研究默认仅自己可见", exact=False).wait_for()
                    assert page.get_by_role("combobox", name="可见范围").count() == 0
                    page.get_by_role("textbox", name="名称").fill("因子研究")
                    page.get_by_role(
                        "button", name="新建研究", exact=True
                    ).click()
                    page.wait_for_function("window.fixture.created.length===1")
                    call = page.evaluate(
                        "window.fixture.calls.find(c => c.path.endsWith('/keycloak-create'))"
                    )
                    assert (
                        call["body"]["visibility"] == "private"
                        and call["body"]["authorized_users"] == []
                    )
                    assert not page.evaluate(
                        "window.fixture.calls.some(c => c.path==='/api/research' && c.method==='POST')"
                    )
                    page.evaluate("window.fixture.switchBeforePost=true")
                    page.get_by_role(
                        "button", name="新建研究", exact=True
                    ).click()
                    page.wait_for_function(
                        "window.fixture.notices.some(n => n.code==='research.create.failed')"
                    )
                    assert page.evaluate("window.fixture.created.length") == 1
                    assert not page.evaluate(
                        "window.fixture.calls.some(c => c.path==='/api/research' && c.method==='POST')"
                    )
                    page.evaluate(
                        "window.fixture.mode='legacy'; window.fixture.switchBeforePost=false"
                    )
                    page.get_by_role("button", name="Reset fixture").evaluate(
                        "button => button.click()"
                    )
                    page.get_by_role("combobox", name="可见范围").wait_for()
                    page.get_by_role("textbox", name="名称").fill("旧服务器研究")
                    page.get_by_role(
                        "button", name="新建研究", exact=True
                    ).click()
                    page.wait_for_function("window.fixture.created.length===2")
                    assert page.evaluate(
                        "window.fixture.calls.some(c => c.path==='/api/research' && c.method==='POST')"
                    )
                    page.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
