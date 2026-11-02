"""Report edits must use the current chapter and preserve the reading position."""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import base64
import json
import subprocess
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "web/app"


def test_report_editor_recovers_after_conflict_without_duplicating_reader(tmp_path):
    harness = tmp_path / "harness.tsx"
    bundle = tmp_path / "harness.js"
    harness.write_text(f"""
import React, {{useState}} from {json.dumps(str(APP / 'node_modules/react/index.js'))};
import {{createRoot}} from {json.dumps(str(APP / 'node_modules/react-dom/client.js'))};
import {{ReportBranchReader}} from {json.dumps(str(APP / 'src/components/report-branch-reader.tsx'))};
import {{ReportEditor}} from {json.dumps(str(APP / 'src/components/report-editor.tsx'))};
import {{ReportMarkdown}} from {json.dumps(str(APP / 'src/components/report-markdown.tsx'))};
import {json.dumps(str(APP / 'src/i18n.ts'))};
import {json.dumps(str(ROOT / 'server/manager/web/styles/app.css'))};
import {json.dumps(str(APP / 'src/shell.css'))};
function App() {{
  const [revision,setRevision] = useState(0);
  const [chapter,setChapter] = useState('');
  return <><ReportBranchReader key={{`reader:${{revision}}`}} target={{{{publication_id:'p1',source_kind:'publication'}}}}
    initialChapterID={{chapter}} onChapterChange={{setChapter}} />
    <ReportEditor key="editor" publicationID="p1" onUpdated={{() => setRevision(value => value + 1)}} />
    <ReportMarkdown target={{{{publication_id:'p1',source_kind:'publication'}}}} /></>;
}}
createRoot(document.getElementById('root')!).render(<App />);
""", encoding="utf-8")
    subprocess.run([str(APP / "node_modules/.bin/esbuild"), str(harness), "--bundle",
                    "--format=iife", "--target=es2020", f"--outfile={bundle}"],
                   cwd=APP, check=True, capture_output=True, text=True)
    (tmp_path / "index.html").write_text('<link rel="stylesheet" href="/harness.css"><div id="root"></div>', encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                for viewport in ({"width": 1440, "height": 900}, {"width": 390, "height": 844}):
                    page = browser.new_page(viewport=viewport, locale="zh-CN")
                    page.set_default_timeout(5000)
                    image_id = "abcdef0123456789abcdef01"
                    image = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/aR0AAAAASUVORK5CYII=")
                    page.route(f"**/api/public-research/p1/local-resources/{image_id}*",
                               lambda route: route.fulfill(body=image, content_type="image/png"))
                    page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                    page.evaluate("""() => {
                      window.fixture = {rev:'1-a', conflict:true, operations:[], jobReads:[], editorReads:[], chapters:[
                        {chapter_id:'c1',title:'第一章：包含很长的国债期货因子研究与回测结果说明标题'}, {chapter_id:'c2',title:'第二章'}],
                        components:{c1:[{component_id:'c1',kind:'chapter',parent_id:null},
                          {component_id:'p1',kind:'paragraph',parent_id:'c1',title:'原段落',body:'![正文图](factortester-local://abcdef0123456789abcdef01)\\n\\n| 项 | 长内容 |\\n| --- | --- |\\n| 产品 | `Product/Futures/CNFutures/_products/T.CFE` |'},
                          {component_id:'job-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-result',kind:'special',display_kind:'test_result',parent_id:'c1',title:'测试运行结果'},
                          {component_id:'job-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb-result',kind:'special',display_kind:'test_result',parent_id:'c1',title:'来源未记录的任务'}],
                          c2:[{component_id:'c2',kind:'chapter',parent_id:null}]}};
                      window.EventSource = class {addEventListener() {} close() {}};
                      window.fetch = async (input, options = {}) => {
                        const url = String(input), f = window.fixture;
                        const response = (body,status=200) => new Response(JSON.stringify(body),
                          {status,headers:{'Content-Type':'application/json'}});
                        if (url === '/api/research-reports/p1') {f.editorReads.push(url);return response({document:{_rev:f.rev,projection_hash:'x'},access:{can_write:true}});}
                        if (url === '/api/research-reports/p1/agent') {f.editorReads.push(url);return response({manifest:{chapters:f.chapters}});}
                        if (url === '/api/research-reports/p1/attachments') return response({attachments:[]});
                        if (url === '/api/public-research/p1/export?format=md') return new Response('# Exported report', {status:200});
                        if (url.startsWith('/api/research-reports/p1/chapters/')) return response({chapter:{components:f.components[url.split('/').at(-1)]}});
                        if (url === '/api/public-research/p1/index') return response({chapters:f.chapters.map(c => ({component_id:c.chapter_id,title:c.title}))});
                        if (url.startsWith('/api/public-research/p1/chapters/')) return response({components:f.components[url.split('/').at(-1)],local_resources:[{resource_id:'abcdef0123456789abcdef01'}],bindings:[
                          {component_id:'job-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-result',kind:'job',target_ref:'job:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',data:{server_id:'manager-b',port:'8001'}}]});
                        if (url.startsWith('/api/jobs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')) {
                          f.jobReads.push(url);return response({task_detail:{job:{job_id:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',status:'running',kind:'backtest'}}});
                        }
                        if (url === '/api/research-reports/p1/operations') {
                          const payload = JSON.parse(options.body);
                          if (payload.base_rev !== f.rev) throw Error('stale revision sent');
                          if (f.conflict) {
                            f.conflict=false;f.rev='2-a';
                            f.components.c1.push({component_id:'p2',kind:'paragraph',parent_id:'c1',title:'并发更新'});
                            return response({success:false,error:'revision conflict'},409);
                          }
                          f.operations.push(payload.operation);
                          f.components.c1.push({...payload.operation.component,parent_id:payload.operation.parent_id});
                          f.rev='3-a';return response({success:true,rev:f.rev});
                        }
                        throw Error('unexpected request: '+url);
                      };
                    }""")
                    page.add_script_tag(path=str(bundle))
                    reader = page.locator(".tr-report-reading")
                    report_image = reader.locator('img[alt="正文图"]')
                    report_image.wait_for(state="visible")
                    report_image.evaluate("node => node.decode()")
                    assert report_image.evaluate("node => node.complete && node.naturalWidth === 1")
                    assert reader.locator('.tr-report-reading-choice .ant-select').evaluate(
                        'node => node.getBoundingClientRect().right <= node.closest(".tr-report-reading-toolbar").getBoundingClientRect().right')
                    assert reader.locator('.tr-report-reading-text table').evaluate(
                        'node => node.getBoundingClientRect().right <= node.closest(".tr-report-reading").getBoundingClientRect().right')
                    assert page.evaluate("window.fixture.editorReads.length") == 0
                    page.get_by_text("Markdown", exact=True).click()
                    page.get_by_text("# Exported report", exact=True).wait_for()
                    assert page.evaluate("window.fixture.jobReads.length") == 0
                    reader.get_by_text("测试运行结果", exact=True).click()
                    reader.locator(".tr-job-page-detail").wait_for()
                    reads = page.evaluate("window.fixture.jobReads")
                    assert len(reads) == 1 and "server_id=manager-b" in reads[0] and "port=8001" in reads[0]
                    assert reader.get_by_role("button", name="取消运行").count() == 0
                    reader.get_by_text("来源未记录的任务", exact=True).click()
                    reader.get_by_text("此任务的来源服务器或业务端口未记录，无法安全读取运行结果。").wait_for()
                    assert len(page.evaluate("window.fixture.jobReads")) == 1
                    reader.get_by_role("button", name="阅读设置").click()
                    font = page.get_by_role("combobox", name="字号")
                    font.focus(); font.press("ArrowDown")
                    page.locator(".ant-select-dropdown:visible").get_by_text("20 px", exact=True).click()
                    assert reader.locator("article").evaluate("node => getComputedStyle(node).fontSize") == "20px"
                    reader.get_by_role("button", name="阅读设置").click()
                    selection = reader.get_by_role("combobox", name="章节")
                    selection.focus(); selection.press("ArrowDown")
                    page.locator(".ant-select-dropdown:visible").get_by_text("第二章", exact=True).click()
                    page.get_by_role("button", name="编辑报告内容").click()
                    page.get_by_label("选择 原段落").wait_for(state="attached")
                    assert page.evaluate("window.fixture.editorReads.length") == 2
                    page.get_by_label("段落标题").fill("新增段落")
                    page.get_by_label("段落正文").fill("草稿")
                    page.get_by_role("button", name="添加段落").click()
                    page.get_by_text("报告刷新失败；操作可能已保存。请重新读取并核对后再继续。").wait_for()
                    assert page.get_by_label("段落正文").input_value() == "草稿"
                    page.get_by_role("button", name="重 试").click()
                    page.get_by_label("选择 并发更新").wait_for(state="attached")
                    page.get_by_role("button", name="已核对").click()
                    page.get_by_role("button", name="添加段落").click()
                    page.get_by_label("选择 新增段落").wait_for(state="attached")
                    operations = page.evaluate("window.fixture.operations")
                    assert len(operations) == 1
                    assert operations[0]["parent_id"] == "c1"
                    assert operations[0]["after_component_id"] == "p2"
                    assert operations[0]["component"]["body"] == "草稿"
                    assert page.locator(".tr-report-reading").count() == 1
                    assert page.locator(".tr-report-reading-choice .ant-select-selection-item").inner_text() == "第二章"
                    assert page.locator(".tr-report-reading article").evaluate("node => getComputedStyle(node).fontSize") == "20px"
                    page.close()
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)


def test_local_report_reader_uses_native_chapters_and_refreshes_after_edit(tmp_path):
    harness = tmp_path / 'local.tsx'
    bundle = tmp_path / 'local.js'
    harness.write_text(f'''
import React from {json.dumps(str(APP / 'node_modules/react/index.js'))};
import {{createRoot}} from {json.dumps(str(APP / 'node_modules/react-dom/client.js'))};
import {{LocalResearchDetail}} from {json.dumps(str(APP / 'src/components/local-research-page.tsx'))};
import {json.dumps(str(APP / 'src/i18n.ts'))};
import {json.dumps(str(ROOT / 'server/manager/web/styles/app.css'))};
import {json.dumps(str(APP / 'src/shell.css'))};
const research={{research_id:'r1',profile_id:'self',title:'本机研究',description:'',updated_at:1}};
const report={{report_id:'p1',research_id:'r1',profile_id:'self',title:'本机报告',created_at:1}};
const f={{generation:1,race:new URLSearchParams(location.search).has('race'),items:[{{component_id:'c1',kind:'chapter',parent_id:null,title:'第一章'}},
  {{component_id:'e1',kind:'entry',parent_id:'c1',title:'原段落',body:'本机保存的正文'}}]}};
const version=()=>({{generation:f.generation,root_ref:'root'+f.generation}});
const client={{snapshot:()=>1,isCurrent:()=>true,get:async()=>research,
  listReports:async()=>({{reports:[report],next_offset:null}}),
  getReport:async()=>({{report,chapters:[{{component_id:'c1',title:'第一章',preview:''}}],version:version()}}),
  getReportChapter:async()=>{{if(f.race){{f.race=false;f.generation++;}}return {{chapter_id:'c1',components:f.items,version:version()}};}},
  addReportComponent:async input=>{{f.items=[...f.items,{{component_id:input.componentId,kind:'entry',parent_id:'c1',title:input.title,body:input.body}}];f.generation++;return version();}}}};
createRoot(document.getElementById('root')!).render(<LocalResearchDetail client={{client as any}}
 capabilities={{{{actions:['get','list_reports','get_report','get_report_chapter','add_report_component'],profiles:[{{profile_id:'self',display_name:'Self'}}]}} as any}}
 item={{research as any}} initialReport={{report as any}} onClose={{()=>{{}}}} />);
''', encoding='utf-8')
    subprocess.run([str(APP / 'node_modules/.bin/esbuild'), str(harness), '--bundle',
                    '--format=iife', '--target=es2020', f'--outfile={bundle}'],
                   cwd=APP, check=True, capture_output=True, text=True)
    (tmp_path / 'index.html').write_text('<link rel="stylesheet" href="/local.css"><div id="root"></div><script src="/local.js"></script>', encoding='utf-8')
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            try:
                for viewport in ({'width': 1440, 'height': 900}, {'width': 390, 'height': 844}):
                    page = browser.new_page(viewport=viewport, locale='zh-CN')
                    page.set_default_timeout(5000)
                    page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                    reader = page.locator('.tr-report-reading')
                    reader.get_by_text('本机保存的正文').wait_for()
                    page.get_by_role('button', name='编辑报告内容').click()
                    page.get_by_label('段落标题').fill('新段落')
                    page.get_by_label('段落正文').fill('新写入的正文')
                    page.get_by_role('button', name='添加段落').click()
                    reader.get_by_text('新写入的正文').wait_for()
                    assert reader.count() == 1
                    assert reader.locator('.tr-report-reading-text p').get_by_text('本机保存的正文', exact=True).count() == 1
                    assert reader.locator('.ant-select-selection-item').inner_text() == '第一章'
                    page.close()
                page = browser.new_page(viewport={'width': 390, 'height': 844}, locale='zh-CN')
                page.set_default_timeout(5000)
                page.goto(f'http://127.0.0.1:{server.server_port}/index.html?race=1')
                reader = page.locator('.tr-report-reading')
                reader.get_by_text('报告已被其他操作修改，请重新读取并核对。').wait_for()
                assert reader.get_by_text('本机保存的正文').count() == 0
                reader.get_by_role('button', name='重 试').click()
                reader.get_by_text('本机保存的正文').wait_for()
                page.close()
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)


def test_local_report_reader_with_real_local_rpc(tmp_path):
    """Exercise the real local store and RPC; HTTP substitutes only for WebKit IPC."""
    from tools.cli.release.research_reporting.local_rpc import LocalResearchRPC

    rpc = LocalResearchRPC(tmp_path / 'store', issuer='https://id.test/realm', identity_id='stable',
                           profiles=[{'profile_id': 'self', 'display_name': 'Self'}])
    research = rpc.request({'action': 'create', 'profile_id': 'self', 'title': '本机研究',
                            'description': '', 'operation_id': 'research-create'})['research']
    report = rpc.request({'action': 'create_report', 'profile_id': 'self', 'research_id': research['research_id'],
                          'title': '本机报告', 'operation_id': 'report-create'})['report']
    base = {'profile_id': 'self', 'research_id': research['research_id'], 'report_id': report['report_id']}
    version = rpc.request({'action': 'get_report', **base})['version']
    version = rpc.request({'action': 'add_report_component', **base, 'component_id': 'chapter-1',
                           'kind': 'chapter', 'parent_id': '', 'title': '第一章', 'body': '', **version})['version']
    _report, root = rpc.store._report_root('self', research['research_id'], report['report_id'])
    image = root / 'figure.png'
    image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/aR0AAAAASUVORK5CYII='))
    rpc.request({'action': 'add_report_component', **base, 'component_id': 'entry-1',
                 'kind': 'entry', 'parent_id': 'chapter-1', 'title': '原段落',
                 'body': f'真实本机正文\n\n![图表]({image.as_uri()})\n\n[下载附件]({image.as_uri()})', **version})
    from tools.cli.release.research_reporting.assets import stage_branch_image
    from tools.cli.release.research_reporting.authoring.tree_model import add_asset, add_component
    asset = stage_branch_image(package_root=root, branch_id='main', source_path=image)
    add_asset(package_root=root, branch_id='main', asset=asset)
    add_component(package_root=root, branch_id='main', component_id='figure', kind='image',
                  title='结构图', parent_id='chapter-1', body='', content={'asset_ref': asset['asset_ref']}, display_kind='')

    harness = tmp_path / 'rpc.tsx'; bundle = tmp_path / 'rpc.js'
    harness.write_text(f'''
import React from {json.dumps(str(APP / 'node_modules/react/index.js'))};
import {{createRoot}} from {json.dumps(str(APP / 'node_modules/react-dom/client.js'))};
import {{localResearchBridge}} from {json.dumps(str(APP / 'src/local-research-bridge.ts'))};
import {{LocalResearchDetail}} from {json.dumps(str(APP / 'src/components/local-research-page.tsx'))};
import {json.dumps(str(APP / 'src/i18n.ts'))};
import {json.dumps(str(ROOT / 'server/manager/web/styles/app.css'))};
import {json.dumps(str(APP / 'src/shell.css'))};
const client=localResearchBridge({{webkit:{{messageHandlers:{{tradeResearchLocalResearch:{{postMessage:async (value:unknown)=>
  (await fetch('/rpc',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(value)}})).json()}}}}}}}})!;
const research={json.dumps(research, ensure_ascii=False)};
const report={json.dumps(report, ensure_ascii=False)};
void client.capabilities({{issuer:'https://id.test/realm',identity_id:'stable'}}).then(capabilities=>
  createRoot(document.getElementById('root')!).render(<LocalResearchDetail client={{client}}
    capabilities={{capabilities}} item={{research as any}}
    initialReport={{report as any}} onClose={{()=>{{}}}} />));
''', encoding='utf-8')
    subprocess.run([str(APP / 'node_modules/.bin/esbuild'), str(harness), '--bundle', '--format=iife',
                    '--target=es2020', f'--outfile={bundle}'], cwd=APP, check=True, capture_output=True, text=True)
    (tmp_path / 'index.html').write_text('<link rel="stylesheet" href="/rpc.css"><div id="root"></div><script src="/rpc.js"></script>', encoding='utf-8')

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs): super().__init__(*args, directory=str(tmp_path), **kwargs)
        def do_POST(self):
            if self.path != '/rpc': self.send_error(404); return
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 65536: self.send_error(400); return
            try: result = rpc.request(json.loads(self.rfile.read(size)))
            except (ValueError, TypeError, PermissionError): self.send_error(400); return
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 900}, locale='zh-CN')
                page.set_default_timeout(5000); page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                reader = page.locator('.tr-report-reading'); reader.get_by_text('真实本机正文').wait_for()
                chart = reader.locator('img[alt="图表"]'); chart.wait_for()
                assert (chart.get_attribute('src') or '').startswith('blob:'), chart.evaluate('node => node.outerHTML')
                assert chart.evaluate('node => node.decode().then(() => node.naturalWidth)') == 1
                structured = reader.locator('img[alt="结构图"]'); structured.wait_for()
                assert structured.evaluate('node => node.decode().then(() => node.naturalWidth)') == 1
                page.screenshot(path=str(tmp_path / 'local-report.png'))
                with page.expect_download() as download:
                    reader.get_by_role('button', name='下载附件').click()
                assert Path(download.value.path()).read_bytes() == image.read_bytes()
                page.get_by_role('button', name='编辑报告内容').click()
                page.get_by_label('段落标题').fill('新增段落'); page.get_by_label('段落正文').fill('真实写入正文')
                page.get_by_role('button', name='添加段落').click()
                reader.get_by_text('真实写入正文').wait_for()
                chapter = rpc.request({'action': 'get_report_chapter', **base, 'chapter_id': 'chapter-1'})['chapter']
                assert any(item['body'] == '真实写入正文' for item in chapter['components'])
                page.close()
            finally: browser.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)
