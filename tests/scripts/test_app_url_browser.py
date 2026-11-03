"""Exercise clean URLs with real React navigation and browser history."""
import json
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'web/app'


def test_app_intent_configuration_history_and_refresh(tmp_path):
    source = tmp_path / 'harness.tsx'
    source.write_text('''
import React,{useEffect} from REACT;
import {createRoot} from DOM;
import {PageInstanceProvider} from INSTANCE;
import {useConfigurationNavigation} from NAV;
import {cleanAppURL,appEntrySearch} from ROUTE;
import {appCatalogLink} from LINK;
function Page(){
 const {view,navigate,back}=useConfigurationNavigation();
 useEffect(()=>{cleanAppURL();window.intent=appCatalogLink(appEntrySearch());},[]);
 return <><output>{view.page}</output><button onClick={()=>navigate({page:'settings'})}>Settings</button><button onClick={back}>Back</button></>;
}
createRoot(document.getElementById('root')!).render(<PageInstanceProvider value={{id:'fixture',pageId:'test-bench',mobile:true,args:{},open:()=>{}}}><Page/></PageInstanceProvider>);
'''.replace('REACT', json.dumps(str(APP/'node_modules/react/index.js')))
        .replace('DOM', json.dumps(str(APP/'node_modules/react-dom/client.js')))
        .replace('INSTANCE',json.dumps(str(APP/'src/page-instance.ts')))
        .replace('NAV',json.dumps(str(APP/'src/configuration/navigation.ts')))
        .replace('ROUTE',json.dumps(str(APP/'src/app-route.ts')))
        .replace('LINK',json.dumps(str(APP/'src/app-link.ts'))))
    subprocess.run([str(APP/'node_modules/.bin/esbuild'),str(source),'--bundle','--format=iife',f'--outfile={tmp_path / "harness.js"}'],check=True,capture_output=True)
    (tmp_path/'app').write_text('<div id="root"></div><script src="/harness.js"></script>')
    class Handler(SimpleHTTPRequestHandler):
        extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '': 'text/html'}
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(tmp_path)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page(viewport={'width':390,'height':844})
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                base=f'http://127.0.0.1:{server.server_port}/app'
                page.goto(base+'?page=factors&object_ref=factor%3Av2%3Aexample&owner_username=alice&tr_config=field&workspace_id=draft#unused')
                page.wait_for_function("location.pathname==='/app' && !location.search && !location.hash")
                assert page.locator('output').inner_text()=='field'
                assert page.evaluate('window.intent.args.catalogRef')=='factor:v2:example'
                page.get_by_role('button',name='Settings',exact=True).click()
                page.wait_for_function("document.querySelector('output').textContent==='settings'")
                assert page.url==base
                page.reload()
                page.wait_for_function("document.querySelector('output').textContent==='settings'")
                page.get_by_role('button',name='Back',exact=True).click()
                page.wait_for_function("document.querySelector('output').textContent==='field'")
                assert page.url==base
                page.go_forward()
                page.wait_for_function("document.querySelector('output').textContent==='settings'")
                assert page.url==base
                assert not errors
            finally:browser.close()
    finally:server.shutdown();server.server_close();thread.join(timeout=5)


def test_logged_out_entry_hides_query_and_preserves_login_destination(tmp_path):
    from urllib.parse import urlparse, parse_qs
    subprocess.run([str(APP/'node_modules/.bin/esbuild'),str(APP/'src/desktop-entry.tsx'),
                    '--bundle','--format=iife',f'--outfile={tmp_path / "entry.js"}'],check=True,capture_output=True)
    (tmp_path/'app').write_text('<div data-tr-web-app></div><script src="/entry.js"></script>')
    class Handler(SimpleHTTPRequestHandler):
        extensions_map={**SimpleHTTPRequestHandler.extensions_map,'':'text/html'}
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(tmp_path)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page(locale='zh-CN')
                page.route('**/api/session',lambda route:route.fulfill(status=401,json={}))
                page.route('**/api/public/entry',lambda route:route.fulfill(json={'authentication_provider':'keycloak'}))
                destinations=[]
                def login(route):
                    destinations.append(route.request.url)
                    route.fulfill(content_type='text/html',body='Organization login')
                page.route('**/auth/oidc/start?*',login)
                base=f'http://127.0.0.1:{server.server_port}/app'
                page.goto(base+'?page=factors&object_ref=factor%3Av2%3Aexample&auth_error=access_denied')
                page.get_by_role('button',name='使用组织账户继续').wait_for()
                assert page.url==base
                assert 'auth_error' not in page.evaluate('history.state.trEntrySearch')
                page.get_by_role('button',name='使用组织账户继续').click()
                page.wait_for_url('**/auth/oidc/start?*')
                target=parse_qs(urlparse(destinations[0]).query)['next'][0]
                assert target.startswith('/app?page=factors&object_ref=')
                assert 'auth_error' not in target
            finally:browser.close()
    finally:server.shutdown();server.server_close();thread.join(timeout=5)
