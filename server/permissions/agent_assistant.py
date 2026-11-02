"""Keycloak client-role gate for the Profile Agent Assistant."""

from __future__ import annotations


RESOURCE_TYPE = "agent_assistant"
RESOURCE_REF = "global"
ACTION = "use"


def can_use_agent_assistant(session: object, *, public_server: bool) -> bool:
    """Require the live Keycloak role for this Manager's execution location."""
    from server.identity.server_admission import current_manager_role

    location = "public" if public_server else "internal"
    return current_manager_role(session, f"{RESOURCE_TYPE}:{location}:{ACTION}")
