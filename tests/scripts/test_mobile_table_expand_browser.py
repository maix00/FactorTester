"""Mobile table expansion retains the active column filter across rotation."""
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


def test_expand_table_with_filter_and_landscape(tmp_path):
    source, bundle = tmp_path / 'table.tsx', tmp_path / 'table.js'
    source.write_text(f'''
import React from {json.dumps(str(APP / 'node_modules/react/index.js'))};
import {{createRoot}} from {json.dumps(str(APP / 'node_modules/react-dom/client.js'))};
import {{TRDataTable}} from {json.dumps(str(APP / 'src/components/data-table.tsx'))};
import {{PageInstanceProvider}} from {json.dumps(str(APP / 'src/page-instance.ts'))};
import {json.dumps(str(APP / 'src/i18n.ts'))};
import {json.dumps(str(APP / 'src/shell.css'))};
const rows=[{{id:'a',kind:'甲'}},{{id:'b',kind:'乙'}}];
createRoot(document.getElementById('root')!).render(<PageInstanceProvider value={{{{id:'t',pageId:'t',mobile:true,args:{{}},open:()=>{{}}}}}}>
<TRDataTable clientFiltering rows={{rows}} rowKey="id" columns={{[{{title:'类别',key:'kind',dataIndex:'kind',filters:[{{text:'甲',value:'甲'}},{{text:'乙',value:'乙'}}],onFilter:(v,r)=>r.kind===v}}]}}
pagination={{{{page:1,pageSize:20,total:2,onChange:()=>{{}}}}}} /></PageInstanceProvider>);
''', encoding='utf-8')
    subprocess.run([str(APP / 'node_modules/.bin/esbuild'), str(source), '--bundle', '--format=iife',
                    '--target=es2020', f'--outfile={bundle}'], cwd=APP, check=True, capture_output=True, text=True)
    (tmp_path / 'index.html').write_text('<link rel="stylesheet" href="/table.css"><div id="root"></div>', encoding='utf-8')
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 844}, locale='zh-CN')
                page.set_default_timeout(8000)
                page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                page.add_script_tag(path=str(bundle))
                page.locator('.ant-table-filter-trigger').first.click()
                page.locator('.ant-dropdown:visible').get_by_text('甲', exact=True).click()
                page.locator('.ant-dropdown:visible .ant-table-filter-dropdown-btns button').last.click()
                assert page.get_by_role('cell', name='甲', exact=True).is_visible()
                assert page.get_by_role('cell', name='乙', exact=True).count() == 0
                page.get_by_role('button', name='放大表格').click()
                page.get_by_role('dialog').wait_for()
                page.set_viewport_size({'width': 844, 'height': 390})
                assert page.get_by_role('dialog').get_by_role('cell', name='甲', exact=True).is_visible()
                assert page.get_by_role('dialog').get_by_role('cell', name='乙', exact=True).count() == 0
                page.wait_for_timeout(350)
                page.screenshot(path='/tmp/tr-table-landscape-fixture.png')
                page.get_by_role('dialog').get_by_role('button', name='返回').click()
                page.get_by_role('dialog').wait_for(state='hidden')
                assert page.get_by_role('cell', name='甲', exact=True).is_visible()
                assert page.get_by_role('cell', name='乙', exact=True).count() == 0
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)
