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
                    page.evaluate("history.replaceState(null, '', '/app?settings=account')")
                    assert page.title() == "TradeResearch account QA"
                    page.evaluate("""mobile => {
                        window.mobile=mobile;
                        if(mobile)document.documentElement.classList.add('tr-mobile-runtime');
                        window.fetch=async input=>{
                            const path=new URL(String(input),location.origin).pathname;
                            const value=path==='/api/session'?{session:{username:'Example@Alice@123',alias:'Alice',role:'user',capabilities:{manager:true,research:true},admin_capabilities:['admin_console:read','admin_console:manage']}}:
                                path==='/api/client/releases/beta.json'?{version:'1.2.3',sha256:'a'.repeat(64),dmg_url:'/api/client/releases/assets/beta/'+'a'.repeat(64)+'.dmg'}:
                                path==='/api/client/profiles'?{profiles:[]}:
                                path==='/api/research'?{researches:Array.from({length:25},(_,i)=>({research_id:'research-'+i,title:'Research '+i,owner_ref:'Example@Alice@123'}))}:
                                {items:[],researches:[],reports:[]};
                            return new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});
                        };
                    }""", mobile)
                    page.add_script_tag(path=str(bundle))
                    reference = page.locator(".tr-settings-card .tr-object-reference").filter(has_text="Alice")
                    reference.wait_for()
                    assert page.locator(".tr-settings-card .tr-property-groups").is_visible()
                    assert page.locator(".tr-settings-card .tr-property-group:first-child .tr-property-list dt").count() == 3
                    if not mobile:
                        page.wait_for_function("""() => ![...document.querySelectorAll('.tr-settings-overlay')].some(element => /ant-zoom-(appear|enter)/.test(element.className))""")
                    page.wait_for_function("""() => [...document.querySelectorAll('.tr-settings-card .tr-property-list > div')].every(row => row.getBoundingClientRect().height >= 41)""")
                    rows = page.locator(".tr-settings-card .tr-property-list > div")
                    boxes = rows.evaluate_all("elements => elements.map(element => ({height:element.getBoundingClientRect().height}))")
                    assert len(boxes) == 5
                    assert max(box["height"] for box in boxes) <= 43
                    assert max(box["height"] for box in boxes) - min(box["height"] for box in boxes) <= 1
                    action = page.locator(".tr-settings-card .tr-account-actions button").bounding_box()
                    value = page.locator(".tr-settings-card .tr-property-group:first-child .tr-property-list dd").last.bounding_box()
                    assert abs(action["x"] + action["width"] - value["x"] - value["width"]) <= 1

                    assert action["height"] <= 28  # Shared AppTheme derives a 27px small control.
                    assert not page.locator(".tr-settings-card").get_by_text("Manager", exact=True).count()
                    assert page.locator(".tr-settings-card").get_by_text("管理控制台" if zh else "Admin console: manage", exact=True).is_visible()
                    assert page.url == f"http://127.0.0.1:{server.server_port}/app"
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
                        assert reference.is_visible()
                        assert page.get_by_text("用户" if zh else "User", exact=True).is_visible()
                        page.screenshot(path=str(tmp_path / f"account-mobile-{locale}.png"))
                        header.get_by_role("button", name="返回" if zh else "Back", exact=True).click()
                        header.locator("ion-title").filter(has_text="设置" if zh else "Settings").wait_for()
                        page.get_by_role("button", name="客户端 ›" if zh else "Client ›", exact=True).click()
                        download = page.get_by_role("link", name="下载 macOS 客户端" if zh else "Download for macOS", exact=True)
                        download.wait_for()
                        assert download.get_attribute("href").endswith("/" + "a" * 64 + ".dmg")
                        assert not page.get_by_text("客户端更新" if zh else "Client updates", exact=True).count()
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
                        dialog.locator(".tr-settings-nav").get_by_role("button", name="客户端" if zh else "Client", exact=True).click()
                        download = dialog.get_by_role("link", name="下载 macOS 客户端" if zh else "Download for macOS", exact=True)
                        download.wait_for()
                        assert download.get_attribute("href").endswith("/" + "a" * 64 + ".dmg")
                        dialog.locator(".ant-modal-close").click()
                        dialog.wait_for(state="hidden")
                    assert "settings=account" not in page.url
                    if not mobile:
                        # Dockview keeps pages mounted. Their Ant controls must
                        # not override a hidden ancestor and bleed into another tab.
                        for _ in range(2):
                            for title, page_id in (("研究台" if zh else "Research", "research"),
                                                   ("测试台" if zh else "Test bench", "test-bench")):
                                page.locator('.tr-module-nav').get_by_role('button', name=title, exact=True).click()
                                active = page.locator(f'.tr-tab-layer[data-tab-layer="{page_id}"][aria-hidden="false"]')
                                active.wait_for()
                                leaked = page.locator('.tr-tab-layer[aria-hidden="true"] button, .tr-tab-layer[aria-hidden="true"] input, .tr-tab-layer[aria-hidden="true"] [role="tab"]').evaluate_all('''nodes => nodes.filter(node => {
                                    const style=getComputedStyle(node),rect=node.getBoundingClientRect();
                                    return rect.width>0 && rect.height>0 && style.visibility!=='hidden' && style.display!=='none';
                                }).map(node=>({tag:node.tagName,text:node.textContent?.slice(0,50)}))''')
                                assert not leaked, leaked
                        nav = page.locator('.tr-module-nav')
                        nav.get_by_role('button', name='产品库' if zh else 'Products', exact=True).click()
                        search = page.locator('.tr-tab-layer[data-tab-layer="products"] .tr-library-filters input').first
                        search.fill('retained query')
                        nav.get_by_role('button', name='研究台' if zh else 'Research', exact=True).click()
                        assert not search.is_visible()
                        nav.get_by_role('button', name='产品库' if zh else 'Products', exact=True).click()
                        assert search.input_value() == 'retained query'
                        nav.get_by_role('button', name='研究台' if zh else 'Research', exact=True).click()
                        research = page.locator('.tr-tab-layer[data-tab-layer="research"] .tr-research-page')
                        research.locator('.ant-pagination').wait_for()
                        bounds = research.evaluate('''node => {
                            node.scrollTop=node.scrollHeight;
                            return {pageBottom:node.getBoundingClientRect().bottom,
                                panelBottom:node.closest('.tr-tab-layer').getBoundingClientRect().bottom,
                                paginationBottom:node.querySelector('.ant-pagination').getBoundingClientRect().bottom};
                        }''')
                        assert bounds['pageBottom'] <= bounds['panelBottom'] + 1
                        assert bounds['paginationBottom'] <= bounds['pageBottom'] + 1
                    assert not page.locator("vite-error-overlay").count()
                    assert not errors
                    page.close()
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
