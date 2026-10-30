"""Keycloak client-role gate for the Profile Agent Assistant."""

from __future__ import annotations


RESOURCE_TYPE = "agent_assistant"
RESOURCE_REF = "global"
ACTION = "use"


def can_use_agent_assistant(username: str, role: str = "", keycloak_roles=()) -> bool:
    """Require an explicit Keycloak client role; local roles never bypass it."""
    del role
    return bool(str(username or "").strip()) and f"{RESOURCE_TYPE}:{ACTION}" in keycloak_roles
