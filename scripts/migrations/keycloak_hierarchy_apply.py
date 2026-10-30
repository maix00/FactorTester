#!/usr/bin/env python3
"""Plan or explicitly apply legacy account hierarchy to Keycloak FGAP v2.

Input is the reviewed export consumed by ``keycloak_roles.py``. The default
mode is offline. ``--apply`` writes deterministic Realm Groups, memberships,
FGAP group policies/permissions, and global client-role mappings; it is
idempotent and rejects conflicting Keycloak resources rather than replacing
them.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.migrations.keycloak_roles import role_mappings_for_accounts
from server.identity.keycloak_hierarchy_admin import apply_keycloak_hierarchy_plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--roles-client-id", default=(
        os.environ.get("TRADERESEARCH_KEYCLOAK_ROLES_CLIENT_ID")
        or os.environ.get("TR_USER_OIDC_ROLES_CLIENT_ID") or ""
    ))
    parser.add_argument(
        "--session-client-ids", default=(
            os.environ.get("TRADERESEARCH_KEYCLOAK_SESSION_CLIENT_IDS") or ""
        ),
        help=(
            "Comma-separated Manager OIDC client IDs that must receive the "
            "verified Realm Group claim mapper. Required when applying memberships."
        ),
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Apply the reviewed groups, scoped admin permissions, memberships, and roles.",
    )
    args = parser.parse_args(argv)
    source = json.loads(args.input.read_text(encoding="utf-8"))
    plan = role_mappings_for_accounts(
        source.get("accounts") or [],
        source.get("organizations") or [],
        source.get("levels") or [],
    )
    result: dict[str, object] = {"dry_run": not args.apply, **plan}
    if args.apply:
        required = (
            "TRADERESEARCH_KEYCLOAK_URL",
            "TRADERESEARCH_KEYCLOAK_REALM",
            "TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_ID",
            "TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_SECRET",
        )
        missing = [key for key in required if not os.environ.get(key, "").strip()]
        if missing:
            parser.error("missing Keycloak apply configuration: " + ", ".join(missing))
        session_client_ids = sorted({
            item.strip() for item in str(args.session_client_ids or "").split(",")
            if item.strip()
        })
        if not session_client_ids:
            parser.error(
                "--session-client-ids or TRADERESEARCH_KEYCLOAK_SESSION_CLIENT_IDS "
                "is required for a hierarchy apply"
            )
        from server.identity.keycloak import KeycloakAdminAdapter

        adapter = KeycloakAdminAdapter(
            os.environ["TRADERESEARCH_KEYCLOAK_URL"].strip(),
            os.environ["TRADERESEARCH_KEYCLOAK_REALM"].strip(),
            client_id=os.environ["TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_ID"].strip(),
            client_secret=os.environ["TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_SECRET"].strip(),
            timeout=5.0,
        )
        applied = apply_keycloak_hierarchy_plan(
            plan, adapter, roles_client_id=str(args.roles_client_id or ""),
            session_client_ids=session_client_ids,
        )
        result["apply_result"] = applied
        result["dry_run"] = False
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if applied.get("applied") else 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
