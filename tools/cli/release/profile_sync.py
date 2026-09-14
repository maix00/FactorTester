"""Manager control-plane synchronization for local Profile projections."""

from __future__ import annotations

from typing import Any

from tools.cli.agent_auth import load_capability
from tools.cli.client import FactorTesterClient
from tools.cli.http import (
    ClientConfig,
    HttpClientError,
    HttpSession,
    load_config,
)
from tools.cli.manager.config import ManagerConfig

_RETRYABLE_HTTP_STATUSES = {401, 403, 408, 429, *range(500, 600)}


def manager_url_for_profile(
    profile: dict[str, Any],
    *,
    manager_url: str = "",
) -> str:
    """Resolve Manager from the client connection, never from Profile data."""
    explicit = str(manager_url or "").strip()
    if explicit:
        return ManagerConfig.from_url(explicit).base_url
    del profile
    capability = load_capability()
    if capability is not None:
        return ManagerConfig.from_url(
            capability.base_url,
        ).base_url
    try:
        configured = load_config()
    except FileNotFoundError as exc:
        raise ValueError(
            "client has no configured server; run `factortester configure` "
            "or pass --manager-url"
        ) from exc
    return ManagerConfig.from_url(configured.base_url).base_url


def manager_url_for_client_url(server_url: str) -> str:
    """Use the selected Manager connection without guessing a business port."""
    value = str(server_url or "").strip()
    if not value:
        raise ValueError("client server URL is empty")
    return ManagerConfig.from_url(
        value,
    ).base_url


def sync_profile(
    profile: dict[str, Any],
    *,
    manager_url: str = "",
) -> dict[str, object]:
    """Sync one Profile through an authenticated Manager session.

    Use the native application's endpoint-scoped session, with legacy cookies
    supported by HttpSession. Operator Manager credentials are a separate
    authority and are never borrowed for ordinary Profile synchronization.
    """
    binding = profile.get("session_binding")
    principal_ref = str(
        binding.get("principal_ref") or ""
        if isinstance(binding, dict) else ""
    ).strip()
    if not principal_ref:
        raise ValueError("profile has no session principal binding")
    target = manager_url_for_profile(profile, manager_url=manager_url)
    try:
        legacy = FactorTesterClient(HttpSession(target, timeout=5))
        _require_principal(legacy.current_principal(), principal_ref)
        return legacy.sync_profile(profile)
    except HttpClientError as exc:
        if exc.status not in _RETRYABLE_HTTP_STATUSES:
            raise
        return _pending_receipt(profile, target, _http_reason(exc))
    except (OSError, TimeoutError, RuntimeError, ValueError) as exc:
        return _pending_receipt(profile, target, str(exc))


def _require_principal(value: dict[str, Any], expected: str) -> None:
    observed = str(value.get("username") or value.get("principal") or "")
    if observed != expected:
        raise ValueError("authenticated principal does not match profile")


def _pending_receipt(
    profile: dict[str, Any], manager_url: str, reason: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "pending",
        "synced": False,
        "pending": True,
        "profile_id": str(profile.get("profile_id") or ""),
        "manager_url": manager_url,
        "reason": reason or "Manager is unavailable; sync remains pending",
    }


def _http_reason(error: HttpClientError) -> str:
    if error.status in {401, 403}:
        return "Manager session is unavailable; sync remains pending"
    return f"Manager returned HTTP {error.status}; sync remains pending"
