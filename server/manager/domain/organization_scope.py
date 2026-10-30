"""Manager organization scope and canonical account-name rules."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping


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

    Organization ownership is deployment data. An unconfigured Manager has
    no managed organizations; callers must fail closed instead of inventing
    a synthetic organization.
    """
    if explicit is not None:
        result = normalize_managed_organizations(explicit)
    else:
        environ = os.environ if environment is None else environment
        raw = str(environ.get("FACTORTESTER_MANAGED_ORGANIZATIONS") or "")
        result = normalize_managed_organizations(raw)
    del public_server, server_role
    return result
