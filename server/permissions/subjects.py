"""Resolve permission subjects for a username (Keycloak-aware, fail closed)."""

from __future__ import annotations

import os
import threading
import time


_SUBJECT_CACHE: dict[tuple[str, str, str], tuple[float, tuple[str, ...], bool]] = {}
_SUBJECT_CACHE_LOCK = threading.Lock()
_SUBJECT_CACHE_LIMIT = 512
_SUBJECT_CACHE_TTL_SECONDS = 15.0
_SUBJECT_CACHE_FAILURE_TTL_SECONDS = 2.0


def resolve_permission_subjects(username: str) -> tuple[tuple[str, ...], bool]:
    """Resolve a user and Keycloak groups/orgs with a short bounded cache.

    The boolean is false only when Keycloak is configured but could not be
    consulted. Authorization callers can then fail closed for group grants.
    Permission entries themselves are always read live, so revoking a grant
    does not wait for this identity cache to expire.
    """
    principal = str(username or "").strip()
    direct = (f"user:{principal}",) if principal else ()
    if not principal:
        return (), True
    base_url = os.environ.get("TRADERESEARCH_KEYCLOAK_URL", "") or os.environ.get(
        "FACTORTESTER_KEYCLOAK_URL", ""
    )
    realm = os.environ.get("TRADERESEARCH_KEYCLOAK_REALM", "") or os.environ.get(
        "FACTORTESTER_KEYCLOAK_REALM", ""
    )
    if not (base_url and realm):
        return direct, True
    client_id = os.environ.get(
        "TRADERESEARCH_KEYCLOAK_CLIENT_ID", "admin-cli"
    )
    cache_key = (base_url.rstrip("/"), realm.strip("/"), principal)
    now = time.monotonic()
    with _SUBJECT_CACHE_LOCK:
        cached = _SUBJECT_CACHE.get(cache_key)
        if cached is not None and cached[0] > now:
            return cached[1], cached[2]
        if cached is not None:
            _SUBJECT_CACHE.pop(cache_key, None)
    try:
        from server.identity.keycloak import KeycloakAdminAdapter, permission_subjects

        timeout = min(
            5.0,
            max(
                0.2,
                float(os.environ.get(
                    "TRADERESEARCH_KEYCLOAK_PERMISSION_TIMEOUT_SECONDS", "2.0"
                )),
            ),
        )
        identity = KeycloakAdminAdapter(
            base_url,
            realm,
            client_id=client_id,
            client_secret=os.environ.get(
                "TRADERESEARCH_KEYCLOAK_CLIENT_SECRET", ""
            ),
            timeout=timeout,
        ).user(principal)
        if identity:
            values = list(permission_subjects(identity))
            legacy = (getattr(identity, "attributes", {}) or {}).get(
                "legacy_username"
            )
            if legacy:
                legacy_value = (
                    legacy[0] if isinstance(legacy, (tuple, list)) else legacy
                )
                legacy_subject = f"user:{legacy_value}"
                if legacy_subject not in values:
                    values.insert(0, legacy_subject)
            if direct[0] not in values:
                values.insert(0, direct[0])
            subjects = tuple(values)
        else:
            subjects = direct
        resolved = True
        ttl = _SUBJECT_CACHE_TTL_SECONDS
    except Exception:
        subjects = direct
        resolved = False
        ttl = _SUBJECT_CACHE_FAILURE_TTL_SECONDS
    with _SUBJECT_CACHE_LOCK:
        if len(_SUBJECT_CACHE) >= _SUBJECT_CACHE_LIMIT:
            # Keep this a small process-local memo, not another identity store.
            oldest = min(_SUBJECT_CACHE, key=lambda key: _SUBJECT_CACHE[key][0])
            _SUBJECT_CACHE.pop(oldest, None)
        _SUBJECT_CACHE[cache_key] = (now + ttl, subjects, resolved)
    return subjects, resolved


def subjects_for_user(username: str) -> list[str]:
    subjects, _resolved = resolve_permission_subjects(username)
    return list(subjects)
