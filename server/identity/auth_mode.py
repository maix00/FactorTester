"""Keycloak is the sole identity and permission authority.

Local-password identity is retired. No deployment setting can reopen it.
"""

from __future__ import annotations

from server import branding

MODES = {"keycloak"}


def auth_mode() -> str:
    value = branding.env("AUTH_MODE", "keycloak").strip().lower()
    return value if value in MODES else "keycloak"


def keycloak_enabled() -> bool:
    return True


def legacy_enabled() -> bool:
    # Kept as a narrow compatibility predicate for older callers.
    return False
