"""Device status presentation with a simulated Manager response, not live authorization."""
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


def test_device_authorization_status_and_mobile_layout(tmp_path):
    source, bundle = tmp_path / 'devices.tsx', tmp_path / 'devices.js'
    source.write_text(f'''
import React from {json.dumps(str(APP / 'node_modules/react/index.js'))};
import {{createRoot}} from {json.dumps(str(APP / 'node_modules/react-dom/client.js'))};
import {{DeviceSettings}} from {json.dumps(str(APP / 'src/components/device-settings.tsx'))};
import {{PageInstanceProvider}} from {json.dumps(str(APP / 'src/page-instance.ts'))};
import {json.dumps(str(APP / 'src/i18n.ts'))};
import {json.dumps(str(APP / 'src/shell.css'))};
const mobile=innerWidth<600, scope=location.search.includes('admin=1')?'admin':'self';
createRoot(document.getElementById('root')!).render(<PageInstanceProvider value={{{{id:'devices',pageId:'devices',mobile,args:{{}},open:()=>{{}}}}}}><DeviceSettings scope={{scope}} /></PageInstanceProvider>);
''', encoding='utf-8')
    subprocess.run([str(APP / 'node_modules/.bin/esbuild'), str(source), '--bundle', '--format=iife',
                    '--target=es2020', f'--outfile={bundle}'], cwd=APP, check=True, capture_output=True, text=True)
    (tmp_path / 'index.html').write_text('<link rel="stylesheet" href="/devices.css"><div id="root"></div>', encoding='utf-8')
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            try:
                for width, height in ((1440, 900), (390, 844)):
                    page = browser.new_page(viewport={'width': width, 'height': height}, locale='zh-CN')
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                    page.evaluate('''() => { window.fetch = async () => new Response(JSON.stringify({success:true, devices:[
                      {device_id:'device-authorized-01',device_name:'工作电脑',client_type:'swift',enabled:true,keycloak_authorized:true},
                      {device_id:'device-denied-00001',device_name:'手机',client_type:'mobile',enabled:true,keycloak_authorized:false},
                      {device_id:'device-unknown-0001',device_name:'旧设备',client_type:'browser',enabled:true},
                      {device_id:'device-revoked-001',device_name:'已撤销设备',client_type:'browser',enabled:false}
                    ]}), {status:200,headers:{'Content-Type':'application/json'}}); }''')
                    page.add_script_tag(path=str(bundle))
                    for name, state in (('工作电脑', '已授权'), ('手机', '未授权'), ('旧设备', '授权未核验'), ('已撤销设备', '已撤销')):
                        row = page.get_by_role('row').filter(has_text=name)
                        row.get_by_text(state, exact=True).wait_for()
                    search = page.get_by_label('搜索我的设备').bounding_box()
                    reload = page.get_by_role('button', name='重新读取').bounding_box()
                    assert search and reload and abs((search['y'] + search['height']/2) - (reload['y'] + reload['height']/2)) < 2
                    assert reload['x'] + reload['width'] <= width + 1
                    if width < 600:
                        status = page.get_by_role('row').filter(has_text='旧设备').get_by_text('授权未核验', exact=True).bounding_box()
                        assert status and status['x'] + status['width'] <= width + 1
                    page.screenshot(path=str(tmp_path / f'devices-list-{width}.png'))
                    page.get_by_role('button', name='手机', exact=True).click()
                    page.get_by_role('dialog').get_by_text('未授权', exact=True).wait_for()
                    assert not errors
                    page.wait_for_timeout(350)
                    page.screenshot(path=str(tmp_path / f'devices-{width}.png'))
                    page.close()
                page = browser.new_page(viewport={'width': 1440, 'height': 900}, locale='zh-CN')
                page.set_default_timeout(8000)
                page.goto(f'http://127.0.0.1:{server.server_port}/index.html?admin=1')
                page.evaluate('''() => { window.fetch = async input => {
                  const path = new URL(String(input),location.origin).pathname;
                  const value = path === '/api/admin/users' ? {success:true,users:[{username:'alice',alias:'Alice'}]} :
                    {success:true,devices:[{device_id:'device-admin-00001',username:'alice',device_name:'Alice 电脑',client_type:'swift',enabled:true,keycloak_authorized:true}]};
                  return new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});
                }; }''')
                page.add_script_tag(path=str(bundle))
                page.get_by_role('combobox', name='搜索机构或层级范围内的用户').click()
                page.locator('.ant-select-dropdown:visible .ant-select-item-option-content').first.click()
                page.get_by_role('row').filter(has_text='Alice 电脑').get_by_text('授权未核验', exact=True).wait_for()
                page.close()
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)
