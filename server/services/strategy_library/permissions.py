"""Access decisions for Strategy library projections."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def subordinate_principals(
    principal: str,
    account_provider: Callable[[], list[dict[str, Any]]] | None,
) -> set[str]:
    """Resolve direct children without making the catalog depend on SQL."""
    if account_provider is None:
        try:
            from tools.data.account_manage import direct_subordinate_accounts_for

            rows = direct_subordinate_accounts_for(principal)
        except (ImportError, OSError, RuntimeError):
            rows = []
    else:
        rows = account_provider() or []
    result: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        username = str(
            row.get("username") or row.get("user_name") or row.get("account")
            or row.get("owner_ref") or ""
        ).strip()
        parent = str(
            row.get("parent_username") or row.get("parent_ref")
            or row.get("superior_username") or ""
        ).strip()
        if username and (not parent or parent == principal):
            result.add(username)
    return result


def access_many(entries: list[dict[str, Any]], *, principal: str,
                subordinate_users: set[str]) -> dict[str, dict[str, bool]]:
    from server.identity.keycloak_authorization import (
        keycloak_request_identity, keycloak_authorized_many,
        keycloak_resource_uri, keycloak_resource_name,
    )
    identity = keycloak_request_identity()
    scopes = {"can_view": "read", "can_edit": "write",
              "can_delete": "delete", "can_share": "share"}
    refs = {str(e["strategy_ref"]) for e in entries}
    uris = {ref: keycloak_resource_uri("strategy", ref) for ref in refs}
    decisions = {}
    if identity and identity.username == principal:
        permissions = [(uris[ref], keycloak_resource_name("strategy", ref), scope)
                       for ref in sorted(refs) for scope in scopes.values()]
        for offset in range(0, len(permissions), 256):
            decisions.update(keycloak_authorized_many(
                identity.token, permissions=permissions[offset:offset + 256],
            ))
    # Metadata labels never override the authoritative Keycloak decision.
    return {str(e["strategy_ref"]): {
        **{key: bool(decisions.get((uris[str(e["strategy_ref"])], scope)))
           for key, scope in scopes.items()},
        "is_owner": str(e.get("owner_ref") or "") == principal,
        "is_subordinate": str(e.get("owner_ref") or "") in subordinate_users,
    } for e in entries}


def access_for(entry: dict[str, Any], *, principal: str,
               shared_principals: set[str], subordinate_users: set[str]) -> dict[str, bool]:
    return access_many([entry], principal=principal,
                       subordinate_users=subordinate_users)[str(entry["strategy_ref"])]
