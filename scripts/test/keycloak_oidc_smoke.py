#!/usr/bin/env python3
"""Smoke test Keycloak token + userinfo for a test user (no browser)."""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request

from server.identity.keycloak import oidc_userinfo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--realm", required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args(argv)
    form = urllib.parse.urlencode({
        "grant_type": "password", "client_id": args.client_id,
        "username": args.username, "password": args.password,
        "scope": "openid profile email",
    }).encode()
    request = urllib.request.Request(
        f"{args.base_url.rstrip('/')}/realms/{args.realm}/protocol/openid-connect/token",
        data=form, method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        token = str(json.loads(response.read())["access_token"])
    profile = oidc_userinfo(
        base_url=args.base_url, realm=args.realm, access_token=token,
    )
    print(json.dumps({"username": profile.get("preferred_username"),
                      "sub": profile.get("sub")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
