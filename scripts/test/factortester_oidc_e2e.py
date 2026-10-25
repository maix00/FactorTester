#!/usr/bin/env python3
"""Browser E2E: FactorTester OIDC start -> Keycloak -> callback -> session."""

from __future__ import annotations

import argparse
import json

from playwright.sync_api import sync_playwright


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--whoami", default="/whoami")
    args = parser.parse_args(argv)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chrome")
        page = browser.new_page()
        page.goto(args.base_url.rstrip("/") + "/api/auth/oidc/start")
        payload = json.loads(page.locator("body").inner_text())
        if not payload.get("success"):
            raise SystemExit(payload)
        page.goto(payload["authorization_url"])
        page.fill("#username", args.username)
        page.click("#kc-login", no_wait_after=True)
        page.wait_for_selector("#password", timeout=10000)
        page.fill("#password", args.password)
        page.click("#kc-login", no_wait_after=True)
        page.wait_for_timeout(3000)
        page.goto(args.base_url.rstrip("/") + args.whoami)
        print(page.locator("body").inner_text())
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
