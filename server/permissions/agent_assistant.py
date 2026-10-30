"""Keycloak client-role gate for the Profile Agent Assistant."""

from __future__ import annotations


RESOURCE_TYPE = "agent_assistant"
RESOURCE_REF = "global"
ACTION = "use"


def can_use_agent_assistant(session: object) -> bool:
    """Require the current Keycloak role, not just a stale token claim."""
    from server.identity.server_admission import current_manager_role

    return current_manager_role(session, f"{RESOURCE_TYPE}:{ACTION}")
