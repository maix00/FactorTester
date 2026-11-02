"""The React Job page must show the complete, owner-scoped frozen RunSpec."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import subprocess
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "web/app"


def test_frozen_run_spec_displays_configuration_and_clickable_references(tmp_path):
    harness = tmp_path / "harness.tsx"
    bundle = tmp_path / "harness.js"
    harness.write_text(
        f"""
import React from {json.dumps(str(APP / 'node_modules/react/index.js'))};
import {{createRoot}} from {json.dumps(str(APP / 'node_modules/react-dom/client.js'))};
import {{FrozenRunSpec}} from {json.dumps(str(APP / 'src/components/frozen-run-spec.tsx'))};
import {{ObjectReferenceContext}} from {json.dumps(str(APP / 'src/components/object-reference.tsx'))};
import {json.dumps(str(APP / 'src/i18n.ts'))};
createRoot(document.getElementById('root')!).render(
  <ObjectReferenceContext.Provider value={{value => {{ (window as any).opened = value; }}}}>
    <FrozenRunSpec hash={{'a'.repeat(64)}} serverID="remote" />
  </ObjectReferenceContext.Provider>);
""", encoding="utf-8",
    )
    subprocess.run(
        [str(APP / "node_modules/.bin/esbuild"), str(harness), "--bundle", "--format=iife",
         "--target=es2020", f"--outfile={bundle}"],
        cwd=APP, check=True, capture_output=True, text=True,
    )
    (tmp_path / "index.html").write_text('<div id="root"></div>', encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page(viewport={"width": 1100, "height": 800})
                page.set_default_timeout(5000)
                page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                page.evaluate("""() => {
                  localStorage.setItem('tr.language', 'zh');
                  window.fetch = async input => {
                    window.requested = String(input);
                    return new Response(JSON.stringify({success: true, run_spec: {
                      run_spec_hash: 'a'.repeat(64), run_spec_version: 2, configuration_id: 'configuration-7',
                      complete_parameters_json: '{}', run_spec: {
                        workspace_id: 'workspace-7', retention_mode: 'all',
                        configuration: {shared: {factor_ref: 'factor:v2:fixture', product_ref: 'T.CFE'},
                          execution: {backend: 'legacy', fee: 3},
                          deep: {level1: {level2: {level3: {level4: {level5: {level6: {level7: {
                            factor_ref: 'factor:v2:deep'
                          }}}}}}}}},
                      },
                    }}), {status: 200, headers: {'Content-Type': 'application/json'}});
                  };
                }""")
                page.add_script_tag(path=str(bundle))
                page.get_by_text("configuration-7", exact=True).wait_for()
                assert "server_id=remote" in page.evaluate("requested")
                assert page.get_by_text("workspace-7", exact=True).is_visible()
                assert page.get_by_text("legacy", exact=True).is_visible()
                page.get_by_role("button", name="查看 factor:v2:fixture 的信息").click()
                assert page.evaluate("opened.kind") == "factor"
                assert page.evaluate("opened.ref") == "factor:v2:fixture"
                assert page.get_by_role("button", name="查看 T.CFE 的信息").is_visible()
                for label in ["deep", "level1", "level2", "level3", "level4", "level5", "level6", "level7"]:
                    page.get_by_text(label, exact=True).click()
                page.get_by_role("button", name="查看 factor:v2:deep 的信息").click()
                assert page.evaluate("opened.ref") == "factor:v2:deep"
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
