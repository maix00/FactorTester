"""Closing one React assistant panel must not stop a shared Profile process."""

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


def test_shared_assistant_panels_do_not_stop_profile_on_unmount(tmp_path):
    harness = tmp_path / "harness.tsx"
    bundle = tmp_path / "harness.js"
    harness.write_text(
        f"""
import React, {{useState}} from {json.dumps(str(APP / 'node_modules/react/index.js'))};
import {{createRoot}} from {json.dumps(str(APP / 'node_modules/react-dom/client.js'))};
import {{AgentAssistant}} from {json.dumps(str(APP / 'src/components/agent-assistant.tsx'))};
import {json.dumps(str(APP / 'src/i18n.ts'))};
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
    (tmp_path / "index.html").write_text('<div id="root"></div>', encoding="utf-8")
    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page()
                page.set_default_timeout(5000)
                page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                page.evaluate("""() => {
                  window.fixture = {running: false, starts: 0, stops: 0,
                                    disposed: 0, holdStart: false, release: null};
                  window.FTStaticLoader = {loadGroups: async () => {}};
                  window.FTAgentChat = {render: async (_context, _profile, options) => {
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
                page.locator("#first").click()
                page.wait_for_function(
                    "document.querySelectorAll('.agent-fixture-chat').length === 1"
                )
                assert page.evaluate("fixture.stops") == 0
                assert page.evaluate("fixture.disposed") == 1
                assert page.evaluate("fixture.running") is True

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
