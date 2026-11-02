"""The real Lightweight Charts renderer remains usable in a rotated panel."""
import json
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'web/app'


def test_market_chart_expands_landscape_without_device_rotation(tmp_path):
    source, bundle = tmp_path / 'chart.tsx', tmp_path / 'chart.js'
    source.write_text(f'''
import React from {json.dumps(str(APP / 'node_modules/react/index.js'))};
import {{createRoot}} from {json.dumps(str(APP / 'node_modules/react-dom/client.js'))};
import {{ProductDetailPage}} from {json.dumps(str(APP / 'src/pages/product-detail.tsx'))};
import {{PageInstanceProvider}} from {json.dumps(str(APP / 'src/page-instance.ts'))};
import {json.dumps(str(APP / 'src/i18n.ts'))};
import {json.dumps(str(APP / 'src/shell.css'))};
createRoot(document.getElementById('root')!).render(<PageInstanceProvider value={{{{id:'p',pageId:'p',mobile:true,args:{{productName:'T.CFE'}},open:()=>{{}}}}}}><ProductDetailPage /></PageInstanceProvider>);
''', encoding='utf-8')
    subprocess.run([str(APP / 'node_modules/.bin/esbuild'), str(source), '--bundle', '--format=iife',
                    '--target=es2020', f'--outfile={bundle}'], cwd=APP, check=True, capture_output=True, text=True)
    (tmp_path / 'index.html').write_text('<html class="tr-mobile-runtime"><link rel="stylesheet" href="/chart.css"><div id="root"></div></html>', encoding='utf-8')
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page(viewport={'width':390, 'height':844}, locale='zh-CN', has_touch=True)
                page.set_default_timeout(8000)
                assets = {'price-chart.js':ROOT / 'server/manager/web/core/price-chart.js',
                          'lightweight-charts.standalone.production.js':ROOT / 'static/vendor/lightweight-charts/lightweight-charts.standalone.production.js',
                          'chart-workbench.js':ROOT / 'static/vendor/chart-workbench/chart-workbench.js'}
                page.route('**/research-static/**', lambda route: route.fulfill(path=str(assets[route.request.url.split('/')[-1]])))
                page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                page.evaluate('''() => { window.fetch = async input => {
                  const path=new URL(String(input),location.origin).pathname;
                  const data=Array.from({length:30},(_,i)=>({timestamp:1704067200000+i*86400000,open:100+i,high:102+i,low:99+i,close:101+i,volume:1000+i,open_interest:3000+i}));
                  const value=path==='/api/market-data/prices'?{data,timezone:'Asia/Shanghai',has_oi:true,data_source:'fixture',freq:'DAY1'}:{targets:[],fields:{},contracts:[]};
                  return new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});
                }; }''')
                page.add_script_tag(path=str(bundle))
                page.locator('.ft-lightweight-price-canvas canvas').first.wait_for()
                page.get_by_role('button', name='全屏').click()
                dialog = page.get_by_role('dialog')
                dialog.locator('.ft-lightweight-price-canvas canvas').first.wait_for()
                assert page.viewport_size == {'width':390, 'height':844}
                assert dialog.locator('.ant-modal-content').evaluate('el => el.clientWidth > el.clientHeight')
                page.wait_for_function('''() => {
                  const el=document.querySelector('.tr-landscape-table-modal .ant-modal');
                  return el && getComputedStyle(el).opacity === '1';
                }''')
                page.screenshot(path='/tmp/tr-mobile-chart-landscape.png')
                page.mouse.click(200, 400)
                detail = dialog.locator('.ft-lightweight-price-detail')
                detail.wait_for(state='visible')
                assert '2024/1/16' in detail.inner_text()
                detail.get_by_role('button', name='关闭').click()
                page.mouse.move(200, 400); page.mouse.wheel(0, -500)
                # Lightweight Charts treats two close clicks as a double click.
                page.wait_for_timeout(550)
                page.mouse.click(200, 400)
                detail.wait_for(state='visible')
                before_drag = detail.inner_text()
                detail.get_by_role('button', name='关闭').click()
                page.mouse.move(200, 400); page.mouse.down(); page.mouse.move(200, 520, steps=8); page.mouse.up()
                page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
                page.mouse.click(200, 400)
                detail.wait_for(state='visible')
                assert detail.inner_text() != before_drag
                after_drag = detail.inner_text()
                detail.get_by_role('button', name='关闭').click()
                page.touchscreen.tap(200, 400)
                detail.wait_for(state='visible')
                assert detail.inner_text() == after_drag
                dialog.get_by_role('button', name='返回').click()
                dialog.wait_for(state='hidden')
                page.locator('.ft-lightweight-price-canvas canvas').first.wait_for()
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)
