"""Responsive settings behavior with a simulated native bridge; not native sign-in verification."""
from __future__ import annotations
import json
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
APP=ROOT/"web/app"


def test_manager_connection_settings(tmp_path):
    source,bundle=tmp_path/"harness.tsx",tmp_path/"harness.js"
    source.write_text(f"""
import React from {json.dumps(str(APP/'node_modules/react/index.js'))};
import {{createRoot}} from {json.dumps(str(APP/'node_modules/react-dom/client.js'))};
import {{SettingsOverlay}} from {json.dumps(str(APP/'src/components/settings-overlay.tsx'))};
import {{MobileSettingDetail}} from {json.dumps(str(APP/'src/pages/mobile-settings.tsx'))};
import {{AuthGate}} from {json.dumps(str(APP/'src/auth.tsx'))};
import {json.dumps(str(APP/'src/i18n.ts'))};
import {json.dumps(str(APP/'src/shell.css'))};
createRoot(document.getElementById('root')!).render(<AuthGate>{{window.fixture.mobile?<MobileSettingDetail section="server"/>:<SettingsOverlay open onClose={{()=>{{}}}} onResetLayout={{()=>{{}}}}/>}}</AuthGate>);
""",encoding="utf-8")
    subprocess.run([str(APP/"node_modules/.bin/esbuild"),str(source),"--bundle","--format=iife","--target=es2020",f"--outfile={bundle}"],cwd=APP,check=True,capture_output=True,text=True)
    (tmp_path/"index.html").write_text('<link rel="stylesheet" href="/harness.css"><div id="root"></div>',encoding="utf-8")
    (tmp_path/"favicon.ico").write_bytes(b"")
    server=ThreadingHTTPServer(("127.0.0.1",0),partial(SimpleHTTPRequestHandler,directory=str(tmp_path)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(channel="chrome",headless=True)
            try:
                cases=[("browser",False,"unauthorized"),("unsupported",False,"unauthorized"),("native",False,"unauthorized"),("native",True,"unavailable")]
                for mode,mobile,state in cases:
                    page=browser.new_page(viewport={"width":390,"height":844} if mobile else {"width":1440,"height":900},locale="zh-CN");page.set_default_timeout(8000)
                    page_errors=[]
                    page.on("pageerror",lambda error:page_errors.append(str(error)))
                    page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                    page.evaluate("""([mode,mobile,state])=>{
                      const f=window.fixture={mobile,calls:[],requests:[]};
                      const ok=x=>({success:true,schema:'tr-manager-bridge:v1',...x});
                      const handlers={tradeResearchAuthentication:{postMessage(){}}};
                      if(mode==='native')handlers.tradeResearchManager={postMessage(m){f.calls.push(m);if(m.action==='capabilities')return Promise.resolve(ok({actions:['current','switch']}));if(m.action==='current')return Promise.resolve(ok({url:'https://old.test',auth_state:'authorized'}));if(m.action==='switch')return Promise.resolve(ok({url:m.url,auth_state:state}));throw Error('unexpected');}};
                      if(mode!=='browser')window.webkit={messageHandlers:handlers};
                      window.fetch=(input,options={})=>{const path=new URL(String(input),location.origin).pathname;f.requests.push({path,method:options.method||'GET'});const result=value=>Promise.resolve(new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}}));
                        if(path==='/api/session')return result({session:{username:'alice'}});if(path==='/api/public/entry')return result({});if(path==='/api/server/network-info')return result({server_id:'fixture',manager_port:7998});throw Error('unexpected request');};
                    }""",[mode,mobile,state])
                    page.add_script_tag(path=str(bundle))
                    if not mobile:page.get_by_role("button",name="服务器",exact=True).click()
                    page.get_by_role("heading",name="Manager 连接").wait_for()
                    if mode=="browser":page.get_by_text("网页由当前地址提供。",exact=False).wait_for()
                    elif mode=="unsupported":page.get_by_text("当前客户端暂不支持在此切换 Manager。",exact=True).wait_for()
                    else:
                        address=page.get_by_label("目标 Manager 地址")
                        page.screenshot(path=str(Path('/tmp')/f'tr-manager-settings-form-fixture-{int(mobile)}.png'))
                        address.fill("https://user:secret@new.test")
                        page.get_by_role("button",name="切换 Manager").click()
                        page.get_by_text("请输入不含凭据、查询参数或片段的 HTTP(S) 地址。",exact=True).wait_for()
                        assert page.evaluate("window.fixture.calls.filter(x=>x.action==='switch').length")==0
                        address.fill("https://new.test")
                        page.get_by_role("button",name="切换 Manager").click()
                        if state=="unauthorized":page.get_by_text("当前登录已清除；客户端正在打开目标服务器的登录页。",exact=True).wait_for()
                        else:page.get_by_text("暂时无法验证目标服务器；客户端正在打开目标地址。",exact=True).wait_for()
                        assert page.evaluate("window.fixture.calls.filter(x=>x.action==='switch')")==[{"action":"switch","url":"https://new.test"}]
                        assert not page.evaluate("window.fixture.requests.some(x=>x.method!=='GET')")
                        page.screenshot(path=str(Path('/tmp')/f'tr-manager-settings-fixture-{int(mobile)}.png'))
                    assert not page_errors
                    page.close()
            finally:browser.close()
    finally:server.shutdown();server.server_close();thread.join(timeout=2)
