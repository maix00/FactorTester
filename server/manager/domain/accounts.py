"""Keycloak-backed Manager account projections."""

from __future__ import annotations

def account_role(account: dict[str, object]) -> str:
    from tools.data.account_manage import is_super_admin_account

    return (
        "super_admin" if is_super_admin_account(account)
        else str(account.get("role") or "user")
    )


def manager_subordinate_users(owner: str) -> list[dict[str, str]]:
    """Return Keycloak directory descendants visible in this verified request."""
    from tools.data.account_manage import direct_subordinate_accounts_for

    result: list[dict[str, str]] = []
    for account in direct_subordinate_accounts_for(owner):
        username = str(account.get("username") or "").strip()
        if not username:
            continue
        alias = str(account.get("alias") or "").strip()
        result.append({
            "username": username,
            "alias": alias,
            "title": alias or username,
            "organization_name": str(account.get("organization_name") or ""),
            "role": str(account.get("role") or "user"),
        })
    return sorted(
        result,
        key=lambda item: (item["title"].lower(), item["username"]),
    )
