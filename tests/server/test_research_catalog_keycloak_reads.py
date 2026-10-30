from types import SimpleNamespace

import pytest

from server.identity.keycloak_authorization import AuthorizationUnavailable, keycloak_resource_uri
from server.identity.keycloak_research import KeycloakResearchAuthorization
from server.manager.services.research_catalog import ResearchCatalog


class NoProfileGrants:
    def profile_membership_access_many(self, *, viewer, profiles):
        return {pair: {"can_view": False, "can_download": False} for pair in profiles}


def _fixture(tmp_path):
    path = tmp_path / "research.sqlite"
    legacy = ResearchCatalog(path)
    public = legacy.create_research(owner_ref="alice", title="Public", visibility="public")
    private = legacy.create_research(owner_ref="alice", title="Private", visibility="private")
    legacy.register_report(public["research_id"], actor="alice", report_id="public-report", visibility="public")
    legacy.register_report(private["research_id"], actor="alice", report_id="private-report")
    legacy.link_evidence(public["research_id"], actor="alice", evidence_owner_ref="alice",
        evidence_ref="evidence:job:sha256:" + "a" * 64, report_id="public-report")
    permissions, calls = set(), []
    def authorize(token, *, permissions, **_kwargs):
        calls.append((token, len(permissions)))
        if ("offline", "offline") in permissions_state:
            raise AuthorizationUnavailable("offline")
        return {(uri, scope): (uri, scope) in permissions_state for uri, _name, scope in permissions}
    permissions_state = permissions
    auth = KeycloakResearchAuthorization(
        identity_provider=lambda viewer: SimpleNamespace(token="verified", subject="subject", identity_id="stable") if viewer else None,
        authorize_many=authorize)
    catalog = ResearchCatalog(path, research_authorizer=auth, profile_authorizer=NoProfileGrants())
    return catalog, public["research_id"], private["research_id"], permissions, calls


def _grant(permissions, kind, ref, *scopes):
    uri = keycloak_resource_uri(kind, ref)
    permissions.update((uri, scope) for scope in scopes)


def test_strict_catalog_never_uses_legacy_public_or_same_name_owner(tmp_path):
    catalog, public, _private, permissions, _calls = _fixture(tmp_path)
    assert catalog.list_researches(viewer="alice") == []
    assert catalog.list_researches(viewer="bob") == []
    assert catalog.list_reports_for_scope(viewer="bob") == []
    with pytest.raises(PermissionError):
        catalog.get_research(public, viewer="alice")
    _grant(permissions, "research", public, "read", "use", "manage")
    result = catalog.list_researches(viewer="bob")
    assert [item["research_id"] for item in result] == [public]
    assert result[0]["authorized_users"] == []
    permissions.clear()
    assert catalog.list_researches(viewer="bob") == []


def test_strict_catalog_batches_research_and_report_scopes_and_propagates_outage(tmp_path):
    catalog, public, _private, permissions, calls = _fixture(tmp_path)
    _grant(permissions, "research", public, "read", "use")
    _grant(permissions, "research_report", "private-report", "read")
    rows = catalog.list_reports_for_scope(viewer="bob")
    assert {row["report_id"] for row in rows} == {"public-report", "private-report"}
    assert next(row for row in rows if row["report_id"] == "private-report")["access"]["can_download"] is False
    assert calls == [("verified", 6), ("verified", 6)]
    permissions.add(("offline", "offline"))
    with pytest.raises(AuthorizationUnavailable):
        catalog.list_researches(viewer="bob")


def test_strict_catalog_does_not_write_legacy_share_grants(tmp_path):
    catalog, public, _private, permissions, _calls = _fixture(tmp_path)
    _grant(permissions, "research", public, "read", "manage")
    with pytest.raises(RuntimeError, match="Keycloak grant migration"):
        catalog.create_share_link(target_kind="research", research_id=public, actor="alice")
    with pytest.raises(RuntimeError, match="Keycloak grant migration"):
        catalog.redeem_share_link("old-token", actor="alice")


def test_strict_catalog_does_not_grant_evidence_by_legacy_owner_name(tmp_path):
    catalog, public, _private, permissions, _calls = _fixture(tmp_path)
    ref = "evidence:job:sha256:" + "a" * 64
    assert catalog.resolve_evidence_access(evidence_ref=ref, viewer="alice")["can_view"] is False
    _grant(permissions, "research", public, "read", "use")
    access = catalog.resolve_evidence_access(evidence_ref=ref, viewer="alice")
    assert access["can_download"] is True and access["can_manage"] is False


def test_strict_catalog_cannot_disable_profile_membership_checks(tmp_path):
    with pytest.raises(ValueError, match="Profile membership"):
        ResearchCatalog(tmp_path / "invalid.sqlite", research_authorizer=object())
