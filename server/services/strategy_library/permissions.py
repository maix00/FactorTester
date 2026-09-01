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


def access_for(
    entry: dict[str, Any],
    *,
    principal: str,
    shared_principals: set[str],
    subordinate_users: set[str],
) -> dict[str, bool]:
    owner = str(entry.get("owner_ref") or "")
    visibility = str(entry.get("visibility") or "private")
    is_owner = owner == principal
    is_subordinate = owner in subordinate_users
    explicitly_shared = principal in shared_principals
    can_view = is_owner or is_subordinate or visibility == "public" or (
        visibility == "shared" and explicitly_shared
    )
    return {
        "can_view": can_view,
        "can_edit": is_owner,
        "can_delete": is_owner,
        "can_share": is_owner,
        "is_owner": is_owner,
        "is_subordinate": is_subordinate,
    }
