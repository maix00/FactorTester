"""Real React shell account navigation; API data is a fixture, not live login.

Browser plugin not available. Reuse GTHT Playwright and installed Chrome.
"""
import json
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from itertools import product

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "web/app"


def test_account_entry_uses_shared_settings_and_has_a_return_path(tmp_path):
    source, bundle = tmp_path / "harness.tsx", tmp_path / "harness.js"
    source.write_text(f"""
import React from {json.dumps(str(APP/'node_modules/react/index.js'))};
import {{createRoot}} from {json.dumps(str(APP/'node_modules/react-dom/client.js'))};
import {{AuthGate}} from {json.dumps(str(APP/'src/auth.tsx'))};
import {{setupIonicReact}} from {json.dumps(str(APP/'node_modules/@ionic/react/dist/index.js'))};
import {json.dumps(str(APP/'src/i18n.ts'))};
import {json.dumps(str(APP/'node_modules/@ionic/react/css/core.css'))};
import {json.dumps(str(APP/'node_modules/@ionic/react/css/structure.css'))};
import {json.dumps(str(APP/'src/shell.css'))};
import {json.dumps(str(APP/'node_modules/dockview-react/dist/styles/dockview.css'))};
setupIonicReact({{mode:'md'}});
(window.mobile ? import({json.dumps(str(APP/'src/mobile-shell.tsx'))}) : import({json.dumps(str(APP/'src/desktop-shell.tsx'))})).then(module=>{{
  const Shell=window.mobile?module.MobileShell:module.DesktopShell;
  createRoot(document.getElementById('root')!).render(<AuthGate><Shell/></AuthGate>);
}});
""")
    subprocess.run([str(APP / "node_modules/.bin/esbuild"), str(source), "--bundle", "--format=iife",
                    "--target=es2020", f"--outfile={bundle}"], cwd=APP, check=True, capture_output=True)
    (tmp_path / "index.html").write_text('<title>TradeResearch account QA</title><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/harness.css"><div id="root"></div>')
    (tmp_path / "favicon.ico").write_bytes(b"")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                for mobile, locale in product((False, True), ("zh-CN", "en-US")):
                    zh = locale == "zh-CN"
                    page = browser.new_page(viewport={"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900}, locale=locale)
                    page.set_default_timeout(8000)
                    errors = []; page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(f"http://127.0.0.1:{server.server_port}/index.html?settings=account")
                    assert page.title() == "TradeResearch account QA"
                    page.evaluate("""mobile => {
                        window.mobile=mobile;
                        if(mobile)document.documentElement.classList.add('tr-mobile-runtime');
                        window.fetch=async input=>{
                            const path=new URL(String(input),location.origin).pathname;
                            const value=path==='/api/session'?{session:{username:'Example@Alice@123',alias:'Alice',role:'user'}}:
                                path==='/api/client/profiles'?{profiles:[]}: {items:[],researches:[],reports:[]};
                            return new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});
                        };
                    }""", mobile)
                    page.add_script_tag(path=str(bundle))
                    reference = page.locator(".tr-object-reference").filter(has_text="Alice")
                    reference.wait_for()
                    assert reference.inner_text() == "Alice"
                    reference.click()
                    details = page.get_by_role("dialog").filter(has=page.get_by_text("Example@Alice@123", exact=True))
                    details.wait_for()
                    if mobile:
                        details.get_by_role("button", name="返回" if zh else "Back", exact=True).click()
                    else:
                        details.locator(".ant-modal-close").click()
                    details.wait_for(state="hidden")
                    if mobile:
                        header = page.locator("ion-header.tr-mobile-header")
                        header.locator("ion-title").filter(has_text="账户" if zh else "Account").wait_for()
                        assert page.locator(".tr-object-reference").filter(has_text="Alice").is_visible()
                        assert page.get_by_text("用户" if zh else "User", exact=True).is_visible()
                        page.screenshot(path=str(tmp_path / f"account-mobile-{locale}.png"))
                        header.get_by_role("button", name="返回" if zh else "Back", exact=True).click()
                        header.locator("ion-title").filter(has_text="设置" if zh else "Settings").wait_for()
                        header.get_by_role("button", name="返回" if zh else "Back", exact=True).click()
                        page.locator(".tr-mobile-shell[data-root='true']").wait_for()
                        assert header.get_by_role("button", name="通知中心" if zh else "Notification center").is_visible()
                        assert header.get_by_role("button", name="打开智能体助手" if zh else "Open agent assistant").is_visible()
                    else:
                        dialog = page.get_by_role("dialog")
                        dialog.wait_for()
                        assert dialog.locator(".tr-object-reference").filter(has_text="Alice").is_visible()
                        assert dialog.get_by_text("用户" if zh else "User", exact=True).is_visible()
                        page.wait_for_timeout(350)
                        page.screenshot(path=str(tmp_path / f"account-desktop-{locale}.png"))
                        dialog.locator(".ant-modal-close").click()
                        dialog.wait_for(state="hidden")
                    assert "settings=account" not in page.url
                    assert not page.locator("vite-error-overlay").count()
                    assert not errors
                    page.close()
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
