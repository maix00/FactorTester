"""A landscape phone must still load the mobile shell on a fresh page."""
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'web/app'


def test_landscape_phone_loads_mobile_shell_and_desktop_stays_desktop(tmp_path):
    bundle = tmp_path / 'loader.js'
    subprocess.run([str(APP / 'node_modules/.bin/esbuild'), str(APP / 'src/loader.ts'), '--bundle',
                    '--format=iife', '--target=es2020', f'--outfile={bundle}'],
                   cwd=APP, check=True, capture_output=True, text=True)
    (tmp_path / 'index.html').write_text('<div data-tr-web-app></div><script src="/loader.js"></script>')
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            try:
                def check(mobile):
                    options = {'viewport': {'width': 844 if mobile else 1200, 'height': 390 if mobile else 844},
                               'service_workers': 'block'}
                    if mobile:
                        options.update(user_agent=playwright.devices['iPhone 13']['user_agent'], is_mobile=True, has_touch=True)
                    context = browser.new_context(**options)
                    page = context.new_page()
                    def asset(route):
                        url = route.request.url
                        if url.endswith('.css'):
                            route.fulfill(status=200, content_type='text/css', body='')
                        else:
                            name = 'mobile' if 'mobile.js' in url else 'desktop'
                            route.fulfill(status=200, content_type='application/javascript', body=f'window.loadedShell="{name}"')
                    page.route('**/research-static/vendor/web-app/*', asset)
                    page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                    page.wait_for_function('window.loadedShell !== undefined')
                    assert page.evaluate('window.loadedShell') == ('mobile' if mobile else 'desktop')
                    assert page.evaluate("document.documentElement.classList.contains('tr-mobile-runtime')") is mobile
                    context.close()
                check(True)
                check(False)
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)
