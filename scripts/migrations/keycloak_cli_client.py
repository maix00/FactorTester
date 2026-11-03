#!/usr/bin/env python3
"""Plan or apply the public Keycloak CLI device-login client.

Realms imported before the CLI login client existed do not get it from the
realm import. This is a reviewed configuration step, not a user migration:
it creates one public client and adds the default scopes the Manager needs to
verify CLI tokens, and never grants a role or touches an existing user.

Dry-run by default. Required environment:

    TRADERESEARCH_KEYCLOAK_URL
    TRADERESEARCH_KEYCLOAK_REALM
    TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_ID
    TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_SECRET
"""

from __future__ import annotations

import argparse
import json
import os


def _adapter():
    from server.identity.keycloak import KeycloakAdminAdapter

    names = (
        "TRADERESEARCH_KEYCLOAK_URL",
        "TRADERESEARCH_KEYCLOAK_REALM",
        "TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_ID",
        "TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_SECRET",
    )
    missing = [name for name in names if not os.environ.get(name, "").strip()]
    if missing:
        raise SystemExit("missing Keycloak configuration: " + ", ".join(missing))
    return KeycloakAdminAdapter(
        os.environ["TRADERESEARCH_KEYCLOAK_URL"].strip(),
        os.environ["TRADERESEARCH_KEYCLOAK_REALM"].strip(),
        client_id=os.environ["TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_ID"].strip(),
        client_secret=os.environ["TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_SECRET"].strip(),
        timeout=10.0,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="create or repair the CLI client; the default is a read-only plan",
    )
    parser.add_argument("--audience", default="tr-manager")
    args = parser.parse_args(argv)
    from server.identity.cli_login import provision

    result = provision(_adapter(), apply=args.apply, audience=args.audience)
    print(json.dumps({"dry_run": not args.apply, **result}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
