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
import {{ResearchPage}} from {json.dumps(str(APP / 'src/pages/research.tsx'))};
import {{PageInstanceProvider}} from {json.dumps(str(APP / 'src/page-instance.ts'))};
import {{AuthGate}} from {json.dumps(str(APP / 'src/auth.tsx'))};
import {json.dumps(str(APP / 'src/i18n.ts'))};
import {json.dumps(str(APP / 'src/shell.css'))};
createRoot(document.getElementById('root')!).render(<AuthGate><PageInstanceProvider value={{{{
  id:'fixture',pageId:'research',mobile:window.fixture.mobile,args:{{}},active:true,open:()=>{{}}
}}}}><ResearchPage /></PageInstanceProvider></AuthGate>);
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
                      const f=window.fixture={mobile:false,nativeCalls:[],requests:[],created:null,first:true};
                      const row=(id,title,profile='p1')=>({research_id:id,profile_id:profile,title,description:'fixture',created_at:1720000000,updated_at:1720000000});
                      const ok=x=>({success:true,schema:'tr-local-research-bridge:v1',...x});
                      const bridge={postMessage(m){f.nativeCalls.push(m);
                        if(m.action==='capabilities')return Promise.resolve(ok({binding:{issuer:'https://identity.test/realm',identity_id:'identity-1'},actions:['list','get','create'],profiles:[{profile_id:'p1',display_name:'自有身份'},{profile_id:'p2',display_name:'第二身份'}]}));
                        if(m.action==='list'){const rows=m.profile_id==='p1'?[row('r1','本机样本'),row('synced','同步样本'),...(f.created?[f.created]:[])]:[...(f.created?[f.created]:[])].filter(x=>x.profile_id==='p2');return Promise.resolve(ok({researches:rows.slice(m.offset,m.offset+m.limit),next_offset:null}));}
                        if(m.action==='get')return Promise.resolve(ok({research:row(m.research_id,'本机样本',m.profile_id)}));
                        if(m.action==='create'){if(!f.created)f.created={...row('new-local',m.title,m.profile_id),description:m.description}; if(f.first){f.first=false;return Promise.reject(Error('fixture lost acknowledgement'));} return Promise.resolve(ok({research:f.created}));}
                        throw Error('unexpected native action');}};
                      const other={postMessage(){return Promise.resolve({});}};
                      window.webkit={messageHandlers:nativeOnly?{tradeResearchLocalResearch:bridge}:{factorTesterLocalRun:other,factorTesterLocalCatalog:other,tradeResearchLocalResearch:bridge}};
                      window.fetch=(input,options={})=>{const u=new URL(String(input),location.origin);f.requests.push({path:u.pathname,method:options.method||'GET'});
                        const res=value=>Promise.resolve(new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}}));
                        if(u.pathname==='/api/session')return res({session:{username:'alice',keycloak_issuer:'https://identity.test/realm',tr_identity_id:'identity-1',keycloak_subject:'alice-sub'}});
                        if(u.pathname==='/api/public/entry')return res({});
                        if(u.pathname==='/api/client/profiles')return res({profiles:[]});
                        if(u.pathname==='/api/research/capabilities/keycloak-sharing')return res({capabilities:{schema:'tr-research-keycloak-sharing-v1',authority:'keycloak',create_research:true}});
                        if(u.pathname==='/api/research')return res({researches:[{research_id:'server-r',title:'服务器样本',owner_ref:'alice'},{research_id:'synced',title:'同步样本',owner_ref:'alice'}]});
                        throw Error('unexpected request '+u.pathname);};
                    }""",native_only)
                    page.add_script_tag(path=str(bundle))
                    page.get_by_text("本机样本",exact=True).wait_for()
                    page.get_by_text("服务器样本",exact=True).wait_for()
                    assert page.get_by_role("button",name="同步样本",exact=True).count()==1
                    assert page.get_by_text("本机 / 服务器",exact=True).is_visible()
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
                    if viewport["width"] < 600: page.get_by_role("button",name="返回").last.click()
                    else: page.locator(".ant-modal-close").last.click()
                    page.get_by_role("button",name="新建研究").click()
                    page.locator(".ant-dropdown:visible").get_by_role("menuitem",name="本机",exact=True).last.click()
                    page.get_by_label("名称",exact=True).fill("我的本机研究")
                    page.locator(".ant-modal").get_by_role("button",name="新建研究").click()
                    page.get_by_text("保存结果未确认",exact=False).wait_for()
                    page.locator(".ant-modal").get_by_role("button",name="新建研究").click()
                    page.get_by_text("我的本机研究",exact=True).wait_for()
                    calls=page.evaluate("window.fixture.nativeCalls.filter(x=>x.action==='create')")
                    assert len(calls)==2 and calls[0]["operation_id"]==calls[1]["operation_id"]
                    assert set(calls[0])=={"action","profile_id","title","description","operation_id"}
                    assert not page.evaluate("window.fixture.requests.some(x=>x.method!=='GET')")
                    page.get_by_role("button",name="新建研究").click()
                    page.locator(".ant-dropdown:visible").get_by_role("menuitem",name="服务器",exact=True).last.click()
                    page.get_by_role("dialog").get_by_role("button",name="新建研究").wait_for()
                    assert len(page.evaluate("window.fixture.nativeCalls.filter(x=>x.action==='create')"))==2
                    if viewport["width"] < 600: page.get_by_role("button",name="返回").last.click()
                    else: page.locator(".ant-modal-close").last.click()
                    assert page.locator(".tr-function-header h1").evaluate("e => e.getBoundingClientRect().width >= e.scrollWidth")
                    if viewport["width"] < 600:
                        assert page.locator(".tr-function-header h1").evaluate("e => {const a=e.getBoundingClientRect(),b=document.querySelector('.tr-function-actions').getBoundingClientRect();return a.right<=b.left || a.bottom<=b.top;}")
                    page.screenshot(path=str(Path('/tmp') / f'tr-local-research-fixture-{viewport["width"]}.png'))
                    assert page.get_by_text("服务器样本",exact=True).is_visible()
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
