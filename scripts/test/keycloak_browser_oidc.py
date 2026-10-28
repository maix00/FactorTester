#!/usr/bin/env python3
"""Browser OIDC smoke: Keycloak login form -> code -> token -> userinfo."""

from __future__ import annotations

import os
import re
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

from server.identity.keycloak import OIDCClient, oidc_userinfo


def main() -> int:
    base = os.environ["KEYCLOAK_URL"].rstrip("/")
    realm = os.environ["KEYCLOAK_REALM"]
    client_id = os.environ["KEYCLOAK_CLIENT_ID"]
    username = os.environ["KEYCLOAK_USERNAME"]
    password = os.environ["KEYCLOAK_PASSWORD"]
    redirect = os.environ["KEYCLOAK_REDIRECT_URI"]
    auth = (
        f"{base}/realms/{realm}/protocol/openid-connect/auth?"
        f"client_id={client_id}&response_type=code&scope=openid%20profile%20email"
        f"&redirect_uri={redirect.replace(':', '%3A').replace('/', '%2F')}&state=s1"
    )
    captured: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chrome")
        page = browser.new_page()
        page.on("request", lambda request: captured.append(request.url)
                if redirect in request.url else None)
        page.goto(auth)
        page.fill("#username", username)
        page.click("#kc-login", no_wait_after=True)
        page.wait_for_selector("#password", timeout=10000)
        page.fill("#password", password)
        page.click("#kc-login", no_wait_after=True)
        page.wait_for_timeout(3000)
        browser.close()
    callback = next((url for url in captured if "code=" in url), "")
    if not callback:
        raise SystemExit("OIDC redirect was not observed")
    code = parse_qs(urlparse(callback).query)["code"][0]
    tokens = OIDCClient(base, realm, client_id).exchange_code(code, redirect)
    profile = oidc_userinfo(base_url=base, realm=realm, access_token=tokens["access_token"])
    print(profile.get("preferred_username"), profile.get("sub"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
