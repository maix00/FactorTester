"""Report edits must use the current chapter and preserve the reading position."""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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
import {json.dumps(str(APP / 'src/i18n.ts'))};
import {json.dumps(str(APP / 'src/shell.css'))};
function App() {{
  const [revision,setRevision] = useState(0);
  const [chapter,setChapter] = useState('');
  return <><ReportBranchReader key={{`reader:${{revision}}`}} target={{{{publication_id:'p1',source_kind:'publication'}}}}
    initialChapterID={{chapter}} onChapterChange={{setChapter}} />
    <ReportEditor key="editor" publicationID="p1" onUpdated={{() => setRevision(value => value + 1)}} /></>;
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
                    page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                    page.evaluate("""() => {
                      window.fixture = {rev:'1-a', conflict:true, operations:[], chapters:[
                        {chapter_id:'c1',title:'第一章'},{chapter_id:'c2',title:'第二章'}],
                        components:{c1:[{component_id:'c1',kind:'chapter',parent_id:null},
                          {component_id:'p1',kind:'paragraph',parent_id:'c1',title:'原段落'}],
                          c2:[{component_id:'c2',kind:'chapter',parent_id:null}]}};
                      window.fetch = async (input, options = {}) => {
                        const url = String(input), f = window.fixture;
                        const response = (body,status=200) => new Response(JSON.stringify(body),
                          {status,headers:{'Content-Type':'application/json'}});
                        if (url === '/api/research-reports/p1') return response({document:{_rev:f.rev,projection_hash:'x'},access:{can_write:true}});
                        if (url === '/api/research-reports/p1/agent') return response({manifest:{chapters:f.chapters}});
                        if (url === '/api/research-reports/p1/attachments') return response({attachments:[]});
                        if (url.startsWith('/api/research-reports/p1/chapters/')) return response({chapter:{components:f.components[url.split('/').at(-1)]}});
                        if (url === '/api/public-research/p1/index') return response({chapters:f.chapters.map(c => ({component_id:c.chapter_id,title:c.title}))});
                        if (url.startsWith('/api/public-research/p1/chapters/')) return response({components:f.components[url.split('/').at(-1)]});
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
                    selection = reader.get_by_role("combobox", name="章节")
                    selection.focus(); selection.press("ArrowDown")
                    page.locator(".ant-select-dropdown:visible").get_by_text("第二章", exact=True).click()
                    page.get_by_role("button", name="编辑报告内容").click()
                    page.get_by_label("选择 原段落").wait_for(state="attached")
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
                    page.close()
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)
