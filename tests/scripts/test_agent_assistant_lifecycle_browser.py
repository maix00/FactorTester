"""Closing one React assistant panel must not stop a shared Profile process."""

from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os
import subprocess
import threading

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "web/app"


def test_shared_assistant_panels_do_not_stop_profile_on_unmount(tmp_path):
    harness = tmp_path / "harness.tsx"
    bundle = tmp_path / "harness.js"
    harness.write_text(
        f"""
import React, {{useState}} from {json.dumps(str(APP / 'node_modules/react/index.js'))};
import {{createRoot}} from {json.dumps(str(APP / 'node_modules/react-dom/client.js'))};
import {{AgentAssistant}} from {json.dumps(str(APP / 'src/components/agent-assistant.tsx'))};
import {{assistantResearchContexts}} from {json.dumps(str(APP / 'src/assistant-research-context.ts'))};
import {json.dumps(str(APP / 'src/i18n.ts'))};
import {json.dumps(str(APP / 'src/shell.css'))};
window.fixture.setResearch = value => assistantResearchContexts.set('research-panel', value);
function App() {{
  const [first, setFirst] = useState(false);
  const [second, setSecond] = useState(false);
  return <><button id="first" onClick={{() => setFirst(value => !value)}}>first</button>
    <button id="second" onClick={{() => setSecond(value => !value)}}>second</button>
    {{first ? <AgentAssistant open presentation="panel" /> : null}}
    {{second ? <AgentAssistant open presentation="panel" /> : null}}</>;
}}
createRoot(document.getElementById("root")!).render(<App />);
""",
        encoding="utf-8",
    )
    subprocess.run(
        [str(APP / "node_modules/.bin/esbuild"), str(harness), "--bundle",
         "--format=iife", "--target=es2020", f"--outfile={bundle}"],
        cwd=APP, check=True, capture_output=True, text=True,
    )
    (tmp_path / "index.html").write_text('<link rel="stylesheet" href="/harness.css"><div id="root"></div>', encoding="utf-8")
    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page(locale="zh-CN")
                page.set_default_timeout(5000)
                page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                page.evaluate("""() => {
                  window.fixture = {running: false, starts: 0, stops: 0,
                                    disposed: 0, holdStart: false, release: null,
                                    workspaces:0, publishes:[], removes:[], releases:[], rpcs:[], contexts:[], allowResearch:true};
                  window.FTStaticLoader = {loadGroups: async () => {}};
                  window.FTAgentChat = {render: async (context, _profile, options) => {
                    window.fixture.contexts.push(context);
                    const root = document.createElement('div');
                    const host = document.createElement('div');
                    host.className = 'profile-chatkit-host agent-fixture-chat';
                    host.textContent = 'fixture conversation';
                    host.__ftBeforeTabSave = () => { window.fixture.disposed++; };
                    root.append(host); options.mountHost.replaceChildren(root); return root;
                  }};
                  window.fetch = async (input, options = {}) => {
                    const url = String(input);
                    let body;
                    if (url === '/api/client/profiles') body = {success: true, profiles: [{
                      profile_id: 'self', is_self_profile: true,
                      runtime: {runtime_kind: 'server', configured: true},
                      active_claim: {claim_id: 'fixture'},
                    }]};
                    else if (url.startsWith('/api/client/profile-agent?'))
                      body = {success: true, status: {running: window.fixture.running}};
                    else if (url === '/api/client/profile-agent/assistance/workspaces')
                      body = {success:true, workspace_id:`workspace-${++window.fixture.workspaces}`};
                    else if (url.startsWith('/api/client/profile-agent/assistance/workspaces?')) {
                      window.fixture.releases.push(url); body = {success:true};
                    }
                    else if (url === '/api/client/profile-agent/assistance/publish') {
                      const payload = JSON.parse(options.body), tab = payload.workspace.tabs[0];
                      window.fixture.publishes.push(payload);
                      body = {success:true,page:tab && window.fixture.allowResearch ? {tab_id:tab.tab_id,assistance:tab.assistance} : null};
                    } else if (url.startsWith('/api/client/profile-agent/assistance/page?')) {
                      window.fixture.removes.push(url); body = {success:true};
                    } else if (url === '/api/client/profile-agent/rpc') {
                      window.fixture.rpcs.push(JSON.parse(options.body)); body = {success:true};
                    }
                    else if (url === '/api/client/profile-agent/start') {
                      window.fixture.starts++;
                      if (window.fixture.holdStart) await new Promise(resolve => {
                        window.fixture.release = resolve;
                      });
                      window.fixture.running = true;
                      body = {success: true, status: {running: true}};
                    } else if (url === '/api/client/profile-agent/stop') {
                      window.fixture.stops++; window.fixture.running = false;
                      body = {success: true};
                    } else throw new Error(`unexpected request: ${url}`);
                    return new Response(JSON.stringify(body), {
                      status: 200, headers: {'Content-Type': 'application/json'},
                    });
                  };
                }""")
                page.add_script_tag(path=str(bundle))
                page.locator("#first").click()
                page.locator(".agent-fixture-chat").first.wait_for()
                page.locator("#second").click()
                page.wait_for_function(
                    "document.querySelectorAll('.agent-fixture-chat').length === 2"
                )
                page.evaluate("fixture.setResearch({researchId:'research-a',title:'研究甲',section:'details'})")
                page.wait_for_function("fixture.publishes.length === 2")
                assert set(page.evaluate("fixture.publishes.map(value => value.workspace_id)")) == {"workspace-1", "workspace-2"}
                assert page.get_by_text("研究甲", exact=True).count() == 2
                for width in (1440,390):
                    page.set_viewport_size({"width":width,"height":844})
                    assert page.locator(".tr-agent-assistant-context").first.evaluate(
                        "node => node.getBoundingClientRect().right <= window.innerWidth + 1"
                    )
                    if output := os.environ.get("TR_ASSISTANT_QA_DIR"):
                        page.screenshot(path=str(Path(output) / f"assistant-context-{width}.png"))
                page.set_viewport_size({"width":1280,"height":720})
                page.locator("#first").click()
                page.wait_for_function(
                    "document.querySelectorAll('.agent-fixture-chat').length === 1"
                )
                assert page.evaluate("fixture.stops") == 0
                assert page.evaluate("fixture.disposed") == 1
                assert page.evaluate("fixture.running") is True
                page.wait_for_function("fixture.removes.length === 1")
                page.wait_for_function("fixture.releases.length === 1")
                assert "workspace_id=workspace-1" in page.evaluate("fixture.removes[0]")
                assert "workspace_id=workspace-1" in page.evaluate("fixture.releases[0]")
                page.evaluate("""async () => fixture.contexts[1].api('/api/client/profile-agent/rpc', {
                  method:'POST',body:JSON.stringify({method:'turn/start',params:{}}),
                })""")
                assert page.evaluate("fixture.rpcs[0].workspace_id") == "workspace-2"
                assert page.evaluate("fixture.publishes.at(-1).workspace.tabs[0].research_id") == "research-a"
                page.evaluate("fixture.allowResearch = false; fixture.setResearch({researchId:'research-a',title:'研究甲',section:'evidence'})")
                page.get_by_text("无法连接", exact=True).wait_for()
                page.set_viewport_size({"width":390,"height":844})
                if output := os.environ.get("TR_ASSISTANT_QA_DIR"):
                    page.screenshot(path=str(Path(output) / "assistant-context-denied-390.png"))
                page.evaluate("""async () => { try { await fixture.contexts[1].api('/api/client/profile-agent/rpc', {
                  method:'POST',body:JSON.stringify({method:'turn/start',params:{}}),
                }); } catch (_) {} }""")
                assert page.evaluate("fixture.rpcs.length") == 1
                page.evaluate("fixture.allowResearch = true")
                page.get_by_role("button",name="重试").click()
                page.get_by_text("已连接", exact=True).wait_for()

                page.locator("#second").click()
                page.evaluate("fixture.running = false; fixture.holdStart = true")
                page.locator("#first").click()
                page.wait_for_function("typeof fixture.release === 'function'")
                page.locator("#first").click()
                page.evaluate("fixture.release()")
                page.wait_for_function("fixture.running === true")
                assert page.evaluate("fixture.stops") == 0
                assert page.locator(".agent-fixture-chat").count() == 0
                page.locator("#second").click()
                page.locator(".agent-fixture-chat").first.wait_for()
                assert page.evaluate("fixture.starts") == 2
                assert page.evaluate("fixture.stops") == 0
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
