"""Manager organization scope and canonical account-name rules."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping


DEFAULT_MANAGED_ORGANIZATION = "GTHT"
PUBLIC_MANAGED_ORGANIZATION = "default"
DEFAULT_ORGANIZATION_NAMES = {
    "GTHT": "GTHT",
    "default": "默认机构",
}
_ALIAS_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fff]{1,32}$")
_ORGANIZATION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def normalize_organization_id(value: object) -> str:
    """Return one safe organization identifier for the username grammar."""
    result = str(value or "").strip()
    if not result or not _ORGANIZATION_RE.fullmatch(result):
        raise ValueError(
            "机构标识只能包含字母、数字、下划线或连字符，且不超过64字符"
        )
    return result


def normalize_managed_organizations(
    values: Iterable[object] | object | None,
) -> tuple[str, ...]:
    """Normalize an explicit Manager organization scope, preserving order."""
    if values is None:
        return ()
    if isinstance(values, str):
        values = values.split(",")
    result: list[str] = []
    for value in values:
        if not str(value or "").strip():
            continue
        item = normalize_organization_id(value)
        if item not in result:
            result.append(item)
    return tuple(result)


def configured_managed_organizations(
    *,
    public_server: bool,
    server_role: str,
    explicit: Iterable[object] | object | None = None,
    environment: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Resolve the Manager scope from deployment configuration.

    ``FACTORTESTER_MANAGED_ORGANIZATIONS`` is a comma-separated override.
    The safe deployment defaults are GTHT for the internal/feature Manager
    and ``default`` for the public/main Manager.
    """
    if explicit is not None:
        result = normalize_managed_organizations(explicit)
    else:
        environ = os.environ if environment is None else environment
        raw = str(environ.get("FACTORTESTER_MANAGED_ORGANIZATIONS") or "")
        result = normalize_managed_organizations(raw)
    if result:
        return result
    if public_server or str(server_role or "").strip().lower() == "main":
        return (PUBLIC_MANAGED_ORGANIZATION,)
    return (DEFAULT_MANAGED_ORGANIZATION,)


def default_managed_organization(organizations: Iterable[str]) -> str:
    """Select the first configured organization for blank registration input."""
    values = tuple(str(item).strip() for item in organizations if str(item).strip())
    if not values:
        raise ValueError("Manager没有配置可管理的机构")
    return values[0]


def validate_alias(value: object) -> str:
    """Validate the user-supplied alias; matching remains case-sensitive."""
    alias = str(value or "").strip()
    if "$" in alias or "@" in alias:
        raise ValueError("别名不能包含 $ 或 @")
    if not _ALIAS_RE.fullmatch(alias):
        raise ValueError("别名只能包含字母、数字、下划线或汉字，且不超过32字符")
    return alias


def organization_descriptor(
    organization_id: str,
    *,
    name: str = "",
    description: str = "",
) -> dict[str, str]:
    """Build a local descriptor when the central organization row is offline."""
    identifier = normalize_organization_id(organization_id)
    return {
        "id": identifier,
        "name": str(name or DEFAULT_ORGANIZATION_NAMES.get(identifier, identifier)),
        "description": str(description or ""),
    }


def canonical_username(organization_id: str, alias: str, suffix: object) -> str:
    """Compose ``organization@alias@numeric-suffix``."""
    organization = normalize_organization_id(organization_id)
    clean_alias = validate_alias(alias)
    serial = str(suffix or "").strip()
    if not serial.isdigit():
        raise ValueError("用户名随机数字部分必须是数字")
    return f"{organization}@{clean_alias}@{serial}"


def _account_organization(account: Mapping[str, object]) -> str:
    return str(account.get("organization_id") or "default").strip() or "default"


def resolve_login_account(
    username: object,
    accounts: Iterable[Mapping[str, object]],
    *,
    managed_organizations: Iterable[str],
) -> Mapping[str, object] | None:
    """Resolve exact, ``organization@alias`` or alias-only login input.

    Exact usernames are intentionally checked first.  This lets a caller use
    a full immutable username even when the Manager's alias shorthand scope
    does not include that organization.  Shorthand forms are restricted to
    the Manager's configured organization scope.
    """
    value = str(username or "").strip()
    rows = [item for item in accounts if isinstance(item, Mapping)]
    exact = next(
        (item for item in rows if str(item.get("username") or "") == value),
        None,
    )
    if exact is not None:
        return exact

    scope = set(normalize_managed_organizations(managed_organizations))
    if not value or not scope:
        return None
    if value.count("@") == 1:
        organization, alias = value.split("@", 1)
        if organization not in scope:
            return None
        candidates = [
            item for item in rows
            if _account_organization(item) == organization
            and str(item.get("alias") or "") == alias
        ]
    elif "@" not in value:
        candidates = [
            item for item in rows
            if _account_organization(item) in scope
            and str(item.get("alias") or "") == value
        ]
    else:
        return None
    if len(candidates) > 1:
        names = ", ".join(
            str(item.get("username") or "") for item in candidates
        )
        raise PermissionError(
            f"用户名 {value!r} 存在多个账号，请使用完整用户名登录：{names}"
        )
    return candidates[0] if candidates else None
