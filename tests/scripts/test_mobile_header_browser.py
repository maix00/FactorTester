"""Ionic header actions remain available with a phone-sized viewport."""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'web/app'


def test_mobile_header_notifications_and_assistant(tmp_path):
    source, bundle = tmp_path / 'harness.tsx', tmp_path / 'harness.js'
    source.write_text(f'''
import React from {json.dumps(str(APP / 'node_modules/react/index.js'))};
import {{createRoot}} from {json.dumps(str(APP / 'node_modules/react-dom/client.js'))};
import {{MobileShell}} from {json.dumps(str(APP / 'src/mobile-shell.tsx'))};
import {{AuthGate}} from {json.dumps(str(APP / 'src/auth.tsx'))};
import {{setupIonicReact}} from {json.dumps(str(APP / 'node_modules/@ionic/react/dist/index.js'))};
import {json.dumps(str(APP / 'src/i18n.ts'))};
import {json.dumps(str(APP / 'node_modules/@ionic/react/css/core.css'))};
import {json.dumps(str(APP / 'node_modules/@ionic/react/css/structure.css'))};
import {json.dumps(str(APP / 'src/shell.css'))};
setupIonicReact({{mode:'md'}});
createRoot(document.getElementById('root')!).render(<AuthGate><MobileShell /></AuthGate>);
''', encoding='utf-8')
    subprocess.run([str(APP / 'node_modules/.bin/esbuild'), str(source), '--bundle', '--format=iife',
                    '--target=es2020', f'--outfile={bundle}'], cwd=APP, check=True, capture_output=True, text=True)
    (tmp_path / 'index.html').write_text('<link rel="stylesheet" href="/harness.css"><div id="root"></div>', encoding='utf-8')
    images = tmp_path / 'research-static/vendor/web-app'
    images.mkdir(parents=True)
    shutil.copyfile(ROOT / 'static/vendor/web-app/network-topology.zh.svg', images / 'network-topology.zh.svg')
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 844}, locale='zh-CN')
                page.set_default_timeout(8000)
                page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                page.evaluate('''() => {window.fetch = input => {const p=new URL(String(input),location.origin).pathname;
                  const body=p==='/api/session'?{session:{username:'alice'}}:p==='/api/client/profiles'?{profiles:[]}:
                    p==='/api/docs/index'?{sections:[{title:'Guide',pages:[{slug:'network-topology',title:'网络拓扑'},
                      {slug:'identity-permissions',title:'用户与权限'}]}]}:
                    p==='/api/docs/pages/network-topology'?{title:'网络拓扑',html:'<p>Topology article</p>'}:
                    p==='/api/docs/pages/identity-permissions'?{title:'用户与权限',html:'<h2 id="identity">用户与权限</h2><a href="#section">Section</a><p id="section">Permission article</p>'}:{items:[]};
                  return Promise.resolve(new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}}));};}''')
                page.add_script_tag(path=str(bundle))
                header = page.locator('ion-header.tr-mobile-header')
                header.wait_for()
                assert header.locator('ion-title').inner_text().strip()
                notifications = header.get_by_role('button', name='通知中心')
                assistant = header.get_by_role('button', name='打开智能体助手')
                notifications.wait_for(state='visible')
                assistant.wait_for(state='visible')
                notifications.click()
                page.locator('ion-modal').wait_for(state='visible')
                page.keyboard.press('Escape')
                assistant.click()
                page.locator('.ant-drawer-open').wait_for(state='visible')
                page.wait_for_timeout(350)
                page.screenshot(path='/tmp/tr-mobile-header-fixture.png')
                page.go_back()
                page.locator('.ant-drawer-open').wait_for(state='hidden')
                assert header.is_visible()
                assistant.click()
                page.locator('.ant-drawer-open').wait_for(state='visible')
                page.locator('.ant-drawer-open .ant-drawer-close').click()
                page.locator('.ant-drawer-open').wait_for(state='hidden')
                assert header.is_visible()
                page.locator('ion-tab-button[tab="more"]').click()
                page.get_by_role('button', name='技术文档').click()
                page.get_by_text('Topology article').wait_for()
                page.get_by_role('tab', name='用户与权限').click()
                page.get_by_text('Permission article').wait_for()
                assert page.locator('article h2').filter(has_text='用户与权限').count() == 1
                page.get_by_role('link', name='Section').click()
                assert page.evaluate('location.hash') == '#section'
                page.go_back()
                page.get_by_text('Permission article').wait_for()
                page.go_back()
                page.get_by_text('Topology article').wait_for()
                assert header.locator('ion-title').inner_text().strip() == '技术文档'
                page.screenshot(path='/tmp/tr-mobile-docs-return.png')
                header.get_by_role('button', name='返回').click()
                page.get_by_role('button', name='alice').click()
                page.get_by_role('menuitem', name='设置').click()
                page.get_by_role('button', name='语言').click()
                language = page.get_by_role('combobox', name='语言')
                language.wait_for(state='attached')
                assert language.evaluate('(element) => getComputedStyle(element).fontSize') == '16px'
                language.click(force=True)
                page.get_by_text('English', exact=True).wait_for(state='visible')
                assert header.get_by_role('button', name='返回').is_visible()
                # Ant Design renders dialogs outside the mobile shell. The
                # focusable elements there need the same iOS protection.
                sizes = page.evaluate('''() => {
                  const container=document.createElement('div');
                  container.innerHTML='<input style="font-size:12px"><textarea style="font-size:12px"></textarea><select style="font-size:12px"><option>A</option></select>';
                  document.body.append(container);
                  const result=Array.from(container.children, node => getComputedStyle(node).fontSize);
                  container.remove(); return result;
                }''')
                assert sizes == ['16px', '16px', '16px']
                page.set_viewport_size({'width': 1024, 'height': 844})
                desktop_size = page.evaluate('''() => {
                  const field=document.createElement('input'); field.style.fontSize='12px';
                  document.body.append(field); const size=getComputedStyle(field).fontSize; field.remove(); return size;
                }''')
                assert desktop_size == '12px'
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)
