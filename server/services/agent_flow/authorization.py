"""Server-derived authorization for Agent execution registration."""

from __future__ import annotations

from tools.data.account_manage import get_account, is_developer_account


_BACKEND_ROLES = {"backend_verifier", "implementation_agent"}
_BACKEND_SCOPE = "server_backend_code"
_MAINTENANCE_ROLE = "server_maintenance"


def require_execution_authority(
    *,
    username: str,
    actor_role: str,
    authority_scope: str,
) -> None:
    """Authorize execution registration without granting token controls."""
    if actor_role not in _BACKEND_ROLES and authority_scope != _BACKEND_SCOPE:
        return
    _require_developer(username)
    if actor_role in _BACKEND_ROLES and authority_scope != _BACKEND_SCOPE:
        raise PermissionError(
            f"{actor_role} requires server_backend_code authority"
        )


def require_resume_role(*, username: str, role: str) -> None:
    if role == _MAINTENANCE_ROLE:
        _require_developer(username)


def _require_developer(username: str) -> None:
    if not is_developer_account(get_account(username)):
        raise PermissionError(
            "server backend operations require a developer account"
        )
