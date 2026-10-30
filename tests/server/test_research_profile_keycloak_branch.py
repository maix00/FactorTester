from __future__ import annotations

import sqlite3

import pytest

from server.identity.keycloak_authorization import AuthorizationUnavailable, keycloak_resource_uri
from server.identity.keycloak_research import KeycloakResearchAuthorization, profile_resource_ref
from server.identity.request_context import bind_verified_identity, identity_request
from server.manager.services.research_catalog import ResearchCatalog


def test_branch_profile_uses_verified_keycloak_decision_and_rechecks_each_write(tmp_path):
    path = tmp_path / "research.sqlite"
    legacy = ResearchCatalog(path)
    research_id = legacy.create_research(owner_ref="alice", title="Research")["research_id"]
    legacy.register_report(research_id, actor="alice", report_id="report", profile_ref="self")
    legacy.add_membership(research_id, actor="alice", principal_ref="bob", profile_ref="self", role="editor")
    legacy.create_workspace(research_id, actor="alice", principal_ref="bob", profile_ref="self")
    uri = keycloak_resource_uri("research_profile", profile_resource_ref(research_id, "bob-id", "self"))
    allowed = {("bob-token", uri, "write")}

    def authorize(token, *, permissions):
        # Network authorization must happen before the SQLite write lock.
        with sqlite3.connect(path, timeout=0.1) as db:
            db.execute("BEGIN IMMEDIATE")
            db.rollback()
        return {(resource, scope): (token, resource, scope) in allowed
                for resource, _name, scope in permissions}

    auth = KeycloakResearchAuthorization(authorize_many=authorize)
    catalog = ResearchCatalog(path, profile_authorizer=auth)
    bob = {"username": "bob", "keycloak_subject": "bob-subject", "tr_identity_id": "bob-id",
           "keycloak_issuer": "https://identity.example/realms/trade"}

    # Local role data is only a migration artifact after the Profile switch.
    with sqlite3.connect(path) as db:
        db.execute("UPDATE research_catalog_memberships SET role='viewer' WHERE principal_ref='bob'")
    with pytest.raises(PermissionError, match="exact Profile"):
        catalog.reserve_report_branch("report", actor="bob", profile_ref="self", branch_id="review")
    with identity_request():
        bind_verified_identity("bob-token", bob)
        value = catalog.reserve_report_branch("report", actor="bob", profile_ref="self", branch_id="review")
        assert value["principal_ref"] == "bob"
        # Keycloak revocation takes effect on the next decision even though
        # the local membership/workspace still exist.
        allowed.clear()
        with pytest.raises(PermissionError, match="exact Profile"):
            catalog.publish_report_branch("report", "review", actor="bob", profile_ref="self",
                expected_generation=0, expected_revision="", generation=1, revision="a" * 64,
                publication_id="p" * 24, storage_server_id="server")


def test_branch_profile_authorization_outage_is_not_converted_to_grant_or_denial(tmp_path):
    path = tmp_path / "research.sqlite"
    catalog = ResearchCatalog(path)
    research_id = catalog.create_research(owner_ref="alice", title="Research")["research_id"]
    catalog.register_report(research_id, actor="alice", report_id="report", profile_ref="self")
    class Unavailable:
        def may_write_profile(self, **_kwargs):
            raise AuthorizationUnavailable("Keycloak unavailable")
    catalog = ResearchCatalog(path, profile_authorizer=Unavailable())
    with pytest.raises(AuthorizationUnavailable):
        catalog.reserve_report_branch("report", actor="alice", profile_ref="self", branch_id="main")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM research_catalog_branches").fetchone()[0] == 0
