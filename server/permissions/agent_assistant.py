"""Explicit platform permission checks for the Profile Agent Assistant."""

from __future__ import annotations

import os
import sqlite3

from server.permissions.entries import PermissionStore
from server.permissions.subjects import resolve_permission_subjects


RESOURCE_TYPE = "agent_assistant"
RESOURCE_REF = "global"
ACTION = "use"


def can_use_agent_assistant(username: str, role: str = "", keycloak_roles=()) -> bool:
    """Check live permission entries against the caller's Keycloak subjects.

    Super administrators retain the existing platform administration access.
    Everyone else needs an explicit allow. If Keycloak is configured but
    unavailable, group/org membership cannot be trusted and access fails
    closed. Direct grants work without Keycloak configuration.
    """
    from server.identity.auth_mode import auth_mode
    if auth_mode() == "keycloak":
        return bool(username) and "agent_assistant:use" in keycloak_roles
    principal = str(username or "").strip()
    if not principal:
        return False
    if str(role or "").strip() == "super_admin":
        return True
    db_path = (
        os.environ.get("TRADERESEARCH_PERMISSIONS_DB", "")
        or os.environ.get("FACTORTESTER_PERMISSIONS_DB", "")
    )
    if not db_path:
        return False
    subjects, resolved = resolve_permission_subjects(principal)
    if not resolved:
        return False
    try:
        return PermissionStore(db_path).allows_any(
            subjects=subjects,
            resource_type=RESOURCE_TYPE,
            resource_ref=RESOURCE_REF,
            action=ACTION,
        )
    except (OSError, sqlite3.Error, ValueError):
        return False
