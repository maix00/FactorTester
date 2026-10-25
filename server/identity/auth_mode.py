"""Controlled legacy/Keycloak authentication rollout."""

from __future__ import annotations

from server import branding

MODES = {"legacy", "keycloak", "dual"}


def auth_mode() -> str:
    value = branding.env("AUTH_MODE", "legacy").strip().lower()
    return value if value in MODES else "legacy"


def keycloak_enabled() -> bool:
    return auth_mode() in {"keycloak", "dual"}


def legacy_enabled() -> bool:
    return auth_mode() in {"legacy", "dual"}
