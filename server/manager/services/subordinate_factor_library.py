"""Direct-child factor-library projection from Manager-local mirrors."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from server.manager.services.account_domain_projection import factor_rows_from_sync


def direct_subordinate_accounts(
    principal: str,
    local_account_store: object | None,
) -> list[dict[str, Any]]:
    """Return active first-level children from the local account mirror."""
    owner = str(principal or "").strip()
    if not owner or local_account_store is None:
        return []
    try:
        rows = local_account_store.load_accounts()
    except (AttributeError, ConnectionError, OSError, RuntimeError, TypeError, ValueError):
        return []
    current = next(
        (
            row for row in rows
            if isinstance(row, Mapping)
            and str(row.get("username") or "").strip() == owner
        ),
        None,
    )
    if current is None:
        return []
    organization_id = str(current.get("organization_id") or "default")
    children = [
        dict(row)
        for row in rows
        if isinstance(row, Mapping)
        and row.get("active", True) is not False
        and str(row.get("parent_username") or "").strip() == owner
        and str(row.get("organization_id") or "default") == organization_id
    ]
    return sorted(
        children,
        key=lambda row: (
            str(row.get("alias") or row.get("username") or "").lower(),
            str(row.get("username") or ""),
        ),
    )


def subordinate_factor_rows(
    sync: object | None,
    accounts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Read each direct child's source-free factors from the SQLite mirror."""
    if sync is None:
        return []
    result: list[dict[str, Any]] = []
    for account in accounts:
        owner = str(account.get("username") or "").strip()
        if owner:
            result.extend(
                factor_rows_from_sync(sync, owner, owner_account=account)
            )
    return result
