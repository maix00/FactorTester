"""React local research UX using a clearly synthetic native bridge, never the real store."""
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


def test_local_research_capability_and_idempotent_retry(tmp_path):
    harness, bundle = tmp_path / "harness.tsx", tmp_path / "harness.js"
    harness.write_text(f"""
import React from {json.dumps(str(APP / 'node_modules/react/index.js'))};
import {{createRoot}} from {json.dumps(str(APP / 'node_modules/react-dom/client.js'))};
import {{ResearchDetailPage}} from {json.dumps(str(APP / 'src/pages/research-detail.tsx'))};
import {{ResearchPage}} from {json.dumps(str(APP / 'src/pages/research.tsx'))};
import {{PageInstanceProvider}} from {json.dumps(str(APP / 'src/page-instance.ts'))};
import {{AuthGate}} from {json.dumps(str(APP / 'src/auth.tsx'))};
import {json.dumps(str(APP / 'src/i18n.ts'))};
import {json.dumps(str(APP / 'src/shell.css'))};
function Harness() {{
 const [current,setCurrent]=React.useState(null);
 return <AuthGate><PageInstanceProvider value={{{{id:'fixture',pageId:'research',mobile:window.fixture.mobile,args:{{}},active:!current,
  open:(pageId,args)=>setCurrent(args)}}}}><div hidden={{!!current}}><ResearchPage/></div></PageInstanceProvider>
  {{current?<PageInstanceProvider value={{{{id:'fixture-detail',pageId:'research-detail',mobile:window.fixture.mobile,args:current,active:true,open:(pageId,args)=>setCurrent(args),back:()=>setCurrent(null)}}}}>
   <button onClick={{()=>setCurrent(null)}}>返回研究列表</button><ResearchDetailPage/>
  </PageInstanceProvider>:null}}</AuthGate>;
}}
createRoot(document.getElementById('root')!).render(<Harness/>);
""", encoding="utf-8")
    subprocess.run([str(APP / "node_modules/.bin/esbuild"), str(harness), "--bundle", "--format=iife",
                    "--target=es2020", f"--outfile={bundle}"], cwd=APP, check=True, capture_output=True, text=True)
    (tmp_path / "index.html").write_text('<link rel="stylesheet" href="/harness.css"><div id="root"></div>', encoding="utf-8")
    (tmp_path / "favicon.ico").write_bytes(b"")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                for viewport,native_only in [({"width":1440,"height":900},False),({"width":390,"height":844},False),({"width":1440,"height":900},True)]:
                    page = browser.new_page(viewport=viewport, locale="zh-CN"); page.set_default_timeout(8000)
                    page_errors=[]
                    page.on("pageerror",lambda error:page_errors.append(str(error)))
                    page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                    page.evaluate("""nativeOnly => {
                      const f=window.fixture={mobile:false,nativeCalls:[],nativeAuth:[],requests:[],created:null,serverNew:null,first:true};
                      const row=(id,title,profile='p1')=>({research_id:id,profile_id:profile,title,description:'fixture',created_at:1720000000,updated_at:1720000000});
                      const ok=x=>({success:true,schema:'tr-local-research-bridge:v1',...x});
                      const bridge={postMessage(m){f.nativeCalls.push(m);
                        if(m.action==='capabilities')return Promise.resolve(ok({binding:{issuer:'https://identity.test/realm',identity_id:'identity-1'},actions:['list','get','create','import_research','import_catalog_report','list_profile_reports','queue_researches'],profiles:[{profile_id:'p1',display_name:'自有身份'},{profile_id:'p2',display_name:'第二身份'},{profile_id:'self',display_name:'本人'}]}));
                        if(m.action==='list'){const rows=m.profile_id==='p1'?[row('r1','本机样本'),row('synced','同步样本'),...(f.created?[f.created]:[])]:m.profile_id==='p2'?[row('synced','同步样本','p2')]:m.profile_id==='self'&&f.serverNew?[row(f.serverNew.research_id,f.serverNew.title,'self')]:[...(f.created?[f.created]:[])].filter(x=>x.profile_id===m.profile_id);return Promise.resolve(ok({researches:rows.slice(m.offset,m.offset+m.limit),next_offset:null}));}
                        if(m.action==='import_research')return Promise.resolve(ok({research:row(m.research_id,f.serverNew.title,'self'),status:'imported'}));
                        if(m.action==='list_profile_reports')return Promise.resolve(ok({reports:[],revision:1,next_offset:null}));
                        if(m.action==='import_catalog_report')return Promise.resolve(ok({report:{report_id:m.report_id,research_id:m.research_id,profile_id:m.profile_id,title:'服务器报告',created_at:1720000000},status:'imported'}));
                        if(m.action==='queue_researches')return Promise.resolve(ok({queued:m.research_ids.length}));
                        if(m.action==='get')return Promise.resolve(ok({research:row(m.research_id,'本机样本',m.profile_id)}));
                        if(m.action==='create'){if(!f.created)f.created={...row('new-local',m.title,m.profile_id),description:m.description}; if(f.first){f.first=false;return Promise.reject(Error('fixture lost acknowledgement'));} return Promise.resolve(ok({research:f.created}));}
                        throw Error('unexpected native action');}};
                      const other={postMessage(){return Promise.resolve({});}};
                      const auth={postMessage(m){f.nativeAuth.push(m);}};
                      window.webkit={messageHandlers:nativeOnly?{tradeResearchLocalResearch:bridge,tradeResearchAuthentication:auth}:{factorTesterLocalRun:other,factorTesterLocalCatalog:other,tradeResearchLocalResearch:bridge,tradeResearchAuthentication:auth}};
                      window.fetch=(input,options={})=>{const u=new URL(String(input),location.origin);f.requests.push({path:u.pathname,method:options.method||'GET'});
                        const res=value=>Promise.resolve(new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}}));
                        if(u.pathname==='/api/session')return res({session:{username:'alice',keycloak_issuer:'https://identity.test/realm',tr_identity_id:'identity-1',keycloak_subject:'alice-sub'}});
                        if(u.pathname==='/api/public/entry')return res({});
                        if(u.pathname==='/api/client/profiles')return res({profiles:[]});
                        if(u.pathname==='/api/research/capabilities/keycloak-sharing')return res({capabilities:{schema:'tr-research-keycloak-sharing-v1',authority:'keycloak',create_research:true}});
                        if(u.pathname==='/api/research')return res({researches:[{research_id:'server-r',title:'服务器样本',owner_ref:'alice'},{research_id:'synced',title:'同步样本',owner_ref:'alice'},{research_id:'research:v1:SSSSSSSSSSSSSSSSSSSSSSSS',title:'已有服务器研究',owner_ref:'alice',is_owned:true,access:{can_view:true}},...(f.serverNew?[f.serverNew]:[])]});
                        if(u.pathname==='/api/research/reports')return res({reports:[{report_id:'report:v1:RRRRRRRRRRRRRRRRRRRRRRRR',research_id:'research:v1:RRRRRRRRRRRRRRRRRRRRRRRR',title:'服务器报告',owner_ref:'alice',research_title:'新服务器研究'}]});
                        if(u.pathname==='/api/research/keycloak-create'){f.serverNew={research_id:'research:v1:RRRRRRRRRRRRRRRRRRRRRRRR',title:'新服务器研究',owner_ref:'alice',access:{can_view:true}};return res({research:f.serverNew});}
                        if(u.pathname.startsWith('/api/research/research%3Av1%3A')&&u.pathname.endsWith('/reports'))return res({reports:[{report_id:'report:v1:RRRRRRRRRRRRRRRRRRRRRRRR',research_id:'research:v1:RRRRRRRRRRRRRRRRRRRRRRRR',title:'服务器报告',owner_ref:'alice'}]});
                        if(u.pathname.startsWith('/api/research/research%3Av1%3A'))return res({research:f.serverNew});
                        throw Error('unexpected request '+u.pathname);};
                    }""",native_only)
                    page.add_script_tag(path=str(bundle))
                    page.get_by_text("本机样本",exact=True).wait_for()
                    assert page.evaluate("window.fixture.nativeAuth.some(x=>x.action==='session-updated')")
                    page.get_by_text("服务器样本",exact=True).wait_for()
                    page.wait_for_function("window.fixture.nativeCalls.some(x=>x.action==='queue_researches' && x.research_ids.includes('research:v1:SSSSSSSSSSSSSSSSSSSSSSSS'))")
                    assert page.get_by_role("button",name="同步样本",exact=True).count()==2
                    copies=page.locator(".ant-table-row").filter(has=page.get_by_role("button",name="同步样本",exact=True))
                    assert copies.count()==2
                    assert copies.nth(0).get_by_text("自有身份",exact=True).count()==1
                    assert copies.nth(1).get_by_text("第二身份",exact=True).count()==1
                    assert len(set(copies.evaluate_all("rows => rows.map(row=>row.dataset.rowKey)")))==2
                    assert page.get_by_text("本机 / 服务器",exact=True).count()==2
                    page.screenshot(path=str(Path('/tmp') / f'tr-multiple-profile-directory-{viewport["width"]}.png'))
                    copies.nth(1).get_by_role("button",name="第二身份",exact=True).click()
                    page.get_by_role("dialog").get_by_text("p2",exact=True).wait_for()
                    if viewport["width"] < 600: page.get_by_role("button",name="返回").last.click()
                    else: page.locator(".ant-modal-close").last.click()
                    assert page.get_by_role("radiogroup",name="位置").count()==0
                    page.locator("th").filter(has_text="位置").locator(".ant-table-filter-trigger").first.click()
                    page.locator(".ant-dropdown:visible").get_by_text("本机",exact=True).click()
                    page.locator(".ant-dropdown:visible .ant-table-filter-dropdown-btns button").last.click()
                    assert page.get_by_text("本机样本",exact=True).is_visible()
                    assert page.get_by_text("服务器样本",exact=True).count()==0
                    page.locator("th").filter(has_text="位置").locator(".ant-table-filter-trigger").first.click()
                    page.locator(".ant-dropdown:visible .ant-table-filter-dropdown-btns button").first.click()
                    page.locator(".ant-dropdown:visible .ant-table-filter-dropdown-btns button").last.click()
                    page.get_by_text("服务器样本",exact=True).wait_for()
                    page.get_by_role("button",name="本机样本").click()
                    page.get_by_text("r1",exact=True).wait_for()
                    assert not page.evaluate("window.fixture.requests.some(x=>x.path==='/api/research/r1')")
                    page.get_by_role("button",name="返回研究列表",exact=True).click()
                    page.get_by_role("button",name="新建研究").click()
                    page.locator(".ant-dropdown:visible").get_by_role("menuitem",name="本机",exact=True).last.click()
                    page.get_by_label("名称",exact=True).fill("我的本机研究")
                    page.locator(".ant-modal").get_by_role("button",name="新建研究").click()
                    page.get_by_text("保存结果未确认",exact=False).wait_for()
                    page.locator(".ant-modal").get_by_role("button",name="新建研究").click()
                    page.get_by_role("heading",name="我的本机研究",exact=True).wait_for()
                    calls=page.evaluate("window.fixture.nativeCalls.filter(x=>x.action==='create')")
                    assert len(calls)==2 and calls[0]["operation_id"]==calls[1]["operation_id"]
                    assert set(calls[0])=={"action","profile_id","title","description","operation_id"}
                    assert not page.evaluate("window.fixture.requests.some(x=>x.method!=='GET')")
                    page.get_by_role("button",name="返回研究列表",exact=True).click()
                    page.get_by_role("button",name="新建研究").click()
                    page.locator(".ant-dropdown:visible").get_by_role("menuitem",name="服务器",exact=True).last.click()
                    page.get_by_role("dialog").get_by_role("button",name="新建研究").wait_for()
                    assert len(page.evaluate("window.fixture.nativeCalls.filter(x=>x.action==='create')"))==2
                    page.get_by_role("dialog").get_by_label("名称",exact=True).fill("新服务器研究")
                    page.get_by_role("dialog").get_by_role("button",name="新建研究").click()
                    page.wait_for_function("window.fixture.nativeCalls.some(x=>x.action==='import_research' && x.profile_id==='self')")
                    page.get_by_role("button",name="返回研究列表",exact=True).click()
                    page.get_by_text("本机 / 服务器",exact=True).first.wait_for()
                    assert page.locator(".tr-function-header h1").evaluate("e => e.getBoundingClientRect().width >= e.scrollWidth")
                    if viewport["width"] < 600:
                        assert page.locator(".tr-function-header h1").evaluate("e => {const a=e.getBoundingClientRect(),b=document.querySelector('.tr-function-actions').getBoundingClientRect();return a.right<=b.left || a.bottom<=b.top;}")
                    page.get_by_role("tab", name="研究报告").click()
                    page.get_by_role("button", name="服务器报告").click()
                    page.get_by_role("button", name="同步主分支到本机").click()
                    page.wait_for_function("window.fixture.nativeCalls.some(x=>x.action==='import_catalog_report')")
                    page.wait_for_function("!document.querySelector('.ant-btn-loading')")
                    page.wait_for_timeout(500)  # Allow the overlay transition to finish before visual evidence.
                    page.screenshot(path=str(Path('/tmp') / f'tr-local-research-fixture-{viewport["width"]}.png'))
                    assert page.get_by_role("heading",name="服务器报告",exact=True).is_visible()
                    assert not page_errors
                    page.close()
                for mode in ["wrong-issuer","wrong-identity","missing-identity"]:
                    page=browser.new_page(viewport={"width":1440,"height":900},locale="zh-CN");page.set_default_timeout(8000)
                    page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                    page.evaluate("""mode=>{
                      const f=window.fixture={mobile:false,calls:[]};const other={postMessage(){return Promise.resolve({});}};
                      const bridge={postMessage(m){f.calls.push(m);return Promise.resolve({success:true,schema:'tr-local-research-bridge:v1',binding:{issuer:mode==='wrong-issuer'?'https://other.test':'https://identity.test',identity_id:mode==='wrong-identity'?'other':'identity-1'},actions:['list','get','create'],profiles:[{profile_id:'p1',display_name:'身份'}]});}};
                      window.webkit={messageHandlers:{factorTesterLocalRun:other,factorTesterLocalCatalog:other,tradeResearchLocalResearch:bridge}};
                      window.fetch=input=>{const path=new URL(String(input),location.origin).pathname;const res=x=>Promise.resolve(new Response(JSON.stringify(x),{status:200,headers:{'Content-Type':'application/json'}}));
                        if(path==='/api/session')return res({session:{username:'alice',keycloak_issuer:'https://identity.test',tr_identity_id:mode==='missing-identity'?'':'identity-1'}});
                        if(path==='/api/public/entry')return res({});if(path==='/api/research')return res({researches:[]});
                        if(path==='/api/research/capabilities/keycloak-sharing')return res({capabilities:{schema:'tr-research-keycloak-sharing-v1',authority:'keycloak',create_research:true}});throw Error('unexpected');};
                    }""",mode)
                    page.add_script_tag(path=str(bundle))
                    page.get_by_role("tab",name="研究工作区",exact=True).wait_for()
                    assert page.get_by_role("button",name="新建本机研究").count()==0
                    calls=page.evaluate("window.fixture.calls")
                    assert all(call["action"]=="capabilities" for call in calls)
                    if mode=="missing-identity":assert not calls
                    page.close()
            finally: browser.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)
