"""Ionic header actions remain available with a phone-sized viewport."""
from __future__ import annotations

import json
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
                  const body=p==='/api/session'?{session:{username:'alice'}}:p==='/api/client/profiles'?{profiles:[]}:{items:[]};
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
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)
