"""Canonical Keycloak wiring for Manager-owned Research objects."""

from __future__ import annotations


def create_keycloak_research_catalog(database):
    """Create a catalog whose request-time permissions come only from Keycloak.

    Historical ACL columns remain available to the explicit migration tools;
    production Manager and data-plane paths must not interpret them as grants.
    """
    from server.identity.keycloak_research import (
        KeycloakResearchAuthorization,
        KeycloakResearchGrantManager,
        resolve_keycloak_research_member,
    )
    from server.manager.services.research_catalog import ResearchCatalog

    authorization = KeycloakResearchAuthorization()
    return ResearchCatalog(
        database,
        research_authorizer=authorization,
        profile_authorizer=authorization,
        profile_grant_manager=KeycloakResearchGrantManager(),
        profile_identity_resolver=resolve_keycloak_research_member,
    )


def create_keycloak_research_transfer_authorizer(database, *, catalog=None):
    """Build the source-side live policy checker used by 7997 object reads."""
    from server.identity.keycloak_research_transfer import (
        KeycloakResearchTransferAuthorization,
    )

    return KeycloakResearchTransferAuthorization(
        catalog or create_keycloak_research_catalog(database),
    )
