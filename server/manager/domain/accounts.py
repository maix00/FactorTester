"""Manager-facing account authentication and hierarchy projections."""

from __future__ import annotations


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
    account = next(
        (item for item in accounts if item.get("username") == username),
        None,
    )
    if account is None:
        matches = [
            item for item in accounts
            if item.get("alias", item.get("username")) == username
        ]
        if len(matches) == 1:
            account = matches[0]
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
    """Return account choices without asking a service port to enumerate."""
    from tools.data.account_manage import visible_accounts_for

    result: list[dict[str, str]] = []
    for account in visible_accounts_for(owner, include_self=False):
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
