"""Direct-child factor-library projection from Manager-local mirrors."""

from __future__ import annotations

from typing import Any

from server.manager.services.account_domain_projection import factor_rows_from_sync


def direct_subordinate_accounts(
    principal: str,
    _retired_local_account_store: object | None = None,
) -> list[dict[str, Any]]:
    """Return Keycloak-managed descendants for the verified current request.

    The compatibility argument is ignored so this boundary cannot regress to
    reading a local identity mirror. Keycloak Realm Group nesting supplies the
    management scope; object access is still decided by FGAP separately.
    """
    owner = str(principal or "").strip()
    if not owner:
        return []
    try:
        from server.identity.keycloak_directory import managed_users_for_verified_request

        rows = managed_users_for_verified_request(owner)
    except (ConnectionError, OSError, RuntimeError, TypeError, ValueError):
        return []
    return rows


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
