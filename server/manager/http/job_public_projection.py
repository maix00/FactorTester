"""Resolve read-only public job projections for Manager forwarding.

The Manager task list may expose a bounded server-wide projection while the
service API remains owner-scoped.  This module keeps the fallback decision in
one place so detail and artifact routes use the same authorization boundary.
"""

from __future__ import annotations

from collections.abc import Iterable


def _account_scope(principal: str) -> tuple[bool, set[str]]:
    """Return the manager read scope for one authenticated account."""
    try:
        from tools.data.account_manage import (
            direct_subordinate_accounts_for,
            get_account,
            is_super_admin_account,
        )

        account = get_account(principal)
        if is_super_admin_account(account):
            return True, set()
        children = direct_subordinate_accounts_for(principal)
    except (
        AttributeError, ConnectionError, OSError, RuntimeError, TypeError,
        ValueError,
    ):
        return False, set()
    return False, {
        str(item.get("username") or "").strip()
        for item in children
        if isinstance(item, dict) and str(item.get("username") or "").strip()
    }


PUBLIC_JOB_PRINCIPAL = "__public_jobs__"


def _server_ids(routes: Iterable[object]) -> set[str]:
    return {
        str(getattr(route, "server_id", "") or "").strip()
        for route in routes
        if str(getattr(route, "server_id", "") or "").strip()
    }


def is_public_job_indexed(
    state: object,
    job_id: str,
    *,
    routes: Iterable[object] = (),
) -> bool:
    """Return whether ``job_id`` was observed in the public task projection.

    The local Manager index is only a projection of jobs already exposed by a
    server-wide task-list request.  It therefore provides the necessary
    bounded allow-list for a public fallback without turning a guessed job ID
    into an unrestricted owner bypass.
    """
    index = getattr(state, "job_index", None)
    if index is None:
        return False
    target = str(job_id or "").strip()
    if not target:
        return False
    route_ids = _server_ids(routes)
    try:
        jobs = index.list(PUBLIC_JOB_PRINCIPAL, limit=2000)
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    for item in jobs:
        if not isinstance(item, dict) or str(item.get("job_id") or "") != target:
            continue
        if not route_ids:
            return True
        item_ids = {
            str(item.get(key) or "").strip()
            for key in (
                "server_id",
                "origin_server_id",
                "execution_server_id",
                "storage_server_id",
            )
            if str(item.get(key) or "").strip()
        }
        if item_ids & route_ids:
            return True
    return False


def _indexed_job_owners(
    state: object,
    job_id: str,
    principal: str,
    *,
    routes: Iterable[object] = (),
) -> set[str]:
    """Find task owners in Manager's already-observed projections.

    The service database remains authoritative.  The local index is only
    used to identify a task selected from a permitted list and to choose the
    corresponding owner principal for the service-side owner check.
    """
    index = getattr(state, "job_index", None)
    if index is None:
        return set()
    current = str(principal or "").strip()
    if not current:
        return set()
    _is_super_admin, children = _account_scope(current)
    candidates = {current, PUBLIC_JOB_PRINCIPAL, *children}
    route_ids = _server_ids(routes)
    target = str(job_id or "").strip()
    owners: set[str] = set()
    for candidate in candidates:
        try:
            jobs = index.list(candidate, limit=2000)
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        for item in jobs:
            if not isinstance(item, dict) or str(item.get("job_id") or "") != target:
                continue
            if route_ids:
                item_ids = {
                    str(item.get(key) or "").strip()
                    for key in (
                        "server_id",
                        "origin_server_id",
                        "execution_server_id",
                        "storage_server_id",
                    )
                    if str(item.get(key) or "").strip()
                }
                if item_ids and not item_ids.intersection(route_ids):
                    continue
            owner = str(item.get("owner") or "").strip()
            if owner and owner != PUBLIC_JOB_PRINCIPAL:
                owners.add(owner)
            elif not owner and candidate != PUBLIC_JOB_PRINCIPAL:
                owners.add(candidate)
    return owners


def read_principals(
    state: object,
    principal: str,
    job_id: str,
    *,
    routes: Iterable[object] = (),
) -> tuple[str, ...]:
    """Return owner lookup order for a read-only job request.

    The caller's principal is always attempted first.  An authenticated
    account may then use the task owner only when the owner is itself or a
    direct child; super administrators may use any owner observed in their
    server projection.  Anonymous/public requests use the bounded public
    principal only for a task already present in the public index.
    """
    current = str(principal or "").strip()
    if not current:
        return ()
    if current == PUBLIC_JOB_PRINCIPAL or current.startswith(
        f"{PUBLIC_JOB_PRINCIPAL}:"
    ):
        return (
            current,
            PUBLIC_JOB_PRINCIPAL,
        ) if is_public_job_indexed(state, job_id, routes=routes) else (current,)

    is_super_admin, children = _account_scope(current)
    values = [current]
    for owner in sorted(_indexed_job_owners(
        state, job_id, current, routes=routes,
    )):
        if owner == current or (not is_super_admin and owner not in children):
            continue
        values.append(owner)
    return tuple(dict.fromkeys(value for value in values if value))


__all__ = [
    "PUBLIC_JOB_PRINCIPAL",
    "is_public_job_indexed",
    "read_principals",
]
