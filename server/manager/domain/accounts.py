"""Manager-facing account authentication and hierarchy projections."""

from __future__ import annotations

from collections.abc import Iterable

from server.manager.domain.organization_scope import resolve_login_account


def account_role(account: dict[str, object]) -> str:
    from tools.data.account_manage import is_super_admin_account

    return (
        "super_admin" if is_super_admin_account(account)
        else str(account.get("role") or "user")
    )


def authenticate_user(
    username: str,
    password: str,
    *,
    control_store: object | None = None,
    managed_organizations: Iterable[str] = (),
) -> tuple[str, str]:
    from tools.data.account_manage import accounts_lock, verify_password

    username = str(username or "").strip()
    password = str(password or "")
    if not username or not password:
        raise ValueError("username and password are required")
    if control_store is not None:
        accounts = control_store.load_accounts()
    else:
        from tools.data.account_manage import load_accounts

        with accounts_lock:
            accounts = load_accounts()
    account = resolve_login_account(
        username,
        accounts,
        managed_organizations=managed_organizations,
    )
    if (
        account is None
        or not verify_password(
            password,
            str(account.get("salt") or ""),
            str(account.get("hash") or ""),
        )
    ):
        raise PermissionError("invalid username or password")
    return str(account["username"]), account_role(account)


def manager_subordinate_users(owner: str) -> list[dict[str, str]]:
    """Return direct account children without querying a service port."""
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
